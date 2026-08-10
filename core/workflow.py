"""Revision-safe software delivery state machine."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from core.models import Actor, AuditEvent, WorkItem, WorkflowState, utc_now
from core.policy import require_capability, require_independent_reviewer


class WorkflowError(RuntimeError):
    pass


class InvalidTransition(WorkflowError):
    pass


class RevisionConflict(WorkflowError):
    pass


class MissingEvidence(WorkflowError):
    pass


class ApprovalRequired(WorkflowError):
    pass


@dataclass(frozen=True)
class Transition:
    action: str
    from_states: frozenset[WorkflowState]
    to_state: WorkflowState
    capability: str


TRANSITIONS: dict[str, Transition] = {
    "normalize": Transition("normalize", frozenset({WorkflowState.RECEIVED}), WorkflowState.NORMALIZED, "feedback.normalize"),
    "queue_triage": Transition("queue_triage", frozenset({WorkflowState.NORMALIZED}), WorkflowState.TRIAGE_PENDING, "feedback.queue"),
    "accept_triage": Transition("accept_triage", frozenset({WorkflowState.TRIAGE_PENDING}), WorkflowState.ACCEPTED, "work.triage"),
    "write_spec": Transition("write_spec", frozenset({WorkflowState.ACCEPTED}), WorkflowState.SPEC_READY, "spec.write"),
    "approve_plan": Transition("approve_plan", frozenset({WorkflowState.SPEC_READY}), WorkflowState.PLAN_APPROVED, "plan.approve"),
    "start_implementation": Transition("start_implementation", frozenset({WorkflowState.PLAN_APPROVED}), WorkflowState.IMPLEMENTING, "implementation.start"),
    "open_pr": Transition("open_pr", frozenset({WorkflowState.IMPLEMENTING}), WorkflowState.PR_OPEN, "pr.open"),
    "record_ci_pass": Transition("record_ci_pass", frozenset({WorkflowState.PR_OPEN}), WorkflowState.CI_PASSED, "ci.record"),
    "approve_review": Transition("approve_review", frozenset({WorkflowState.CI_PASSED}), WorkflowState.REVIEW_APPROVED, "review.approve"),
    "deploy_staging": Transition("deploy_staging", frozenset({WorkflowState.REVIEW_APPROVED}), WorkflowState.STAGING_DEPLOYED, "staging.deploy"),
    "accept_staging": Transition("accept_staging", frozenset({WorkflowState.STAGING_DEPLOYED}), WorkflowState.PROD_APPROVAL_PENDING, "staging.accept"),
    "approve_production": Transition("approve_production", frozenset({WorkflowState.PROD_APPROVAL_PENDING}), WorkflowState.PROD_APPROVED, "production.approve"),
    "deploy_production": Transition("deploy_production", frozenset({WorkflowState.PROD_APPROVED}), WorkflowState.DEPLOYED, "production.deploy"),
    "verify_production": Transition("verify_production", frozenset({WorkflowState.DEPLOYED}), WorkflowState.VERIFIED, "production.verify"),
    "close": Transition("close", frozenset({WorkflowState.VERIFIED}), WorkflowState.CLOSED, "work.close"),
    "rollback": Transition("rollback", frozenset({WorkflowState.DEPLOYED, WorkflowState.VERIFIED}), WorkflowState.ROLLED_BACK, "production.rollback"),
}


def _require_fields(evidence: dict[str, str], names: Iterable[str]) -> None:
    missing = [name for name in names if not evidence.get(name)]
    if missing:
        raise MissingEvidence(f"missing evidence: {', '.join(missing)}")


def transition(
    item: WorkItem,
    action: str,
    actor: Actor,
    evidence: dict[str, str],
    *,
    expected_revision: int,
) -> WorkItem:
    if expected_revision != item.revision:
        raise RevisionConflict(
            f"expected revision {expected_revision}, current revision is {item.revision}"
        )
    rule = TRANSITIONS.get(action)
    if not rule or item.state not in rule.from_states:
        raise InvalidTransition(f"action {action} is not valid from {item.state.value}")
    require_capability(actor, rule.capability)
    if not evidence:
        raise MissingEvidence("every transition requires durable evidence")

    if action == "approve_review":
        require_independent_reviewer(actor, item)
        _require_fields(evidence, ("review_id", "decision"))
    elif action == "record_ci_pass":
        _require_fields(evidence, ("check_run", "result"))
    elif action == "approve_plan":
        _require_fields(evidence, ("approval_id", "scope_hash"))
        item.plan_approved_by = actor.id
    elif action == "start_implementation":
        if not item.plan_approved_by:
            raise ApprovalRequired("implementation requires an approved plan")
        item.author_id = actor.id
    elif action == "open_pr":
        _require_fields(evidence, ("pull_request", "commit"))
    elif action == "deploy_staging":
        _require_fields(evidence, ("artifact_digest", "environment"))
        item.artifact_digest = evidence["artifact_digest"]
    elif action == "approve_production":
        _require_fields(evidence, ("approval_id", "artifact_digest"))
        if evidence["artifact_digest"] != item.artifact_digest:
            raise ApprovalRequired("approval is not bound to the staged artifact digest")
        item.production_approved_by = actor.id
    elif action == "deploy_production":
        _require_fields(evidence, ("artifact_digest", "environment"))
        if not item.production_approved_by:
            raise ApprovalRequired("production deployment requires explicit owner approval")
        if evidence["artifact_digest"] != item.artifact_digest:
            raise ApprovalRequired("production artifact differs from the approved artifact")

    old_state = item.state
    item.state = rule.to_state
    item.revision += 1
    item.audit.append(
        AuditEvent(
            sequence=len(item.audit) + 1,
            timestamp=utc_now(),
            actor_id=actor.id,
            actor_role=actor.role,
            action=action,
            from_state=old_state.value,
            to_state=item.state.value,
            revision=item.revision,
            evidence=dict(sorted(evidence.items())),
        )
    )
    return item
