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

TRUSTED_ROOT = Path(__file__).resolve().parents[1]
if str(TRUSTED_ROOT) not in sys.path:
    sys.path.insert(0, str(TRUSTED_ROOT))

from core.context_team import (  # noqa: E402
    DESIGN_RELATIVE,
    LOCK_RELATIVE,
    ContextTeamError,
    compile_context_files,
    inspect_context_team,
)
from core.contracts import (  # noqa: E402
    ContractViolation,
    load_contract_file,
    validate_writer_authority,
)
from core.host_lifecycle import (  # noqa: E402
    HostLifecycleError,
    INSTALL_LOCK_RELATIVE,
    METADATA_STAGE_RELATIVE,
    OPERATION_GUARD_RELATIVE,
    UNINSTALL_TOMBSTONE_RELATIVE,
    load_install_plan,
    preview_uninstall,
    verify_installation,
    _source_records,
    _validate_source,
)
from core.installation import InstallationError, verify_factory_installation  # noqa: E402
from core.instance import _canonical_json  # noqa: E402

COMMIT = re.compile(r"^[a-f0-9]{40}$")
DIGEST = re.compile(r"^sha256:[a-f0-9]{64}$")
SOURCE_URL = "https://github.com/90le/agent-team-engineering.git"
ANONYMOUS_COMMANDS = (
    "systemd transient cgroup with memory/CPU/PID/file/tmpfs limits; setpriv random unregistered UID; no groups/capabilities; no-new-privileges; verify credential-parent /proc isolation",
    "trusted git clone --no-local --no-checkout https://github.com/90le/agent-team-engineering.git <private-tmp>",
    "git verify annotated tag object and peeled commit",
    "git checkout --detach <peeled-tag-commit>; verify clean exact HEAD",
    "bubblewrap candidate phase: new user/mount/PID/network namespaces; read-only /usr runtime; private /tmp workspace only; no outbound network",
    "factory install; factory verify; doctor",
    "create and validate portable team",
    "host plan; preview; confirm; apply; verify; uninstall-preview; uninstall; replay",
    "native writer-authority-validate",
    "trusted independent read-back of the tagged installation tree, portable team lock, host lifecycle effects, and WriterTopology authority chain",
)
COMMAND_TIMEOUT_SECONDS = 300
MAX_COMMAND_OUTPUT_BYTES = 16 * 1024 * 1024
MAX_TRUSTED_TREE_BYTES = 100 * 1024 * 1024
EXPECTED_MEMORY_MAX_BYTES = 1024 * 1024 * 1024
EXPECTED_MEMORY_SWAP_MAX_BYTES = 0
EXPECTED_TASKS_MAX = 128
EXPECTED_CPU_QUOTA_US = 200_000
EXPECTED_CPU_PERIOD_US = 100_000
EXPECTED_FILE_SIZE_LIMIT_BYTES = 16 * 1024 * 1024
EXPECTED_TMPFS_BYTES = 512 * 1024 * 1024
BUBBLEWRAP = Path("/usr/bin/bwrap")


class AnonymousWorkerError(RuntimeError):
    pass


def _snapshot_regular_tree(root: Path) -> dict[str, dict[str, Any]]:
    """Capture the clean tagged source before any candidate code executes."""

    records: dict[str, dict[str, Any]] = {}
    total = 0
    for path in sorted(root.rglob("*")):
        relative_path = path.relative_to(root)
        if relative_path.parts and relative_path.parts[0] == ".git":
            continue
        if path.is_symlink():
            raise AnonymousWorkerError(
                f"tagged source contains a symbolic link: {relative_path.as_posix()}"
            )
        metadata = path.stat()
        if path.is_dir():
            continue
        if not path.is_file():
            raise AnonymousWorkerError(
                f"tagged source contains a special file: {relative_path.as_posix()}"
            )
        content = path.read_bytes()
        total += len(content)
        if total > MAX_TRUSTED_TREE_BYTES:
            raise AnonymousWorkerError("tagged source tree exceeds the trusted size limit")
        relative = relative_path.as_posix()
        records[relative] = {
            "path": relative,
            "sha256": "sha256:" + hashlib.sha256(content).hexdigest(),
            "mode": 0o755 if metadata.st_mode & 0o100 else 0o644,
            "size": len(content),
        }
    if not records:
        raise AnonymousWorkerError("tagged source tree is empty")
    return records


