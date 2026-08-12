"""Vendor-neutral portable core contracts and semantic validation.

The JSON documents are the portable authority.  These helpers add deterministic
digests and cross-field checks that intentionally do not depend on an agent,
SCM, messaging, runner, or orchestration vendor SDK.
"""

from __future__ import annotations

import hashlib
import json
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable

from core.json_support import loads_strict
from core.schema_validation import SchemaIssue, validate_schema

ROOT = Path(__file__).resolve().parents[1]
CONTRACT_VERSION = "1.1.0"
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
    "writer_topology": "schemas/writer-topology.schema.json",
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
    """Return the single canonical representation used by all core digests."""

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
    fields = APPROVAL_SCOPE_FIELDS + (
        ("writer_topology",) if "writer_topology" in document else ()
    )
    missing = [field for field in fields if field not in document]
    if missing:
        raise ValueError(f"approval scope is missing fields: {', '.join(missing)}")
    return {field: document[field] for field in fields}


def approval_scope_digest(document: dict[str, Any]) -> str:
    return digest_value(approval_scope_payload(document))


def evidence_bundle_digest(document: dict[str, Any]) -> str:
    return digest_value(_without(document, "bundle_digest"))


def writer_topology_digest(document: dict[str, Any]) -> str:
    """Bind the complete portable writer topology except its carrying digest."""

    return digest_value(_without(document, "topology_digest"))


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
    version = document.get("schema_version")
    expected_schema = f"urn:agent-team:schema:plan-revision:{version}"
    if document.get("$schema") != expected_schema:
        issues.append(_issue("$.$schema", "must match schema_version"))
    if version == "1.1.0" and "writer_topology" not in document:
        issues.append(
            _issue(
                "$.writer_topology",
                "v1.1 plans must explicitly bind a topology or declare null",
            )
        )
    if version == "1.0.0" and "writer_topology" in document:
        issues.append(
            _issue(
                "$.writer_topology",
                "v1.0 plans cannot claim the v1.1 topology binding",
            )
        )
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
    version = document.get("schema_version")
    expected_schema = f"urn:agent-team:schema:approval-grant:{version}"
    if document.get("$schema") != expected_schema:
        issues.append(_issue("$.$schema", "must match schema_version"))
    if version == "1.1.0" and "writer_topology" not in document:
        issues.append(
            _issue(
                "$.writer_topology",
                "v1.1 approvals must explicitly bind a topology or declare null",
            )
        )
    if version == "1.0.0" and "writer_topology" in document:
        issues.append(
            _issue(
                "$.writer_topology",
                "v1.0 approvals cannot claim the v1.1 topology binding",
            )
        )
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


