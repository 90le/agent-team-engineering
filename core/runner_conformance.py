"""Fail-closed planning and report validation for disposable isolated runners.

This module never starts a process.  It turns an already validated execution
request into a fixed OCI argv for trusted worker composition code.  The live
probe is a separate opt-in tool that refuses production storage hosts.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from core.isolation import IsolationViolation, validate_execution_request
from core.json_support import loads_strict
from core.schema_validation import validate_schema
from core.security import find_inline_secret

ROOT = Path(__file__).resolve().parents[1]
PROFILE_SCHEMA = ROOT / "schemas" / "sandbox-profile.schema.json"
REPORT_SCHEMA = ROOT / "schemas" / "runner-conformance-report.schema.json"
IMAGE_DIGEST = re.compile(r"^sha256:[a-f0-9]{64}$")
CONTAINER_NAME = re.compile(r"^agent-team-[a-z0-9][a-z0-9-]{0,62}$")
REQUIRED_PROBES = (
    "non-root-user",
    "read-only-source",
    "ephemeral-workspace",
    "read-only-root",
    "no-production-mounts",
    "no-docker-socket",
    "no-inherited-secrets",
    "network-denied",
    "timeout-termination",
    "resource-limit",
    "residue-cleanup",
)
DISPOSABLE_ACK = "I_UNDERSTAND_THIS_RUNNER_IS_DISPOSABLE"
PRODUCTION_SENTINELS = (Path("/srv/appdata"), Path("/mnt/synology"), Path("/etc/pve"))


class RunnerConformanceError(RuntimeError):
    """Raised before an unsafe or unsupported runner plan is accepted."""


def assert_disposable_worker(
    environment: Mapping[str, str],
    *,
    path_exists: Callable[[Path], bool] = Path.exists,
) -> None:
    """Refuse live probes unless GitHub attests a hosted ephemeral Linux runner."""

    required = {
        "CI": "true",
        "GITHUB_ACTIONS": "true",
        "RUNNER_ENVIRONMENT": "github-hosted",
        "RUNNER_OS": "Linux",
        "AGENT_TEAM_DISPOSABLE_ACK": DISPOSABLE_ACK,
    }
    wrong = [key for key, expected in required.items() if environment.get(key) != expected]
    if wrong:
        raise RunnerConformanceError(
            "live runner probe requires GitHub-hosted disposable attestation: "
            + ", ".join(sorted(wrong))
        )
    if environment.get("GITHUB_EVENT_NAME") not in {"pull_request", "workflow_dispatch"}:
        raise RunnerConformanceError("live runner probe is limited to PR or manual workflows")
    present = [str(path) for path in PRODUCTION_SENTINELS if path_exists(path)]
    if present:
        raise RunnerConformanceError(
            "refusing a host with production/PVE storage sentinels: " + ", ".join(present)
        )


def _canonical(value: Any) -> str:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _schema(path: Path) -> dict[str, Any]:
    value = loads_strict(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RunnerConformanceError(f"schema root is not an object: {path.name}")
    return value


def _validate(document: dict[str, Any], schema_path: Path, label: str) -> None:
    issues = validate_schema(document, _schema(schema_path))
    if issues:
        details = "; ".join(f"{issue.path}: {issue.message}" for issue in issues)
        raise RunnerConformanceError(f"invalid {label}: {details}")
    secret_path = find_inline_secret(document)
    if secret_path is not None:
        raise RunnerConformanceError(f"{label} contains inline secret-like data at {secret_path}")


def validate_sandbox_profile(document: dict[str, Any]) -> dict[str, Any]:
    _validate(document, PROFILE_SCHEMA, "sandbox profile")
    denied = set(str(value) for value in document["mounts"]["denied_host_paths"])
    required_denials = {
        "/srv/appdata",
        "/mnt/synology",
        "/etc/pve",
        "/root",
        "/home",
        "/var/run/docker.sock",
    }
    missing = sorted(required_denials - denied)
    if missing:
        raise RunnerConformanceError(
            "sandbox profile does not deny required host paths: " + ", ".join(missing)
        )
    return loads_strict(_canonical(document))


def load_sandbox_profile(path: Path) -> dict[str, Any]:
    value = loads_strict(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RunnerConformanceError("sandbox profile root must be an object")
    return validate_sandbox_profile(value)


def build_native_oci_plan(
    request: dict[str, Any],
    profile: dict[str, Any],
    *,
    source_directory: Path,
    resolved_image_digest: str,
    container_name: str,
    command_registry: Mapping[str, Sequence[str]],
    docker_binary: str = "docker",
) -> dict[str, Any]:
    """Build argv only; trusted worker code decides whether and where to run it."""

    profile = validate_sandbox_profile(profile)
    try:
        validate_execution_request(
            request,
            allowed_command_ids=command_registry,
            allowed_secret_refs=(),
            maximum_timeout_seconds=int(profile["resources"]["timeout_seconds"]),
        )
    except IsolationViolation as error:
        raise RunnerConformanceError(str(error)) from error
    if request["network_policy"] != "none" or request["network_allowlist"]:
        raise RunnerConformanceError("the v0.8 reference profile permits no sandbox network")
    if request["secret_refs"]:
        raise RunnerConformanceError("the v0.8 conformance runner accepts no secret reference")
    if request["arguments"]:
        raise RunnerConformanceError("reference conformance commands do not accept task argv")
    command = tuple(str(value) for value in command_registry[request["command_id"]])
    if not command or any(not value or "\x00" in value for value in command):
        raise RunnerConformanceError("trusted command registry contains invalid argv")
    if not IMAGE_DIGEST.fullmatch(resolved_image_digest):
        raise RunnerConformanceError("worker image must be resolved to an immutable sha256 ID")
    if not CONTAINER_NAME.fullmatch(container_name):
        raise RunnerConformanceError("container name is invalid")
    if source_directory.is_symlink():
        raise RunnerConformanceError("source directory cannot be a symbolic link")
    source = source_directory.resolve()
    if not source.is_dir():
        raise RunnerConformanceError("source directory does not exist")
    for denied_value in profile["mounts"]["denied_host_paths"]:
        denied = Path(str(denied_value)).resolve()
        if source == denied or denied in source.parents:
            raise RunnerConformanceError(
                f"source directory is inside a denied host path: {denied}"
            )
    resources = profile["resources"]
    argv = [
        docker_binary,
        "run",
        "--rm",
        "--name",
        container_name,
        "--read-only",
        "--network",
        "none",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges:true",
        "--pids-limit",
        str(resources["pids"]),
        "--memory",
        f"{resources['memory_mib']}m",
        "--memory-swap",
        f"{resources['memory_mib']}m",
        "--cpus",
        str(resources["cpus"]),
        "--user",
        profile["process"]["user"],
        "--workdir",
        "/workspace",
        "--tmpfs",
        f"/workspace:rw,nosuid,nodev,size={resources['workspace_mib']}m,mode=1777",
        "--tmpfs",
        "/tmp:rw,nosuid,nodev,noexec,size=8m,mode=1777",
        "--mount",
        f"type=bind,src={source},dst=/source,readonly",
        "--env",
        "HOME=/workspace",
        "--env",
        "PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
        resolved_image_digest,
        *command,
    ]
    binding = {
        "request": request,
        "profile": profile,
        "source": str(source),
        "resolved_image_digest": resolved_image_digest,
        "container_name": container_name,
        "command": list(command),
    }
    return {
        "argv": argv,
        "environment": {"PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"},
        "timeout_seconds": int(request["timeout_seconds"]),
        "output_bytes": int(resources["output_bytes"]),
        "plan_digest": "sha256:"
        + hashlib.sha256(_canonical(binding).encode("utf-8")).hexdigest(),
    }


def validate_runner_report(document: dict[str, Any]) -> dict[str, Any]:
    _validate(document, REPORT_SCHEMA, "runner conformance report")
    required = set(str(value) for value in document["required_probe_ids"])
    missing_required = sorted(set(REQUIRED_PROBES) - required)
    if missing_required:
        raise RunnerConformanceError(
            "runner report omits required probes: " + ", ".join(missing_required)
        )
    all_passed = True
    for run in document["runs"]:
        results = run["probe_results"]
        missing = sorted(required - set(results))
        if missing:
            raise RunnerConformanceError(
                f"{run['run_id']} omits probes: {', '.join(missing)}"
            )
        passed = run["status"] == "PASS" and all(results[key] == "PASS" for key in required)
        passed = passed and run["container_residue"] == 0
        all_passed = all_passed and passed
    eligible = all_passed and document["score"] >= 80 and document["cleanup_verified"]
    if document["hard_gate_passed"] is not eligible:
        raise RunnerConformanceError("hard_gate_passed differs from measured report results")
    expected_decision = "REFERENCE_ELIGIBLE" if eligible else "NO_GO"
    if document["decision"] != expected_decision:
        raise RunnerConformanceError("runner decision differs from hard-gate policy")
    return loads_strict(_canonical(document))