def _verify_factory_effects(
    installed: Path,
    source_records: dict[str, dict[str, Any]],
    release: str,
    expected_commit: str,
) -> dict[str, Any]:
    try:
        manifest = verify_factory_installation(installed)
    except (InstallationError, OSError, ValueError) as exc:
        raise AnonymousWorkerError(f"installed Factory failed trusted verification: {exc}") from None
    installed_records = {
        str(record["path"]): {
            "path": str(record["path"]),
            "sha256": str(record["sha256"]),
            "mode": int(record["mode"]),
            "size": int(record["size"]),
        }
        for record in manifest["files"]
    }
    if (
        manifest.get("source_revision") != expected_commit
        or manifest.get("source_tag") != release
        or manifest.get("release_verified") is not True
        or installed_records != source_records
    ):
        raise AnonymousWorkerError(
            "installed Factory differs from the independently captured tag tree"
        )
    return manifest


def _verify_source_effects(
    source: Path,
    expected_records: dict[str, dict[str, Any]],
) -> None:
    if _snapshot_regular_tree(source) != expected_records:
        raise AnonymousWorkerError("tagged source changed after candidate execution")


def _verify_team_effects(
    team: Path,
    expected_design: dict[str, Any],
    expected_factory: dict[str, Any],
) -> dict[str, Any]:
    try:
        summary = inspect_context_team(team)
        actual_design = _loads_strict(
            (team / DESIGN_RELATIVE).read_text(encoding="utf-8")
        )
        actual_lock = _loads_strict(
            (team / LOCK_RELATIVE).read_text(encoding="utf-8")
        )
        expected_files = compile_context_files(
            expected_design,
            include_platforms=expected_design["mode"] == "lite",
        )
    except (ContextTeamError, OSError, ValueError) as exc:
        raise AnonymousWorkerError(f"portable team failed trusted verification: {exc}") from None
    if summary.get("status") != "VALID" or summary.get("errors") != 0:
        raise AnonymousWorkerError("portable team trusted verification is not VALID")
    if actual_design != expected_design:
        raise AnonymousWorkerError("portable team differs from the exact tagged design")
    if not isinstance(actual_lock, dict) or actual_lock.get("factory") != expected_factory:
        raise AnonymousWorkerError("portable team lock differs from the exact tagged Factory")
    expected_content = {
        DESIGN_RELATIVE: _canonical_json(expected_design).encode("utf-8"),
        **{
            relative: content.encode("utf-8")
            for relative, content in expected_files.items()
        },
    }
    expected_paths = set(expected_content) | {LOCK_RELATIVE}
    actual_paths: set[str] = set()
    for path in sorted(team.rglob("*")):
        relative = path.relative_to(team).as_posix()
        if path.is_symlink():
            raise AnonymousWorkerError(f"portable team contains a symbolic link: {relative}")
        if path.is_dir():
            continue
        if not path.is_file():
            raise AnonymousWorkerError(f"portable team contains a special file: {relative}")
        actual_paths.add(relative)
    if actual_paths != expected_paths:
        raise AnonymousWorkerError("portable team file set differs from the exact tagged design")
    for relative, content in expected_content.items():
        if (team / relative).read_bytes() != content:
            raise AnonymousWorkerError(
                f"portable team file differs from the exact tagged design: {relative}"
            )
    return summary


def _verify_candidate_baseline(
    *,
    source: Path,
    source_records: dict[str, dict[str, Any]],
    installed: Path,
    team: Path,
    expected_design: dict[str, Any],
    release: str,
    expected_commit: str,
) -> None:
    """Recheck every earlier candidate effect after each later candidate command."""

    _verify_source_effects(source, source_records)
    manifest: dict[str, Any] | None = None
    if installed.exists() or installed.is_symlink():
        manifest = _verify_factory_effects(
            installed,
            source_records,
            release,
            expected_commit,
        )
    if team.exists() or team.is_symlink():
        if manifest is None:
            raise AnonymousWorkerError("portable team exists without the exact tagged Factory")
        _verify_team_effects(
            team,
            expected_design,
            {
                "id": manifest["factory_id"],
                "version": manifest["factory_version"],
                "source_revision": expected_commit,
                "source_dirty": False,
            },
        )


def _verify_active_host_effects(
    projection: Path,
    plan_document: dict[str, Any],
) -> dict[str, Any]:
    digest = str(plan_document["proposal_digest"])
    try:
        report = verify_installation(projection)
        install_lock = _loads_strict(
            (projection / INSTALL_LOCK_RELATIVE).read_text(encoding="utf-8")
        )
    except (HostLifecycleError, OSError, ValueError) as exc:
        raise AnonymousWorkerError(f"host projection failed trusted verification: {exc}") from None
    if (
        report.get("status") != "VALID"
        or report.get("proposal_digest") != digest
        or not isinstance(install_lock, dict)
        or install_lock.get("proposal_digest") != digest
        or install_lock.get("proposal") != plan_document["proposal"]
    ):
        raise AnonymousWorkerError("host projection trusted verification differs")
    return report


