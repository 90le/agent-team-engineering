"""Fail-closed validation for disposable runner requests."""

from __future__ import annotations

import hashlib
import ipaddress
import json
import re
from pathlib import Path
from typing import Any, Iterable

from core.json_support import loads_strict
from core.schema_validation import validate_schema

ROOT = Path(__file__).resolve().parents[1]
EXECUTION_SCHEMA = ROOT / "schemas" / "execution-request.schema.json"
HOST_AND_PORT = re.compile(r"^[A-Za-z0-9.-]+(?::([0-9]{1,5}))?$")


class IsolationViolation(RuntimeError):
    """Raised before an unsafe runner request reaches an executor."""


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def execution_plan_digest(request: dict[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(_canonical_json(request).encode("utf-8")).hexdigest()


def _validate_network_target(value: str) -> None:
    match = HOST_AND_PORT.fullmatch(value)
    if not match or "*" in value:
        raise IsolationViolation(f"invalid network allowlist target: {value}")
    host = value.rsplit(":", 1)[0] if match.group(1) else value
    if match.group(1) and not 1 <= int(match.group(1)) <= 65535:
        raise IsolationViolation(f"invalid network port: {value}")
    if host.casefold() == "localhost" or host.casefold().endswith(".local"):
        raise IsolationViolation("runner allowlist cannot target localhost or .local names")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return
    if not address.is_global:
        raise IsolationViolation("runner allowlist cannot target non-global IP addresses")


def validate_execution_request(
    request: dict[str, Any],
    *,
    allowed_command_ids: Iterable[str],
    allowed_secret_refs: Iterable[str] = (),
    maximum_timeout_seconds: int = 3600,
) -> None:
    schema = loads_strict(EXECUTION_SCHEMA.read_text(encoding="utf-8"))
    issues = validate_schema(request, schema)
    if issues:
        details = "; ".join(f"{issue.path}: {issue.message}" for issue in issues)
        raise IsolationViolation(f"execution request violates schema: {details}")
    if request["command_id"] not in frozenset(allowed_command_ids):
        raise IsolationViolation("command_id is not present in the runner allowlist")
    if request["timeout_seconds"] > maximum_timeout_seconds:
        raise IsolationViolation("execution timeout exceeds the runner profile")
    if not str(request["source_ref"]).startswith("project-source:"):
        raise IsolationViolation("source_ref must be an abstract project-source reference")
    if ".." in str(request["source_ref"]).split("/"):
        raise IsolationViolation("source_ref cannot contain path traversal")
    if len(request["arguments"]) > 100 or any(
        len(argument) > 1000 or "\x00" in argument for argument in request["arguments"]
    ):
        raise IsolationViolation("runner arguments exceed bounded argv limits")

    requested_secrets = set(request["secret_refs"])
    permitted_secrets = set(allowed_secret_refs)
    if not requested_secrets <= permitted_secrets:
        raise IsolationViolation("execution request asks for an unapproved secret reference")

    network_targets = request["network_allowlist"]
    if request["network_policy"] == "none" and network_targets:
        raise IsolationViolation("network_policy none requires an empty allowlist")
    if request["network_policy"] == "allowlist" and not network_targets:
        raise IsolationViolation("network_policy allowlist requires at least one target")
    for target in network_targets:
        _validate_network_target(target)

    for required, expected in (
        ("source_read_only", True),
        ("workspace_ephemeral", True),
        ("production_mounts", False),
        ("docker_socket", False),
        ("privileged", False),
    ):
        if request[required] is not expected:
            raise IsolationViolation(f"unsafe runner boundary: {required} must be {expected}")
