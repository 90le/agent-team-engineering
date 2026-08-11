"""Versioned AI-host catalog and deliberately narrow, read-only probes.

Host descriptors are data, never executable plugins.  A probe may run only the
descriptor's single, explicit local version command.  It receives no user
configuration, credentials, stdin, shell, or network endpoint from this module.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from core.json_support import loads_strict
from core.schema_validation import SchemaIssue, validate_schema

ROOT = Path(__file__).resolve().parents[1]
HOST_SCHEMA = ROOT / "schemas" / "host-capability.schema.json"
HOST_ID = re.compile(r"^[a-z][a-z0-9-]{0,62}$")
EXECUTABLE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")
ALLOWED_VERSION_ARGUMENTS = {("--version",), ("version",)}
MAX_OUTPUT_CHARACTERS = 300
_CONTROL_CHARACTERS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


class HostCatalogError(RuntimeError):
    """Raised when catalog data is missing, unsafe, or invalid."""


def _load_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = loads_strict(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise HostCatalogError(f"cannot load {label}: {error}") from error
    if not isinstance(value, dict):
        raise HostCatalogError(f"{label} root must be an object")
    return value


def _schema(repository_root: Path) -> dict[str, Any]:
    return _load_object(repository_root / "schemas" / "host-capability.schema.json", "host schema")


def _semantic_issues(
    descriptor: Mapping[str, Any], *, expected_host_id: str | None
) -> list[SchemaIssue]:
    issues: list[SchemaIssue] = []
    host_id = descriptor.get("host_id")
    if expected_host_id is not None and host_id != expected_host_id:
        issues.append(SchemaIssue("$.host_id", "must match its hosts/<host-id> directory"))

    probe = descriptor.get("probe")
    if not isinstance(probe, dict):
        return issues
    mode = probe.get("mode")
    command = probe.get("command")
    if not isinstance(command, list) or any(not isinstance(value, str) for value in command):
        return issues
    if mode == "version-command":
        if len(command) != 2:
            issues.append(SchemaIssue("$.probe.command", "version probe must have two argv items"))
        elif not EXECUTABLE_NAME.fullmatch(command[0]):
            issues.append(
                SchemaIssue("$.probe.command[0]", "probe executable must be a bare command name")
            )
        elif tuple(command[1:]) not in ALLOWED_VERSION_ARGUMENTS:
            issues.append(
                SchemaIssue("$.probe.command", "probe may run only --version or version")
            )
    elif mode == "unavailable" and command:
        issues.append(SchemaIssue("$.probe.command", "unavailable probe must have empty argv"))
    for index, surface in enumerate(descriptor.get("native_surfaces", [])):
        if isinstance(surface, str) and (surface.startswith("/") or ".." in Path(surface).parts):
            issues.append(
                SchemaIssue(
                    f"$.native_surfaces[{index}]",
                    "native surface must be a relative path or symbolic surface name",
                )
            )
    return issues


def validate_host_descriptor(
    descriptor: Mapping[str, Any],
    *,
    expected_host_id: str | None = None,
    repository_root: Path = ROOT,
) -> tuple[SchemaIssue, ...]:
    """Return all portable-schema and fail-closed semantic issues."""

    if not isinstance(descriptor, dict):
        return (SchemaIssue("$", "host descriptor root must be an object"),)
    issues = validate_schema(descriptor, _schema(repository_root))
    issues.extend(_semantic_issues(descriptor, expected_host_id=expected_host_id))
    return tuple(issues)


def list_host_ids(*, repository_root: Path = ROOT) -> tuple[str, ...]:
    """List only safe, direct catalog entries without parsing or probing them."""

    host_root = repository_root / "hosts"
    if not host_root.is_dir() or host_root.is_symlink():
        raise HostCatalogError("hosts directory is missing or unsafe")
    host_ids: list[str] = []
    for candidate in sorted(host_root.iterdir(), key=lambda path: path.name):
        descriptor = candidate / "host.json"
        if (
            candidate.is_dir()
            and not candidate.is_symlink()
            and HOST_ID.fullmatch(candidate.name)
            and descriptor.is_file()
            and not descriptor.is_symlink()
        ):
            host_ids.append(candidate.name)
    return tuple(host_ids)


def load_host_descriptor(
    host_id: str, *, repository_root: Path = ROOT
) -> dict[str, Any]:
    """Load and validate one descriptor; path-like host identifiers are refused."""

    if not HOST_ID.fullmatch(host_id):
        raise HostCatalogError("invalid host id")
    host_root = (repository_root / "hosts").resolve()
    descriptor_path = repository_root / "hosts" / host_id / "host.json"
    try:
        resolved = descriptor_path.resolve(strict=True)
    except OSError as error:
        raise HostCatalogError(f"unknown host: {host_id}") from error
    if host_root not in resolved.parents or descriptor_path.is_symlink():
        raise HostCatalogError(f"unsafe host descriptor path: {host_id}")
    descriptor = _load_object(resolved, f"host descriptor {host_id}")
    issues = validate_host_descriptor(
        descriptor,
        expected_host_id=host_id,
        repository_root=repository_root,
    )
    if issues:
        detail = "; ".join(f"{issue.path}: {issue.message}" for issue in issues)
        raise HostCatalogError(f"invalid host descriptor {host_id}: {detail}")
    return descriptor


def load_host_catalog(*, repository_root: Path = ROOT) -> dict[str, dict[str, Any]]:
    """Load all validated descriptors without running any host process."""

    return {
        host_id: load_host_descriptor(host_id, repository_root=repository_root)
        for host_id in list_host_ids(repository_root=repository_root)
    }


def _probe_environment(environment: Mapping[str, str]) -> dict[str, str]:
    """Build a credential-free environment that hides normal user config roots."""

    isolated = {
        "HOME": "/nonexistent",
        "XDG_CACHE_HOME": "/nonexistent",
        "XDG_CONFIG_HOME": "/nonexistent",
        "XDG_DATA_HOME": "/nonexistent",
        "XDG_STATE_HOME": "/nonexistent",
        "CODEX_HOME": "/nonexistent",
        "CLAUDE_CONFIG_DIR": "/nonexistent",
        "HERMES_HOME": "/nonexistent",
        "OPENCLAW_HOME": "/nonexistent",
        "OPENCLAW_STATE_DIR": "/nonexistent",
        "OPENCLAW_CONFIG_PATH": "/nonexistent/openclaw.json",
        "LANG": "C",
        "LC_ALL": "C",
    }
    for key in ("PATH", "PATHEXT", "SYSTEMROOT"):
        if key in environment:
            isolated[key] = environment[key]
    return isolated


def _safe_output(stdout: object, stderr: object) -> str | None:
    for value in (stdout, stderr):
        if not isinstance(value, str):
            continue
        for line in value.splitlines():
            cleaned = _CONTROL_CHARACTERS.sub("", line).strip()
            if cleaned:
                return cleaned[:MAX_OUTPUT_CHARACTERS]
    return None


def probe_host(
    host_id: str,
    *,
    repository_root: Path = ROOT,
    which: Callable[[str], str | None] = shutil.which,
    run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    environment: Mapping[str, str] = os.environ,
) -> dict[str, Any]:
    """Run at most one local, credential-free version command.

    The function never invokes a shell, accepts task arguments, reads a host
    configuration file, performs authentication, or contacts an endpoint.
    Timeouts and process errors are converted into stable result states.
    """

    descriptor = load_host_descriptor(host_id, repository_root=repository_root)
    probe = descriptor["probe"]
    declared_command = list(probe["command"])
    result: dict[str, Any] = {
        "host_id": host_id,
        "support_tier": descriptor["support_tier"],
        "probe_mode": probe["mode"],
        "status": "not-applicable",
        "installed": False,
        "command": declared_command,
        "resolved_executable": None,
        "version_output": None,
        "returncode": None,
        "error": None,
        "safety": dict(descriptor["safety"]),
    }
    if probe["mode"] == "unavailable":
        return result

    executable = which(declared_command[0])
    if executable is None:
        result["status"] = "not-found"
        result["error"] = "executable-not-found"
        return result

    command = [executable, *declared_command[1:]]
    result["installed"] = True
    result["resolved_executable"] = executable
    try:
        completed = run(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=int(probe["timeout_seconds"]),
            check=False,
            shell=False,
            cwd=os.path.abspath(os.sep),
            env=_probe_environment(environment),
        )
    except subprocess.TimeoutExpired:
        result["status"] = "timeout"
        result["error"] = "version-command-timeout"
        return result
    except OSError:
        result["status"] = "error"
        result["error"] = "version-command-os-error"
        return result

    result["returncode"] = completed.returncode
    result["version_output"] = _safe_output(completed.stdout, completed.stderr)
    if completed.returncode != 0:
        result["status"] = "command-failed"
        result["error"] = "version-command-nonzero"
    elif result["version_output"] is None:
        result["status"] = "command-failed"
        result["error"] = "version-command-empty-output"
    else:
        result["status"] = "available"
    return result