def _verify_uninstalled_host_effects(
    projection: Path,
    plan_document: dict[str, Any],
    digest: str,
) -> None:
    try:
        preview = preview_uninstall(projection)
    except (HostLifecycleError, OSError, ValueError) as exc:
        raise AnonymousWorkerError(f"host uninstall failed trusted verification: {exc}") from None
    if preview.get("status") != "ALREADY_UNINSTALLED" or preview.get(
        "proposal_digest"
    ) != digest:
        raise AnonymousWorkerError("host uninstall tombstone differs from the exact plan")
    lifecycle = plan_document["proposal"]["lifecycle"]
    absent = {
        INSTALL_LOCK_RELATIVE,
        METADATA_STAGE_RELATIVE,
        lifecycle["initial_apply_intent"],
        lifecycle["metadata_recovery_intent"],
    }
    for record in plan_document["proposal"]["files"]:
        absent.update((record["path"], record["stage_path"], record["intent_path"]))
    for relative in absent:
        path = projection / relative
        if path.exists() or path.is_symlink():
            raise AnonymousWorkerError("host uninstall retained a managed or transient file")
    for relative in (OPERATION_GUARD_RELATIVE, UNINSTALL_TOMBSTONE_RELATIVE):
        path = projection / relative
        if path.is_symlink() or not path.is_file():
            raise AnonymousWorkerError("host uninstall retained unsafe lifecycle evidence")


def _verify_writer_authority_effects(root: Path) -> dict[str, Any]:
    fixture = root / "examples/v08-contracts/valid"
    try:
        topology = load_contract_file("writer_topology", fixture / "writer-topology.json")
        plan = load_contract_file("plan_revision", fixture / "plan-revision.json")
        approval = load_contract_file("approval_grant", fixture / "approval-grant.json")
        issues = validate_writer_authority(topology, plan, approval)
    except (ContractViolation, OSError, ValueError) as exc:
        raise AnonymousWorkerError(f"writer authority failed trusted verification: {exc}") from None
    if issues:
        raise AnonymousWorkerError("writer authority failed trusted cross-contract verification")
    return {
        "topology_digest": topology["topology_digest"],
        "plan_digest": plan["plan_digest"],
        "approval_scope_digest": approval["scope_digest"],
    }


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


def _candidate_sandbox_command(
    arguments: list[str],
    cwd: Path,
    workspace: Path,
    environment: dict[str, str],
) -> list[str]:
    """Expose candidate code only to a read-only runtime and private /tmp."""

    if not BUBBLEWRAP.is_file() or not os.access(BUBBLEWRAP, os.X_OK):
        raise AnonymousWorkerError("bubblewrap is required for offline candidate execution")
    resolved_workspace = workspace.resolve()
    resolved_cwd = cwd.resolve()
    if resolved_workspace.parent != Path("/tmp") or (
        resolved_cwd != resolved_workspace
        and resolved_workspace not in resolved_cwd.parents
    ):
        raise AnonymousWorkerError("candidate sandbox path escapes the private workspace")
    command = [
        str(BUBBLEWRAP),
        "--unshare-all",
        "--unshare-user",
        "--disable-userns",
        "--die-with-parent",
        "--new-session",
        "--cap-drop",
        "ALL",
        "--ro-bind",
        "/usr",
        "/usr",
        "--symlink",
        "usr/bin",
        "/bin",
        "--symlink",
        "usr/lib",
        "/lib",
        "--symlink",
        "usr/lib64",
        "/lib64",
        "--proc",
        "/proc",
        "--dev",
        "/dev",
        "--bind",
        "/tmp",
        "/tmp",
        "--chdir",
        str(resolved_cwd),
        "--clearenv",
    ]
    for key in sorted(environment):
        command.extend(("--setenv", key, environment[key]))
    command.extend(("--", *arguments))
    return command


