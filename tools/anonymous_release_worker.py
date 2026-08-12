#!/usr/bin/env python3
"""Run candidate-controlled anonymous release checks behind a Linux UID boundary."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import resource
import signal
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

COMMIT = re.compile(r"^[a-f0-9]{40}$")
DIGEST = re.compile(r"^sha256:[a-f0-9]{64}$")
SOURCE_URL = "https://github.com/90le/agent-team-engineering.git"
ANONYMOUS_COMMANDS = (
    "systemd transient cgroup with memory/CPU/PID/file/tmpfs limits; setpriv random unregistered UID; no groups/capabilities; no-new-privileges; verify credential-parent /proc isolation",
    "git clone --no-local --no-checkout https://github.com/90le/agent-team-engineering.git <temporary>",
    "git verify annotated tag object and peeled commit",
    "git checkout --detach <peeled-tag-commit>; verify clean exact HEAD",
    "factory install; factory verify; doctor",
    "create and validate portable team",
    "host plan; preview; confirm; apply; verify; uninstall-preview; uninstall; replay",
    "native writer-authority-validate",
)
COMMAND_TIMEOUT_SECONDS = 300
MAX_COMMAND_OUTPUT_BYTES = 16 * 1024 * 1024
EXPECTED_MEMORY_MAX_BYTES = 1024 * 1024 * 1024
EXPECTED_MEMORY_SWAP_MAX_BYTES = 0
EXPECTED_TASKS_MAX = 128
EXPECTED_CPU_QUOTA_US = 200_000
EXPECTED_CPU_PERIOD_US = 100_000
EXPECTED_FILE_SIZE_LIMIT_BYTES = 16 * 1024 * 1024
EXPECTED_TMPFS_BYTES = 512 * 1024 * 1024


class AnonymousWorkerError(RuntimeError):
    pass


def _strict_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _loads_strict(content: str) -> Any:
    return json.loads(
        content,
        object_pairs_hook=_strict_pairs,
        parse_constant=lambda value: (_ for _ in ()).throw(
            ValueError(f"non-finite JSON value: {value}")
        ),
    )


def _digest(value: str, label: str) -> str:
    if DIGEST.fullmatch(value) is None:
        raise AnonymousWorkerError(f"{label} is not a SHA-256 digest")
    return value


def _commit(value: str, label: str) -> str:
    if COMMIT.fullmatch(value) is None:
        raise AnonymousWorkerError(f"{label} is not an exact Git commit")
    return value


def _anonymous_environment(home: Path) -> dict[str, str]:
    python_bin = str(Path(sys.executable).resolve().parent)
    return {
        "HOME": str(home),
        "PATH": os.pathsep.join(
            dict.fromkeys((python_bin, "/usr/local/bin", "/usr/bin", "/bin"))
        ),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PYTHONNOUSERSITE": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_SYSTEM": os.devnull,
        "GIT_TERMINAL_PROMPT": "0",
        "GCM_INTERACTIVE": "Never",
        "SSH_ASKPASS_REQUIRE": "never",
    }


def _run(arguments: list[str], cwd: Path, environment: dict[str, str]) -> str:
    label = " ".join(arguments[:4])
    with tempfile.TemporaryFile(mode="w+b") as stdout_file, tempfile.TemporaryFile(
        mode="w+b"
    ) as stderr_file:
        try:
            process = subprocess.Popen(
                arguments,
                cwd=cwd,
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=stdout_file,
                stderr=stderr_file,
                start_new_session=True,
                shell=False,
            )
            try:
                return_code = process.wait(timeout=COMMAND_TIMEOUT_SECONDS)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait()
                raise AnonymousWorkerError(
                    f"anonymous verification command timed out: {label}"
                ) from None
        except OSError:
            raise AnonymousWorkerError(
                f"anonymous verification command failed: {label}"
            ) from None
        for stream in (stdout_file, stderr_file):
            if os.fstat(stream.fileno()).st_size > MAX_COMMAND_OUTPUT_BYTES:
                raise AnonymousWorkerError(
                    "anonymous verification command output is too large"
                )
        if return_code != 0:
            raise AnonymousWorkerError(
                f"anonymous verification command failed: {label}"
            )
        stdout_file.seek(0)
        try:
            return stdout_file.read().decode("utf-8", errors="strict").strip()
        except UnicodeDecodeError:
            raise AnonymousWorkerError(
                "anonymous verification command output is not UTF-8"
            ) from None


def _read_exact_integer(path: Path, label: str) -> int:
    try:
        value = path.read_text(encoding="ascii").strip()
        if not value.isdigit():
            raise ValueError
        return int(value)
    except (OSError, ValueError):
        raise AnonymousWorkerError(f"{label} is unavailable") from None


def _resource_boundary() -> dict[str, Any]:
    try:
        cgroup_entry = next(
            line.split("::", 1)[1]
            for line in Path("/proc/self/cgroup").read_text(encoding="ascii").splitlines()
            if line.startswith("0::")
        )
    except (OSError, StopIteration):
        raise AnonymousWorkerError("unified resource cgroup is unavailable") from None
    if re.fullmatch(r"/system\.slice/agent-team-v1-anonymous-[a-f0-9]{16}\.service", cgroup_entry) is None:
        raise AnonymousWorkerError("worker is not inside the declared transient cgroup")
    cgroup = Path("/sys/fs/cgroup") / cgroup_entry.lstrip("/")
    if (
        _read_exact_integer(cgroup / "memory.max", "memory limit")
        != EXPECTED_MEMORY_MAX_BYTES
        or _read_exact_integer(cgroup / "memory.swap.max", "swap limit")
        != EXPECTED_MEMORY_SWAP_MAX_BYTES
        or _read_exact_integer(cgroup / "pids.max", "process limit")
        != EXPECTED_TASKS_MAX
    ):
        raise AnonymousWorkerError("worker cgroup resource limits differ")
    try:
        cpu_quota, cpu_period = (
            int(value)
            for value in (cgroup / "cpu.max").read_text(encoding="ascii").split()
        )
    except (OSError, ValueError):
        raise AnonymousWorkerError("CPU quota is unavailable") from None
    if (cpu_quota, cpu_period) != (
        EXPECTED_CPU_QUOTA_US,
        EXPECTED_CPU_PERIOD_US,
    ):
        raise AnonymousWorkerError("worker CPU quota differs")
    file_limit = resource.getrlimit(resource.RLIMIT_FSIZE)
    if file_limit != (
        EXPECTED_FILE_SIZE_LIMIT_BYTES,
        EXPECTED_FILE_SIZE_LIMIT_BYTES,
    ):
        raise AnonymousWorkerError("worker file-size limit differs")
    filesystem = os.statvfs("/tmp")
    tmpfs_bytes = filesystem.f_frsize * filesystem.f_blocks
    if tmpfs_bytes != EXPECTED_TMPFS_BYTES:
        raise AnonymousWorkerError("worker temporary-filesystem limit differs")
    try:
        mount_record = next(
            line
            for line in Path("/proc/self/mountinfo").read_text(encoding="utf-8").splitlines()
            if len(line.split()) > 8 and line.split()[4] == "/tmp"
        )
    except (OSError, StopIteration):
        raise AnonymousWorkerError("private temporary filesystem is unavailable") from None
    if " - tmpfs " not in mount_record:
        raise AnonymousWorkerError("worker /tmp is not a private tmpfs")
    return {
        "resource_isolation": {
            "cgroup_v2": True,
            "process_tree_cgroup_isolated": True,
            "bounded_output_capture": True,
            "memory_max_bytes": EXPECTED_MEMORY_MAX_BYTES,
            "memory_swap_max_bytes": EXPECTED_MEMORY_SWAP_MAX_BYTES,
            "tasks_max": EXPECTED_TASKS_MAX,
            "cpu_quota_percent": EXPECTED_CPU_QUOTA_US // 1000,
            "file_size_limit_bytes": EXPECTED_FILE_SIZE_LIMIT_BYTES,
            "temporary_filesystem_limit_bytes": EXPECTED_TMPFS_BYTES,
        }
    }


def _linux_process_boundary(credential_parent_pid: int) -> dict[str, Any]:
    if sys.platform != "linux" or not Path("/proc/self/status").is_file():
        raise AnonymousWorkerError("anonymous verification requires Linux procfs")
    if credential_parent_pid < 2 or credential_parent_pid == os.getpid():
        raise AnonymousWorkerError("credential parent process identity is invalid")
    try:
        Path(f"/proc/{credential_parent_pid}/environ").read_bytes()
    except PermissionError:
        parent_environment_readable = False
    except OSError:
        raise AnonymousWorkerError(
            "credential parent process cannot be verified as a live isolated process"
        ) from None
    else:
        parent_environment_readable = True

    def read_status(pid: str) -> dict[str, str]:
        observed: dict[str, str] = {}
        for line in Path(f"/proc/{pid}/status").read_text(
            encoding="utf-8"
        ).splitlines():
            key, separator, value = line.partition(":")
            if separator:
                observed[key] = value.strip()
        return observed

    status = read_status("self")
    parent_status = read_status(str(credential_parent_pid))
    for field in ("Uid", "Gid"):
        values = status.get(field, "").split()
        if len(values) != 4 or len(set(values)) != 1:
            raise AnonymousWorkerError("worker identity transition is incomplete")
    self_uid = int(status["Uid"].split()[1])
    parent_uids = parent_status.get("Uid", "").split()
    if len(parent_uids) != 4:
        raise AnonymousWorkerError("credential parent identity is unavailable")
    parent_uid = int(parent_uids[1])
    supplementary_groups_empty = status.get("Groups", "") == ""
    credential_process_uid_isolated = self_uid != parent_uid
    capability_fields = ("CapInh", "CapPrm", "CapEff", "CapBnd", "CapAmb")
    try:
        capabilities_empty = all(int(status[field], 16) == 0 for field in capability_fields)
    except (KeyError, ValueError):
        raise AnonymousWorkerError("worker capability state is unavailable") from None
    no_new_privileges = status.get("NoNewPrivs") == "1"
    if (
        parent_environment_readable
        or not credential_process_uid_isolated
        or not supplementary_groups_empty
        or not capabilities_empty
        or not no_new_privileges
    ):
        raise AnonymousWorkerError("credential-process isolation boundary is not enforced")
    return {
        "credential_process_uid_isolated": True,
        "credential_parent_environment_readable": False,
        "supplementary_groups_empty": True,
        "no_new_privileges": True,
        "capabilities_empty": True,
        "isolation_mechanism": "linux-systemd-cgroup-setpriv-random-uid-v1",
        **_resource_boundary(),
    }


def _execute_workflow(
    release: str,
    expected_tag_object: str,
    expected_commit: str,
    workspace: Path,
    verified_at: str,
) -> dict[str, Any]:
    _commit(expected_tag_object, "annotated tag object")
    _commit(expected_commit, "peeled release commit")
    if not re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+", release):
        raise AnonymousWorkerError("release name is invalid")
    if not workspace.is_dir() or any(workspace.iterdir()):
        raise AnonymousWorkerError("anonymous workspace must be an empty directory")
    anonymous_home = workspace / "home"
    anonymous_home.mkdir(mode=0o700)
    environment = _anonymous_environment(anonymous_home)
    source = workspace / "source"
    installed = workspace / "installed"
    team = workspace / "team"
    projection = workspace / "projection"
    plan = workspace / "host-plan.json"
    commands: list[list[str]] = [
        [
            "git",
            "clone",
            "--quiet",
            "--no-local",
            "--no-checkout",
            SOURCE_URL,
            str(source),
        ],
        ["git", "rev-parse", f"refs/tags/{release}"],
        ["git", "cat-file", "-t", f"refs/tags/{release}"],
        ["git", "rev-parse", f"{release}^{{}}"],
    ]
    results = [
        _run(command, source if source.exists() else workspace, environment)
        for command in commands
    ]
    if (
        results[1] != expected_tag_object
        or results[2] != "tag"
        or results[3] != expected_commit
    ):
        raise AnonymousWorkerError(
            "anonymous clone tag identity differs from accepted release"
        )
    _run(
        [
            "git",
            "-c",
            "advice.detachedHead=false",
            "checkout",
            "--detach",
            expected_commit,
        ],
        source,
        environment,
    )
    if (
        _run(["git", "rev-parse", "HEAD"], source, environment)
        != expected_commit
        or _run(["git", "status", "--porcelain"], source, environment)
    ):
        raise AnonymousWorkerError(
            "anonymous working tree is not the clean peeled tag commit"
        )
    workflow = [
        [
            sys.executable,
            "tools/agent_team.py",
            "factory",
            "install",
            "--output",
            str(installed),
        ],
        [
            sys.executable,
            str(installed / "tools/agent_team.py"),
            "factory",
            "verify",
            "--root",
            str(installed),
        ],
        [sys.executable, str(installed / "tools/agent_team.py"), "doctor"],
        [
            str(installed / "agent-team"),
            "create",
            "--design",
            str(installed / "examples/context-first/team-design.json"),
            "--output",
            str(team),
        ],
        [str(installed / "agent-team"), "context", "validate", "--root", str(team)],
        [
            str(installed / "agent-team"),
            "host",
            "plan",
            "--team",
            str(team),
            "--target",
            "generic-ai",
            "--destination",
            str(projection),
            "--output",
            str(plan),
        ],
        [str(installed / "agent-team"), "host", "preview", "--plan", str(plan)],
    ]
    for command in workflow:
        _run(command, source, environment)
    try:
        plan_document = _loads_strict(plan.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise AnonymousWorkerError("anonymous host plan is invalid") from None
    digest = plan_document.get("proposal_digest") if isinstance(plan_document, dict) else None
    if not isinstance(digest, str):
        raise AnonymousWorkerError("anonymous host plan lacks an exact digest")
    _digest(digest, "anonymous host plan")
    remainder = [
        [
            str(installed / "agent-team"),
            "host",
            "confirm",
            "--plan",
            str(plan),
            "--digest",
            digest,
            "--approved-by",
            "Anonymous Release Verifier",
        ],
        [str(installed / "agent-team"), "host", "apply", "--plan", str(plan)],
        [str(installed / "agent-team"), "host", "verify", "--root", str(projection)],
        [
            str(installed / "agent-team"),
            "host",
            "uninstall-preview",
            "--root",
            str(projection),
        ],
        [
            str(installed / "agent-team"),
            "host",
            "uninstall",
            "--root",
            str(projection),
            "--digest",
            digest,
        ],
        [
            str(installed / "agent-team"),
            "host",
            "uninstall-preview",
            "--root",
            str(projection),
        ],
        [
            str(installed / "agent-team"),
            "host",
            "uninstall",
            "--root",
            str(projection),
            "--digest",
            digest,
        ],
        [
            str(installed / "agent-team"),
            "native",
            "writer-authority-validate",
            "--topology",
            str(installed / "examples/v08-contracts/valid/writer-topology.json"),
            "--plan",
            str(installed / "examples/v08-contracts/valid/plan-revision.json"),
            "--approval",
            str(installed / "examples/v08-contracts/valid/approval-grant.json"),
        ],
    ]
    last = ""
    for command in remainder:
        last = _run(command, source, environment)
    try:
        writer = _loads_strict(last)
    except ValueError:
        raise AnonymousWorkerError(
            "anonymous writer-authority output is invalid"
        ) from None
    if (
        not isinstance(writer, dict)
        or writer.get("status") != "VALID"
        or writer.get("automatic_execution") is not False
        or writer.get("identity_or_signature_verified") is not False
    ):
        raise AnonymousWorkerError("anonymous writer-authority boundary differs")
    return {
        "status": "PASS",
        "workflow_url": None,
        "source_url": SOURCE_URL,
        "tag": release,
        "tag_object": expected_tag_object,
        "commit": expected_commit,
        "verified_at": verified_at,
        "commands": list(ANONYMOUS_COMMANDS),
        "unauthenticated_git_transport": True,
        "caller_credentials_inherited": False,
        "same_uid_filesystem_isolated": False,
        "write_isolation": False,
        "external_writes_verified": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--release", required=True)
    parser.add_argument("--tag-object", required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--credential-parent-pid", type=int, required=True)
    parser.add_argument("--verified-at", required=True)
    arguments = parser.parse_args()
    result: dict[str, Any] | None = None
    workspace_created = False
    try:
        boundary = _linux_process_boundary(arguments.credential_parent_pid)
        if arguments.workspace.exists() or arguments.workspace.parent != Path("/tmp"):
            raise AnonymousWorkerError("anonymous workspace path is not fresh private /tmp")
        arguments.workspace.mkdir(mode=0o700)
        workspace_created = True
        result = _execute_workflow(
            arguments.release,
            arguments.tag_object,
            arguments.commit,
            arguments.workspace.resolve(),
            arguments.verified_at,
        )
        result.update(boundary)
    except (AnonymousWorkerError, OSError, ValueError) as error:
        print(f"anonymous release worker refused or failed: {error}", file=sys.stderr)
        return 2
    finally:
        try:
            if workspace_created:
                if arguments.workspace.is_symlink() or not arguments.workspace.is_dir():
                    raise OSError("anonymous workspace identity changed")
                arguments.workspace.chmod(0o700)
                for child in arguments.workspace.iterdir():
                    if child.is_dir() and not child.is_symlink():
                        shutil.rmtree(child)
                    else:
                        child.unlink()
                arguments.workspace.rmdir()
        except OSError:
            print("anonymous release worker could not clear its workspace", file=sys.stderr)
            return 2
    if result is None:
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