def _validate_writer_topology(document: dict[str, Any]) -> list[ContractIssue]:
    issues: list[ContractIssue] = []
    if document.get("topology_digest") != writer_topology_digest(document):
        issues.append(_issue("$.topology_digest", "does not match the canonical topology content"))

    writers = [item for item in document.get("writers", []) if isinstance(item, dict)]
    writer_ids = [str(item.get("actor_id", "")) for item in writers]
    if len(writer_ids) != len(set(writer_ids)):
        issues.append(_issue("$.writers", "writer actor_id values must be unique"))

    owned_roots: list[tuple[str, str, int, int]] = []
    required_tokens = ("{work_item_id}", "{writer_id}")
    dangerous_actions = {
        "approval.issue",
        "default-branch.merge",
        "production.deploy",
        "release.publish",
    }
    reserved_writer_roots = {
        ".agent-team",
        ".agents",
        ".claude",
        ".codex",
        ".git",
        ".github",
        ".hermes",
        ".openclaw",
    }
    reserved_root_files = {
        "agents.md",
        "ai-bootstrap.md",
        "ai-start.md",
        "architecture.md",
        "claude.md",
        "constitution.md",
        "context-map.md",
        "project-context.md",
        "security.md",
        "team.md",
    }
    for index, writer in enumerate(writers):
        actor = str(writer.get("actor_id", ""))
        if actor.endswith(".lock"):
            issues.append(
                _issue(
                    f"$.writers[{index}].actor_id",
                    "must remain a Git-safe branch component and cannot end in .lock",
                )
            )
        if not str(writer.get("role_ref", "")).startswith(actor + "@"):
            issues.append(_issue(f"$.writers[{index}].role_ref", "must identify the writer actor"))
        for field in ("worktree_template", "branch_template"):
            value = str(writer.get(field, ""))
            missing = [token for token in required_tokens if token not in value]
            if missing:
                issues.append(
                    _issue(
                        f"$.writers[{index}].{field}",
                        f"must isolate both work item and writer: missing {', '.join(missing)}",
                    )
                )
        allowed = set(writer.get("allowed_actions", []))
        forbidden = set(writer.get("forbidden_actions", []))
        if allowed & forbidden:
            issues.append(_issue(f"$.writers[{index}]", "allowed and forbidden actions overlap"))
        if not dangerous_actions <= forbidden:
            issues.append(
                _issue(
                    f"$.writers[{index}].forbidden_actions",
                    "must forbid approval, default-branch merge, release, and deployment",
                )
            )
        for root_index, root_value in enumerate(writer.get("ownership_roots", [])):
            root = str(root_value)
            path = Path(root)
            unicode_normalized = unicodedata.normalize("NFC", root)
            components = path.parts
            if (
                not root
                or root == "."
                or path.is_absolute()
                or ".." in path.parts
                or path.as_posix() != root
                or unicode_normalized != root
                or "\\" in root
                or ":" in root
                or any(
                    unicodedata.category(character)[0] == "C"
                    or unicodedata.category(character) in {"Zl", "Zp"}
                    for character in root
                )
                or any(component != component.rstrip(" .") for component in components)
            ):
                issues.append(
                    _issue(
                        f"$.writers[{index}].ownership_roots[{root_index}]",
                        "must be a normalized repository-relative subtree",
                    )
                )
            first_component = components[0].rstrip(" .").casefold() if components else ""
            if first_component in reserved_writer_roots or (
                len(components) == 1 and first_component in reserved_root_files
            ):
                issues.append(
                    _issue(
                        f"$.writers[{index}].ownership_roots[{root_index}]",
                        "must not assign SCM control or Factory governance paths to a source writer",
                    )
                )
            owned_roots.append(
                (actor, unicode_normalized.casefold().rstrip("/"), index, root_index)
            )
    for left_index, left in enumerate(owned_roots):
        for right in owned_roots[left_index + 1 :]:
            left_root, right_root = left[1], right[1]
            if (
                left_root == right_root
                or left_root.startswith(right_root + "/")
                or right_root.startswith(left_root + "/")
            ):
                issues.append(
                    _issue(
                        f"$.writers[{right[2]}].ownership_roots[{right[3]}]",
                        f"overlaps an existing ownership root assigned to {left[0]}: {left_root}",
                    )
                )

    integrator = document.get("integrator", {})
    integrator_id = str(integrator.get("actor_id", "")) if isinstance(integrator, dict) else ""
    if isinstance(integrator, dict):
        if integrator_id.endswith(".lock"):
            issues.append(
                _issue(
                    "$.integrator.actor_id",
                    "must remain a Git-safe branch component and cannot end in .lock",
                )
            )
        if not str(integrator.get("role_ref", "")).startswith(integrator_id + "@"):
            issues.append(_issue("$.integrator.role_ref", "must identify the integrator actor"))
        allowed = set(integrator.get("allowed_actions", []))
        forbidden = set(integrator.get("forbidden_actions", []))
        if allowed & forbidden:
            issues.append(_issue("$.integrator", "allowed and forbidden actions overlap"))
        if not dangerous_actions <= forbidden:
            issues.append(
                _issue(
                    "$.integrator.forbidden_actions",
                    "must forbid approval, default-branch merge, release, and deployment",
                )
            )

    assurance = [
        item for item in document.get("assurance_roles", []) if isinstance(item, dict)
    ]
    assurance_ids = [str(item.get("actor_id", "")) for item in assurance]
    actor_ids = writer_ids + [integrator_id] + assurance_ids
    if len(actor_ids) != len(set(actor_ids)):
        issues.append(_issue("$", "writers, integrator, and assurance roles must be independent identities"))
    kinds = [str(item.get("kind", "")) for item in assurance]
    if kinds.count("tester") != 1 or kinds.count("reviewer") != 1:
        issues.append(_issue("$.assurance_roles", "must contain exactly one tester and one reviewer"))
    for index, role in enumerate(assurance):
        actor = str(role.get("actor_id", ""))
        if actor.endswith(".lock"):
            issues.append(
                _issue(
                    f"$.assurance_roles[{index}].actor_id",
                    "must remain a Git-safe branch component and cannot end in .lock",
                )
            )
        kind = str(role.get("kind", ""))
        if not str(role.get("role_ref", "")).startswith(actor + "@"):
            issues.append(
                _issue(f"$.assurance_roles[{index}].role_ref", "must identify its actor")
            )
        allowed = set(role.get("allowed_actions", []))
        forbidden = set(role.get("forbidden_actions", []))
        if allowed & forbidden:
            issues.append(
                _issue(f"$.assurance_roles[{index}]", "allowed and forbidden actions overlap")
            )
        if not dangerous_actions <= forbidden:
            issues.append(
                _issue(
                    f"$.assurance_roles[{index}].forbidden_actions",
                    "must forbid approval, default-branch merge, release, and deployment",
                )
            )
        allowed_by_kind = {
            "tester": {"evidence.write", "repository.read", "tests.run"},
            "reviewer": {"evidence.read", "repository.read", "review.write"},
        }
        forbidden_by_kind = {
            "tester": dangerous_actions | {"review-own-work", "source.write"},
            "reviewer": dangerous_actions | {"review-own-work", "source.write"},
        }
        if allowed != allowed_by_kind.get(kind, set()):
            issues.append(
                _issue(
                    f"$.assurance_roles[{index}].allowed_actions",
                    "must use the read-only least-privilege action set for its kind",
                )
            )
        if forbidden != forbidden_by_kind.get(kind, set()):
            issues.append(
                _issue(
                    f"$.assurance_roles[{index}].forbidden_actions",
                    "must forbid source writes, self-review, approval, merge, release, and deployment",
                )
            )

    repository = document.get("repository", {})
    base_ref = str(repository.get("base_ref", "")) if isinstance(repository, dict) else ""
    ref_name, separator, commit = base_ref.rpartition("@")
    forbidden_ref_characters = set(" ~^:?*[\\")
    ref_components = ref_name.split("/")
    if (
        not separator
        or len(commit) != 40
        or any(character not in "0123456789abcdef" for character in commit)
        or not ref_name
        or ref_name == "HEAD"
        or ref_name.startswith(("/", ".", "-"))
        or ref_name.endswith(("/", "."))
        or ".." in ref_name
        or "@{" in ref_name
        or "//" in ref_name
        or any(ord(character) < 32 or ord(character) == 127 for character in ref_name)
        or any(character in forbidden_ref_characters for character in ref_name)
        or any(
            not component
            or component.startswith(".")
            or component.endswith(".lock")
            for component in ref_components
        )
    ):
        issues.append(
            _issue(
                "$.repository.base_ref",
                "must bind a Git-safe ref label to one exact lowercase 40-hex commit",
            )
        )

    phases = [item for item in document.get("phases", []) if isinstance(item, dict)]
    sequences = [item.get("sequence") for item in phases]
    if sequences != list(range(1, len(phases) + 1)):
        issues.append(_issue("$.phases", "sequence values must be contiguous and ordered from 1"))
    phase_ids = [str(item.get("phase_id", "")) for item in phases]
    if len(phase_ids) != len(set(phase_ids)):
        issues.append(_issue("$.phases", "phase_id values must be unique"))
    expected_phase_ids = [
        "human-approval",
        "isolated-implementation",
        "deterministic-integration",
        "independent-testing",
        "independent-review",
        "draft-pr-handoff",
    ]
    expected_failure_states = [
        "NEEDS_HUMAN",
        "BLOCKED",
        "NEEDS_HUMAN",
        "FAILED",
        "BLOCKED",
        "NEEDS_HUMAN",
    ]
    if phase_ids != expected_phase_ids:
        issues.append(_issue("$.phases", "phase identities must match the deterministic v1 sequence"))
    if [str(item.get("failure_state", "")) for item in phases] != expected_failure_states:
        issues.append(_issue("$.phases", "failure states must match the reviewed v1 recovery policy"))
    known_actors = set(actor_ids) | {"human.owner"}
    for index, phase in enumerate(phases):
        unknown = sorted(set(phase.get("actors", [])) - known_actors)
        if unknown:
            issues.append(
                _issue(f"$.phases[{index}].actors", f"unknown actors: {', '.join(unknown)}")
            )
    if phases:
        first = phases[0]
        if (
            first.get("actors") != ["human.owner"]
            or first.get("requires") != ["plan-revision"]
            or first.get("produces") != ["approval-grant"]
            or first.get("parallel") is not False
        ):
            issues.append(_issue("$.phases[0]", "must be the exact human approval gate"))
        last = phases[-1]
        if (
            last.get("actors") != [integrator_id]
            or set(last.get("requires", []))
            != {"independent-review", "integration-candidate", "test-evidence"}
            or last.get("produces") != ["draft-pr"]
            or last.get("parallel") is not False
        ):
            issues.append(_issue(f"$.phases[{len(phases) - 1}]", "must stop at integrator-created Draft PR"))

    def phases_producing(artifact: str) -> list[tuple[int, dict[str, Any]]]:
        return [
            (index, phase)
            for index, phase in enumerate(phases)
            if artifact in phase.get("produces", [])
        ]

    implementation = phases_producing("writer-commit")
    if len(implementation) != 1:
        issues.append(_issue("$.phases", "must have exactly one writer-commit phase"))
    else:
        index, phase = implementation[0]
        if (
            index != 1
            or set(phase.get("actors", [])) != set(writer_ids)
            or phase.get("parallel") is not True
            or set(phase.get("requires", [])) != {"approval-grant", "base-commit"}
            or set(phase.get("produces", [])) != {"writer-commit", "writer-evidence"}
        ):
            issues.append(
                _issue(
                    f"$.phases[{index}]",
                    "writer phase must dispatch every isolated writer only after exact approval",
                )
            )
    tester_id = next(
        (str(item.get("actor_id")) for item in assurance if item.get("kind") == "tester"),
        "",
    )
    reviewer_id = next(
        (str(item.get("actor_id")) for item in assurance if item.get("kind") == "reviewer"),
        "",
    )
    required_phase_contracts = (
        (2, "integration-candidate", integrator_id, {"writer-commit", "writer-evidence"}),
        (3, "test-evidence", tester_id, {"integration-candidate"}),
        (4, "independent-review", reviewer_id, {"integration-candidate", "test-evidence"}),
    )
    for expected_index, artifact, actor, required_inputs in required_phase_contracts:
        matching = phases_producing(artifact)
        if (
            len(matching) != 1
            or matching[0][0] != expected_index
            or matching[0][1].get("actors") != [actor]
            or set(matching[0][1].get("requires", [])) != required_inputs
            or matching[0][1].get("produces") != [artifact]
            or matching[0][1].get("parallel") is not False
        ):
            issues.append(
                _issue("$.phases", f"{artifact} has an invalid actor, position, input, or output")
            )
    if len(phases) != 6:
        issues.append(_issue("$.phases", "v1 writer topology requires exactly six phases"))

    required_idempotency = {
        "actor_id",
        "base_commit",
        "phase_id",
        "plan_digest",
        "topology_digest",
        "work_item_id",
    }
    actual_idempotency = set(document.get("recovery", {}).get("idempotency_fields", []))
    if required_idempotency != actual_idempotency:
        issues.append(_issue("$.recovery.idempotency_fields", "does not bind the complete retry identity"))

    host_records = [
        item for item in document.get("host_degradation", []) if isinstance(item, dict)
    ]
    host_ids = [str(item.get("host", "")) for item in host_records]
    if len(host_ids) != len(set(host_ids)):
        issues.append(_issue("$.host_degradation", "host records must be unique"))
    projection_for_tier = {
        "native-install-verified": "native-team-files-no-multiwriter-runtime",
        "verified-export": "role-files-only",
        "experimental-plan": "leader-squad-overlay-no-independent-writer-enforcement",
        "portable": "portable-documents-only",
    }
    limitation_for_projection = {
        "role-files-only": "Role and context files do not create a durable independent-writer controller.",
        "portable-documents-only": "The receiving AI must map every role and gate without weakening the contract.",
        "native-team-files-no-multiwriter-runtime": "Native role and Skill files are installed, but the Factory has not verified a durable multi-writer scheduler.",
        "leader-squad-overlay-no-independent-writer-enforcement": "A Squad wakes its leader; role labels do not enforce write ownership or independent approval.",
    }
    for index, record in enumerate(host_records):
        expected_projection = projection_for_tier.get(str(record.get("support_tier", "")))
        if record.get("projection") != expected_projection:
            issues.append(
                _issue(
                    f"$.host_degradation[{index}].projection",
                    "must match the declared evidence tier without overstating enforcement",
                )
            )
        expected_limitation = limitation_for_projection.get(str(record.get("projection", "")))
        if record.get("limitations") != [expected_limitation]:
            issues.append(
                _issue(
                    f"$.host_degradation[{index}].limitations",
                    "must use the exact reviewed non-enforcement limitation for its projection",
                )
            )
    try:
        from core.host_catalog import load_host_catalog

        catalog = load_host_catalog(repository_root=ROOT)
    except (OSError, RuntimeError, ValueError) as exc:
        issues.append(_issue("$.host_degradation", f"cannot validate Factory host catalog: {exc}"))
    else:
        catalog_claim = document.get("factory_host_catalog", {})
        expected_catalog_digest = digest_value(catalog)
        if not isinstance(catalog_claim, dict) or catalog_claim.get(
            "catalog_digest"
        ) != expected_catalog_digest:
            issues.append(
                _issue(
                    "$.factory_host_catalog.catalog_digest",
                    "differs from the authoritative Factory host catalog",
                )
            )
        if not isinstance(catalog_claim, dict) or catalog_claim.get("hosts") != sorted(catalog):
            issues.append(
                _issue(
                    "$.factory_host_catalog.hosts",
                    "must bind the exact ordered Factory host catalog",
                )
            )
        if set(host_ids) != set(catalog):
            issues.append(
                _issue(
                    "$.host_degradation",
                    "must cover exactly the current Factory host catalog",
                )
            )
        for index, record in enumerate(host_records):
            descriptor = catalog.get(str(record.get("host", "")))
            if descriptor is not None and record.get("support_tier") != descriptor.get(
                "support_tier"
            ):
                issues.append(
                    _issue(
                        f"$.host_degradation[{index}].support_tier",
                        "differs from the authoritative Factory host descriptor",
                    )
                )
    return issues