def _run_candidate(
    arguments: list[str],
    cwd: Path,
    workspace: Path,
    environment: dict[str, str],
) -> str:
    return _run(
        _candidate_sandbox_command(arguments, cwd, workspace, environment),
        cwd,
        environment,
    )


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
        "isolation_mechanism": "linux-systemd-cgroup-setpriv-bubblewrap-v1",
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
    source_records = _snapshot_regular_tree(source)
    try:
        expected_design = _loads_strict(
            (source / "examples/context-first/team-design.json").read_text(
                encoding="utf-8"
            )
        )
        expected_writer = _verify_writer_authority_effects(source)
    except (OSError, ValueError) as exc:
        raise AnonymousWorkerError("tagged release inputs are invalid") from exc
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
        _run_candidate(command, source, workspace, environment)
        if command[:4] == [
            sys.executable,
            "tools/agent_team.py",
            "factory",
            "install",
        ]:
            _verify_factory_effects(
                installed,
                source_records,
                release,
                expected_commit,
            )
        elif "create" in command and "--design" in command:
            manifest = _verify_factory_effects(
                installed,
                source_records,
                release,
                expected_commit,
            )
            _verify_team_effects(
                team,
                expected_design,
                {
                    "id": manifest["factory_id"],
                    "version": manifest["factory_version"],
                    "source_revision": expected_commit,
                    "source_dirty": False,
                },
            )
        _verify_candidate_baseline(
            source=source,
            source_records=source_records,
            installed=installed,
            team=team,
            expected_design=expected_design,
            release=release,
            expected_commit=expected_commit,
        )
    try:
        plan_document = _loads_strict(plan.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise AnonymousWorkerError("anonymous host plan is invalid") from None
    try:
        trusted_plan = load_install_plan(plan)
    except (HostLifecycleError, OSError, ValueError) as exc:
        raise AnonymousWorkerError(
            f"anonymous host plan failed trusted validation: {exc}"
        ) from None
    if trusted_plan != plan_document or trusted_plan.get("state") != "DRAFT":
        raise AnonymousWorkerError("anonymous host plan differs from trusted validation")
    proposal = trusted_plan["proposal"]
    try:
        trusted_team = _validate_source(trusted_plan)
    except HostLifecycleError as exc:
        raise AnonymousWorkerError(
            f"anonymous host plan source failed trusted validation: {exc}"
        ) from None
    if (
        trusted_team != team.resolve()
        or proposal["team"]["team_id"] != expected_design["team_id"]
        or proposal["host"]["id"] != "generic-ai"
        or Path(proposal["destination"]) != projection.resolve()
    ):
        raise AnonymousWorkerError("anonymous host plan differs from the exact requested inputs")
    expected_projection = [
        {
            key: record[key]
            for key in ("source", "path", "sha256", "management", "stage_path")
        }
        for record in _source_records(team.resolve(), "generic-ai")
    ]
    actual_projection = [
        {
            key: record[key]
            for key in ("source", "path", "sha256", "management", "stage_path")
        }
        for record in proposal["files"]
    ]
    if actual_projection != expected_projection:
        raise AnonymousWorkerError(
            "anonymous host plan file set differs from the exact team projection"
        )
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
    writer_output = ""
    host_active = False
    host_uninstalled = False
    for command in remainder:
        output = _run_candidate(command, source, workspace, environment)
        _verify_candidate_baseline(
            source=source,
            source_records=source_records,
            installed=installed,
            team=team,
            expected_design=expected_design,
            release=release,
            expected_commit=expected_commit,
        )
        if command[1:3] == ["host", "apply"]:
            host_active = True
            _verify_active_host_effects(projection, plan_document)
        elif command[1:3] == ["host", "uninstall"]:
            host_active = False
            host_uninstalled = True
            _verify_uninstalled_host_effects(projection, plan_document, digest)
        elif "writer-authority-validate" in command:
            writer_output = output
        elif host_active:
            _verify_active_host_effects(projection, plan_document)
        elif host_uninstalled:
            _verify_uninstalled_host_effects(projection, plan_document, digest)
    try:
        writer = _loads_strict(writer_output)
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
    trusted_writer = _verify_writer_authority_effects(installed)
    if trusted_writer != expected_writer or any(
        writer.get(key) != value for key, value in expected_writer.items()
    ):
        raise AnonymousWorkerError(
            "anonymous writer-authority output differs from trusted recomputation"
        )
    _verify_candidate_baseline(
        source=source,
        source_records=source_records,
        installed=installed,
        team=team,
        expected_design=expected_design,
        release=release,
        expected_commit=expected_commit,
    )
    _verify_uninstalled_host_effects(projection, plan_document, digest)
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
        "same_uid_filesystem_isolated": True,
        "write_isolation": True,
        "external_writes_verified": True,
        "candidate_network_isolated": True,
        "candidate_runtime_read_only": True,
        "independent_effects_verified": True,
        "independent_effects": [
            "factory-installation-manifest-and-tag-tree",
            "portable-team-design-lock-and-managed-files",
            "host-active-lock-files-and-uninstall-tombstone",
            "writer-topology-plan-approval-digest-chain",
        ],
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
