"""Vendor-neutral v0.8 core contracts and semantic validation.

The JSON documents are the portable authority.  These helpers add deterministic
digests and cross-field checks that intentionally do not depend on an agent,
SCM, messaging, runner, or orchestration vendor SDK.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable

from core.json_support import loads_strict
from core.schema_validation import SchemaIssue, validate_schema

ROOT = Path(__file__).resolve().parents[1]
CONTRACT_VERSION = "1.0.0"
MAX_CONTRACT_BYTES = 1_000_000

CONTRACT_SCHEMAS: dict[str, str] = {
    "team_spec": "schemas/team-spec.schema.json",
    "role_contract": "schemas/role-contract.schema.json",
    "workflow_spec": "schemas/workflow-spec.schema.json",
    "work_item": "schemas/work-item-v2.schema.json",
    "plan_revision": "schemas/plan-revision.schema.json",
    "approval_grant": "schemas/approval-grant.schema.json",
    "run": "schemas/run.schema.json",
    "evidence_bundle": "schemas/evidence-bundle.schema.json",
    "adapter_descriptor": "schemas/adapter-descriptor.schema.json",
    "command_envelope": "schemas/command-envelope.schema.json",
    "event_envelope": "schemas/event-envelope.schema.json",
}

V08_STATES = frozenset(
    {
        "RECEIVED",
        "NORMALIZED",
        "TRIAGED",
        "PLANNED",
        "AWAITING_APPROVAL",
        "APPROVED",
        "EXECUTING",
        "VERIFYING",
        "REVIEWING",
        "CHANGES_REQUESTED",
        "DRAFT_PR_READY",
        "COMPLETED",
        "REJECTED",
        "DUPLICATE",
        "NEEDS_HUMAN",
        "CANCELLED",
        "EXPIRED",
        "FAILED",
        "BLOCKED",
    }
)


@dataclass(frozen=True)
class ContractIssue:
    path: str
    message: str


class ContractViolation(ValueError):
    """Raised when a portable contract is structurally or semantically invalid."""

    def __init__(self, contract: str, issues: list[ContractIssue]) -> None:
        self.contract = contract
        self.issues = tuple(issues)
        detail = "; ".join(f"{issue.path}: {issue.message}" for issue in issues)
        super().__init__(f"invalid {contract} contract: {detail}")


def canonical_json(value: Any) -> str:
    """Return the single canonical representation used by all v0.8 digests."""

    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def digest_value(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _without(document: dict[str, Any], *keys: str) -> dict[str, Any]:
    return {key: value for key, value in document.items() if key not in keys}


def plan_revision_digest(document: dict[str, Any]) -> str:
    """Bind every plan field other than the digest that carries the binding."""

    return digest_value(_without(document, "plan_digest"))


APPROVAL_SCOPE_FIELDS = (
    "actor_id",
    "identity_provider",
    "work_item_id",
    "plan_revision",
    "plan_digest",
    "repository_id",
    "base_commit",
    "allowed_paths",
    "allowed_actions",
    "runner_profile",
    "agent_capabilities",
    "budget_limit",
    "time_limit_seconds",
    "merge_allowed",
    "deploy_allowed",
    "issued_at",
    "expires_at",
    "nonce",
)


def approval_scope_payload(document: dict[str, Any]) -> dict[str, Any]:
    missing = [field for field in APPROVAL_SCOPE_FIELDS if field not in document]
    if missing:
        raise ValueError(f"approval scope is missing fields: {', '.join(missing)}")
    return {field: document[field] for field in APPROVAL_SCOPE_FIELDS}


def approval_scope_digest(document: dict[str, Any]) -> str:
    return digest_value(approval_scope_payload(document))


def evidence_bundle_digest(document: dict[str, Any]) -> str:
    return digest_value(_without(document, "bundle_digest"))


@lru_cache(maxsize=None)
def load_contract_schema(contract: str) -> dict[str, Any]:
    try:
        relative = CONTRACT_SCHEMAS[contract]
    except KeyError as exc:
        raise KeyError(f"unknown core contract: {contract}") from exc
    value = loads_strict((ROOT / relative).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"contract schema root must be an object: {relative}")
    return value


def _issue(path: str, message: str) -> ContractIssue:
    return ContractIssue(path, message)


def _parse_time(value: str, path: str, issues: list[ContractIssue]) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("timezone required")
        return parsed
    except (TypeError, ValueError):
        issues.append(_issue(path, "must be an RFC 3339 date-time with timezone"))
        return None


def _validate_role(document: dict[str, Any]) -> list[ContractIssue]:
    allowed = set(document.get("allowed_actions", []))
    forbidden = set(document.get("forbidden_actions", []))
    overlap = sorted(allowed & forbidden)
    return (
        [_issue("$.allowed_actions", f"actions are also forbidden: {', '.join(overlap)}")]
        if overlap
        else []
    )


def _validate_workflow(document: dict[str, Any]) -> list[ContractIssue]:
    issues: list[ContractIssue] = []
    states = set(document.get("states", []))
    if not states <= V08_STATES:
        issues.append(_issue("$.states", "contains a state outside the v0.8 vocabulary"))
    if document.get("initial_state") not in states:
        issues.append(_issue("$.initial_state", "must appear in states"))
    terminal = set(document.get("terminal_states", []))
    if not terminal <= states:
        issues.append(_issue("$.terminal_states", "terminal states must appear in states"))
    transition_keys: set[tuple[str, str]] = set()
    for index, transition in enumerate(document.get("transitions", [])):
        if not isinstance(transition, dict):
            continue
        source = str(transition.get("from_state", ""))
        target = str(transition.get("to_state", ""))
        event = str(transition.get("event", ""))
        if source not in states or target not in states:
            issues.append(_issue(f"$.transitions[{index}]", "references an undeclared state"))
        if source in terminal:
            issues.append(_issue(f"$.transitions[{index}].from_state", "terminal states cannot transition"))
        key = (source, event)
        if key in transition_keys:
            issues.append(_issue(f"$.transitions[{index}]", "duplicates a state/event transition"))
        transition_keys.add(key)
        if target == "APPROVED" and not transition.get("requires_approval", False):
            issues.append(_issue(f"$.transitions[{index}].requires_approval", "APPROVED requires an exact grant"))
    return issues


def _validate_plan(document: dict[str, Any]) -> list[ContractIssue]:
    issues: list[ContractIssue] = []
    expected = plan_revision_digest(document)
    if document.get("plan_digest") != expected:
        issues.append(_issue("$.plan_digest", "does not match the canonical plan content"))
    tasks = document.get("tasks", [])
    task_id_list = [str(task.get("task_id")) for task in tasks if isinstance(task, dict)]
    task_ids = set(task_id_list)
    if len(task_id_list) != len(task_ids):
        issues.append(_issue("$.tasks", "task_id values must be unique"))
    graph: dict[str, set[str]] = {}
    for index, task in enumerate(tasks):
        if not isinstance(task, dict):
            continue
        task_id = str(task.get("task_id", ""))
        dependencies = {str(value) for value in task.get("depends_on", [])}
        graph[task_id] = dependencies
        unknown = sorted(dependencies - task_ids)
        if unknown:
            issues.append(_issue(f"$.tasks[{index}].depends_on", f"unknown tasks: {', '.join(unknown)}"))
        if task_id in dependencies:
            issues.append(_issue(f"$.tasks[{index}].depends_on", "task cannot depend on itself"))
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(task_id: str) -> bool:
        if task_id in visiting:
            return True
        if task_id in visited:
            return False
        visiting.add(task_id)
        if any(visit(child) for child in graph.get(task_id, set()) if child in graph):
            return True
        visiting.remove(task_id)
        visited.add(task_id)
        return False

    if any(visit(task_id) for task_id in sorted(graph) if task_id not in visited):
        issues.append(_issue("$.tasks", "task dependency graph contains a cycle"))
    for index, path in enumerate(document.get("allowed_paths", [])):
        if path.startswith("/") or ".." in Path(path).parts:
            issues.append(_issue(f"$.allowed_paths[{index}]", "must be a repository-relative safe path"))
    return issues


def _validate_approval(document: dict[str, Any]) -> list[ContractIssue]:
    issues: list[ContractIssue] = []
    try:
        expected = approval_scope_digest(document)
    except ValueError as exc:
        issues.append(_issue("$", str(exc)))
    else:
        if document.get("scope_digest") != expected:
            issues.append(_issue("$.scope_digest", "does not match the exact approval scope"))
    issued = _parse_time(str(document.get("issued_at", "")), "$.issued_at", issues)
    expires = _parse_time(str(document.get("expires_at", "")), "$.expires_at", issues)
    if issued is not None and expires is not None and expires <= issued:
        issues.append(_issue("$.expires_at", "must be later than issued_at"))
    if document.get("merge_allowed") is not False or document.get("deploy_allowed") is not False:
        issues.append(_issue("$", "v0.8 grants cannot allow merge or deployment"))
    return issues


def _validate_run(document: dict[str, Any]) -> list[ContractIssue]:
    issues: list[ContractIssue] = []
    lease = document.get("lease")
    if isinstance(lease, dict):
        acquired = _parse_time(str(lease.get("acquired_at", "")), "$.lease.acquired_at", issues)
        expires = _parse_time(str(lease.get("expires_at", "")), "$.lease.expires_at", issues)
        if acquired is not None and expires is not None and expires <= acquired:
            issues.append(_issue("$.lease.expires_at", "must be later than acquired_at"))
    return issues


def _validate_evidence(document: dict[str, Any]) -> list[ContractIssue]:
    item_ids = [
        str(item.get("evidence_id"))
        for item in document.get("items", [])
        if isinstance(item, dict)
    ]
    issues: list[ContractIssue] = []
    if len(item_ids) != len(set(item_ids)):
        issues.append(_issue("$.items", "evidence_id values must be unique"))
    expected = evidence_bundle_digest(document)
    if document.get("bundle_digest") != expected:
        issues.append(_issue("$.bundle_digest", "does not match the canonical evidence index"))
    return issues


def _validate_adapter(document: dict[str, Any]) -> list[ContractIssue]:
    issues: list[ContractIssue] = []
    ports = set(document.get("ports", []))
    policy_ports: list[str] = []
    for index, policy in enumerate(document.get("idempotency", [])):
        if isinstance(policy, dict):
            port = str(policy.get("port"))
            policy_ports.append(port)
            if port not in ports:
                issues.append(_issue(f"$.idempotency[{index}].port", "must be one of the declared ports"))
    if len(policy_ports) != len(set(policy_ports)):
        issues.append(_issue("$.idempotency", "each port can declare only one idempotency policy"))
    missing = sorted(ports - set(policy_ports))
    if missing:
        issues.append(_issue("$.idempotency", f"missing policies for ports: {', '.join(missing)}"))
    return issues


SEMANTIC_VALIDATORS: dict[str, Callable[[dict[str, Any]], list[ContractIssue]]] = {
    "role_contract": _validate_role,
    "workflow_spec": _validate_workflow,
    "plan_revision": _validate_plan,
    "approval_grant": _validate_approval,
    "run": _validate_run,
    "evidence_bundle": _validate_evidence,
    "adapter_descriptor": _validate_adapter,
}


def validate_contract(contract: str, document: Any) -> list[ContractIssue]:
    schema_issues: list[SchemaIssue] = validate_schema(document, load_contract_schema(contract))
    issues = [ContractIssue(issue.path, issue.message) for issue in schema_issues]
    if isinstance(document, dict) and not schema_issues:
        validator = SEMANTIC_VALIDATORS.get(contract)
        if validator is not None:
            issues.extend(validator(document))
    return issues


def require_contract(contract: str, document: Any) -> dict[str, Any]:
    issues = validate_contract(contract, document)
    if issues:
        raise ContractViolation(contract, issues)
    if not isinstance(document, dict):  # defensive; every current core contract is an object
        raise ContractViolation(contract, [_issue("$", "contract root must be an object")])
    return document


def load_contract_file(contract: str, path: Path) -> dict[str, Any]:
    raw = path.read_bytes()
    if len(raw) > MAX_CONTRACT_BYTES:
        raise ContractViolation(contract, [_issue("$", "contract exceeds the 1 MiB limit")])
    try:
        value = loads_strict(raw)
    except ValueError as exc:
        raise ContractViolation(contract, [_issue("$", f"invalid strict JSON: {exc}")]) from exc
    return require_contract(contract, value)