SEMANTIC_VALIDATORS: dict[str, Callable[[dict[str, Any]], list[ContractIssue]]] = {
    "role_contract": _validate_role,
    "workflow_spec": _validate_workflow,
    "plan_revision": _validate_plan,
    "approval_grant": _validate_approval,
    "run": _validate_run,
    "evidence_bundle": _validate_evidence,
    "adapter_descriptor": _validate_adapter,
    "writer_topology": _validate_writer_topology,
}


def validate_contract(contract: str, document: Any) -> list[ContractIssue]:
    schema_issues: list[SchemaIssue] = validate_schema(document, load_contract_schema(contract))
    issues = [ContractIssue(issue.path, issue.message) for issue in schema_issues]
    if isinstance(document, dict) and not schema_issues:
        validator = SEMANTIC_VALIDATORS.get(contract)
        if validator is not None:
            issues.extend(validator(document))
    return issues


def validate_writer_authority(
    topology: Any,
    plan: Any,
    approval: Any,
) -> list[ContractIssue]:
    """Validate the topology -> plan -> human approval digest authority chain."""

    issues: list[ContractIssue] = []
    documents = (
        ("topology", "writer_topology", topology),
        ("plan", "plan_revision", plan),
        ("approval", "approval_grant", approval),
    )
    for label, contract, document in documents:
        for issue in validate_contract(contract, document):
            suffix = issue.path[1:] if issue.path.startswith("$") else "." + issue.path
            issues.append(_issue(f"$.{label}{suffix}", issue.message))
    if issues or not all(isinstance(document, dict) for _, _, document in documents):
        return issues

    expected_binding = {
        "topology_id": topology["topology_id"],
        "topology_version": topology["topology_version"],
        "topology_digest": topology["topology_digest"],
    }
    if plan.get("writer_topology") != expected_binding:
        issues.append(
            _issue(
                "$.plan.writer_topology",
                "must bind the exact validated WriterTopology identity and digest",
            )
        )
    if approval.get("writer_topology") != expected_binding:
        issues.append(
            _issue(
                "$.approval.writer_topology",
                "must bind the exact validated WriterTopology identity and digest",
            )
        )

    repository = topology["repository"]
    _, separator, topology_commit = repository["base_ref"].rpartition("@")
    if plan.get("repository_id") != repository["repository_id"]:
        issues.append(
            _issue("$.plan.repository_id", "must match the WriterTopology repository")
        )
    if not separator or plan.get("base_commit") != topology_commit:
        issues.append(
            _issue("$.plan.base_commit", "must match the commit-bound WriterTopology base")
        )

    known_actors = {
        str(item["actor_id"])
        for item in topology["writers"]
    } | {str(topology["integrator"]["actor_id"])} | {
        str(item["actor_id"]) for item in topology["assurance_roles"]
    }
    task_roles = {
        str(task.get("role_id", ""))
        for task in plan.get("tasks", [])
        if isinstance(task, dict)
    }
    writer_ids = {str(item["actor_id"]) for item in topology["writers"]}
    missing_writers = sorted(writer_ids - task_roles)
    if missing_writers:
        issues.append(
            _issue(
                "$.plan.tasks",
                "must assign at least one task to every topology writer: "
                + ", ".join(missing_writers),
            )
        )
    unknown_roles = sorted(task_roles - known_actors)
    if unknown_roles:
        issues.append(
            _issue(
                "$.plan.tasks",
                "contains roles outside the approved topology: " + ", ".join(unknown_roles),
            )
        )

    roots = [
        str(root).rstrip("/").casefold()
        for writer in topology["writers"]
        for root in writer["ownership_roots"]
    ]
    for index, raw_path in enumerate(plan.get("allowed_paths", [])):
        candidate = str(raw_path).rstrip("/").casefold()
        if not any(candidate == root or candidate.startswith(root + "/") for root in roots):
            issues.append(
                _issue(
                    f"$.plan.allowed_paths[{index}]",
                    "must remain inside one topology writer ownership root",
                )
            )

    compared_fields = (
        "work_item_id",
        "plan_digest",
        "repository_id",
        "base_commit",
        "writer_topology",
        "allowed_paths",
        "allowed_actions",
        "budget_limit",
        "time_limit_seconds",
    )
    for field in compared_fields:
        if approval.get(field) != plan.get(field):
            issues.append(
                _issue(
                    f"$.approval.{field}",
                    "must equal the exact approved PlanRevision field",
                )
            )
    if approval.get("plan_revision") != plan.get("revision"):
        issues.append(
            _issue("$.approval.plan_revision", "must equal the approved plan revision")
        )
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
