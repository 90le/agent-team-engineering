#!/usr/bin/env python3
"""Run fixed runner conformance probes on a GitHub-hosted disposable worker only."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.runner_conformance import (  # noqa: E402
    REQUIRED_PROBES,
    RunnerConformanceError,
    assert_disposable_worker,
    build_native_oci_plan,
    load_sandbox_profile,
    validate_runner_report,
)

PROFILE = ROOT / "examples" / "v08-contracts" / "valid" / "sandbox-profile.json"
IMAGE_REFERENCE = "alpine:3.22"
PROBE_SOURCE = r'''#!/bin/sh
set -u

pass() { printf 'PASS:%s\n' "$1"; }

[ "$(id -u)" != "0" ] && pass non-root-user
if ! touch /source/should-not-exist 2>/dev/null; then pass read-only-source; fi
if touch /workspace/write-ok && rm /workspace/write-ok; then pass ephemeral-workspace; fi
if ! touch /root-filesystem-write 2>/dev/null; then pass read-only-root; fi
if [ ! -e /srv/appdata ] && [ ! -e /mnt/synology ] && [ ! -e /etc/pve ]; then
  pass no-production-mounts
fi
if [ ! -S /var/run/docker.sock ]; then pass no-docker-socket; fi
if ! env | cut -d= -f1 | grep -Eiq '(token|secret|password|credential|private_key|api_key)'; then
  pass no-inherited-secrets
fi
if ! wget -T 1 -qO- http://1.1.1.1/ >/dev/null 2>&1; then pass network-denied; fi

memory_limit="$(cat /sys/fs/cgroup/memory.max 2>/dev/null || cat /sys/fs/cgroup/memory/memory.limit_in_bytes 2>/dev/null || true)"
pids_limit="$(cat /sys/fs/cgroup/pids.max 2>/dev/null || cat /sys/fs/cgroup/pids/pids.max 2>/dev/null || true)"
if [ "$memory_limit" = "67108864" ] && [ "$pids_limit" = "32" ]; then pass resource-limit; fi
'''


def _run(
    arguments: list[str],
    *,
    timeout: float,
    environment: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        arguments,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=environment,
        shell=False,
    )


def _container_residue(docker: str, prefixes: tuple[str, ...]) -> int:
    result = _run(
        [docker, "ps", "-a", "--format", "{{.Names}}"],
        timeout=10,
    )
    if result.returncode != 0:
        raise RunnerConformanceError("cannot verify container cleanup")
    return sum(
        1
        for name in result.stdout.splitlines()
        if any(name.startswith(prefix) for prefix in prefixes)
    )


def _cleanup_container(docker: str, name: str) -> None:
    _run([docker, "rm", "-f", name], timeout=10)


def _request(run_id: str, *, command_id: str, timeout_seconds: int) -> dict:
    return {
        "schema_version": "1.0.0",
        "job_id": f"job-{run_id}",
        "work_item_id": "work-runner-conformance",
        "project_id": "project.runner-conformance",
        "source_ref": "project-source:project.runner-conformance@main",
        "commit": "0" * 40,
        "command_id": command_id,
        "arguments": [],
        "workspace_id": f"workspace-{run_id}",
        "timeout_seconds": timeout_seconds,
        "network_policy": "none",
        "network_allowlist": [],
        "secret_refs": [],
        "source_read_only": True,
        "workspace_ephemeral": True,
        "production_mounts": False,
        "docker_socket": False,
        "privileged": False,
    }


def _normal_probe(
    docker: str,
    profile: dict,
    source: Path,
    image_id: str,
    index: int,
) -> tuple[dict[str, str], bool]:
    name = f"agent-team-conformance-{index}"
    plan = build_native_oci_plan(
        _request(f"probe-{index}", command_id="probe", timeout_seconds=10),
        profile,
        source_directory=source,
        resolved_image_digest=image_id,
        container_name=name,
        command_registry={"probe": ("/bin/sh", "/source/probe.sh")},
        docker_binary=docker,
    )
    try:
        result = _run(
            plan["argv"],
            timeout=float(plan["timeout_seconds"]) + 5,
            environment=plan["environment"],
        )
    except subprocess.TimeoutExpired:
        _cleanup_container(docker, name)
        return {}, False
    markers = {
        line.removeprefix("PASS:").strip()
        for line in result.stdout.splitlines()
        if line.startswith("PASS:")
    }
    measured = {
        probe: ("PASS" if probe in markers else "FAIL")
        for probe in REQUIRED_PROBES
        if probe not in {"timeout-termination", "residue-cleanup"}
    }
    return measured, result.returncode == 0


def _timeout_probe(
    docker: str,
    profile: dict,
    source: Path,
    image_id: str,
    index: int,
) -> bool:
    name = f"agent-team-timeout-{index}"
    plan = build_native_oci_plan(
        _request(f"timeout-{index}", command_id="timeout", timeout_seconds=1),
        profile,
        source_directory=source,
        resolved_image_digest=image_id,
        container_name=name,
        command_registry={"timeout": ("/bin/sleep", "30")},
        docker_binary=docker,
    )
    timed_out = False
    try:
        _run(plan["argv"], timeout=2, environment=plan["environment"])
    except subprocess.TimeoutExpired:
        timed_out = True
    finally:
        _cleanup_container(docker, name)
    return timed_out


def _resolve_image(docker: str) -> str:
    pulled = _run([docker, "pull", IMAGE_REFERENCE], timeout=180)
    if pulled.returncode != 0:
        raise RunnerConformanceError("failed to pull the fixed conformance image")
    inspected = _run(
        [docker, "image", "inspect", "--format={{.Id}}", IMAGE_REFERENCE],
        timeout=20,
    )
    image_id = inspected.stdout.strip()
    if inspected.returncode != 0 or not image_id.startswith("sha256:"):
        raise RunnerConformanceError("failed to resolve conformance image to sha256 ID")
    return image_id


def run_probe(output: Path) -> dict:
    assert_disposable_worker(os.environ)
    docker = shutil.which("docker")
    if docker is None:
        raise RunnerConformanceError("docker is unavailable on the disposable worker")
    profile = load_sandbox_profile(PROFILE)
    image_id = _resolve_image(docker)
    temporary = Path(tempfile.mkdtemp(prefix="agent-team-conformance-", dir="/tmp"))
    prefixes = ("agent-team-conformance-", "agent-team-timeout-")
    runs: list[dict] = []
    try:
        source = temporary / "source"
        source.mkdir()
        script = source / "probe.sh"
        script.write_text(PROBE_SOURCE, encoding="utf-8")
        script.chmod(0o755)
        for index in range(1, 4):
            started = time.monotonic()
            measured, command_ok = _normal_probe(docker, profile, source, image_id, index)
            measured["timeout-termination"] = (
                "PASS" if _timeout_probe(docker, profile, source, image_id, index) else "FAIL"
            )
            residue = _container_residue(docker, prefixes)
            measured["residue-cleanup"] = "PASS" if residue == 0 else "FAIL"
            passed = command_ok and all(
                measured.get(probe) == "PASS" for probe in REQUIRED_PROBES
            )
            runs.append(
                {
                    "run_id": f"run-{index}",
                    "status": "PASS" if passed else "FAIL",
                    "probe_results": measured,
                    "container_residue": residue,
                    "duration_milliseconds": int((time.monotonic() - started) * 1000),
                }
            )
    finally:
        for prefix in prefixes:
            result = _run(
                [docker, "ps", "-aq", "--filter", f"name=^{prefix}"],
                timeout=10,
            )
            for container_id in result.stdout.splitlines():
                _cleanup_container(docker, container_id.strip())
        shutil.rmtree(temporary, ignore_errors=False)

    cleanup_verified = not temporary.exists() and _container_residue(docker, prefixes) == 0
    all_passed = cleanup_verified and all(run["status"] == "PASS" for run in runs)
    score = round(
        100
        * sum(
            result == "PASS"
            for run in runs
            for result in run["probe_results"].values()
        )
        / (len(REQUIRED_PROBES) * len(runs))
    )
    report = {
        "schema_version": "1.0.0",
        "candidate_id": "runner.native-oci",
        "profile_id": profile["profile_id"],
        "environment_kind": profile["environment"]["kind"],
        "resolved_image_digest": image_id,
        "required_probe_ids": list(REQUIRED_PROBES),
        "runs": runs,
        "score": score,
        "hard_gate_passed": all_passed and score >= 80,
        "decision": "REFERENCE_ELIGIBLE" if all_passed and score >= 80 else "NO_GO",
        "cleanup_verified": cleanup_verified,
    }
    validate_runner_report(report)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    try:
        report = run_probe(arguments.output.resolve())
    except (RunnerConformanceError, OSError, subprocess.SubprocessError) as error:
        print(f"runner probe refused or failed: {error}", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "candidate_id": report["candidate_id"],
                "decision": report["decision"],
                "score": report["score"],
                "cleanup_verified": report["cleanup_verified"],
            },
            sort_keys=True,
        )
    )
    return 0 if report["hard_gate_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
