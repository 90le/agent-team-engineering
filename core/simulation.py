"""Deterministic, side-effect-free reference scenario."""

from __future__ import annotations

import hashlib

from core.models import Actor, FeedbackEvent, WorkItem
from core.policy import contains_untrusted_directive, infer_risk
from core.security import redact_credential_like
from core.workflow import transition

ACTORS = {
    "intake": Actor("agent-intake", "public-intake"),
    "triage": Actor("agent-triage", "triage"),
    "product": Actor("agent-product", "product"),
    "owner": Actor("owner-demo", "owner", kind="human"),
    "builder": Actor("agent-builder", "builder"),
    "qa": Actor("agent-qa", "qa"),
    "reviewer": Actor("agent-reviewer", "reviewer"),
    "release": Actor("agent-release", "release"),
    "operations": Actor("agent-operations", "operations"),
}


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def create_work_item(event: FeedbackEvent) -> WorkItem:
    stable_id = _digest(f"{event.channel}:{event.message_id}")[:16]
    summary = redact_credential_like(" ".join(event.content.split()))[:240]
    return WorkItem(
        id=f"work-{stable_id}",
        source_event_id=event.event_id,
        title=f"反馈：{summary[:60]}",
        summary=summary,
        risk=infer_risk(event.content),
        untrusted_directive_detected=contains_untrusted_directive(event.content),
    )


def _step(item: WorkItem, action: str, actor_key: str, evidence: dict[str, str]) -> None:
    transition(
        item,
        action,
        ACTORS[actor_key],
        evidence,
        expected_revision=item.revision,
    )


def run_feedback_to_release(event: FeedbackEvent, *, approve_production: bool = False) -> WorkItem:
    item = create_work_item(event)
    commit = _digest(item.id)[:40]
    artifact_digest = f"sha256:{_digest(commit)}"

    _step(item, "normalize", "intake", {"source": event.event_id, "content_mode": "untrusted-data"})
    _step(
        item, "queue_triage", "intake", {"queue": "software-delivery", "idempotency_key": item.id}
    )
    _step(item, "accept_triage", "triage", {"decision": "accept-for-demo", "risk": item.risk.value})
    _step(item, "write_spec", "product", {"spec_id": f"spec-{item.id}", "acceptance_count": "2"})
    _step(
        item,
        "approve_plan",
        "owner",
        {"approval_id": "approval-plan-demo", "scope_hash": _digest(item.summary)},
    )
    _step(
        item,
        "start_implementation",
        "builder",
        {"workspace": "ephemeral-demo", "branch": f"agent/demo/{item.id}"},
    )
    _step(item, "open_pr", "builder", {"pull_request": "demo://pull/1", "commit": commit})
    _step(item, "record_ci_pass", "qa", {"check_run": "demo://checks/1", "result": "passed"})
    _step(
        item,
        "approve_review",
        "reviewer",
        {"review_id": "demo://reviews/1", "decision": "approved"},
    )
    _step(
        item,
        "deploy_staging",
        "release",
        {"artifact_digest": artifact_digest, "environment": "staging-demo"},
    )
    _step(item, "accept_staging", "qa", {"acceptance": "passed", "evidence": "demo://acceptance/1"})

    if not approve_production:
        return item

    _step(
        item,
        "approve_production",
        "owner",
        {"approval_id": "approval-production-demo", "artifact_digest": artifact_digest},
    )
    _step(
        item,
        "deploy_production",
        "release",
        {"artifact_digest": artifact_digest, "environment": "production-demo"},
    )
    _step(
        item,
        "verify_production",
        "operations",
        {"health": "healthy", "observation_window": "simulated"},
    )
    _step(item, "close", "operations", {"closure": "verified", "feedback_notified": "simulated"})
    return item
