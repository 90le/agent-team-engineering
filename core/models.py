"""Open data contracts used by the reference workflow simulator."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class RiskLevel(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class WorkflowState(StrEnum):
    RECEIVED = "RECEIVED"
    NORMALIZED = "NORMALIZED"
    TRIAGE_PENDING = "TRIAGE_PENDING"
    ACCEPTED = "ACCEPTED"
    SPEC_READY = "SPEC_READY"
    PLAN_APPROVED = "PLAN_APPROVED"
    IMPLEMENTING = "IMPLEMENTING"
    PR_OPEN = "PR_OPEN"
    CI_PASSED = "CI_PASSED"
    REVIEW_APPROVED = "REVIEW_APPROVED"
    STAGING_DEPLOYED = "STAGING_DEPLOYED"
    PROD_APPROVAL_PENDING = "PROD_APPROVAL_PENDING"
    PROD_APPROVED = "PROD_APPROVED"
    DEPLOYED = "DEPLOYED"
    VERIFIED = "VERIFIED"
    CLOSED = "CLOSED"
    REJECTED = "REJECTED"
    BLOCKED = "BLOCKED"
    ROLLED_BACK = "ROLLED_BACK"


@dataclass(frozen=True)
class Actor:
    id: str
    role: str
    kind: str = "agent"

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True)
class FeedbackEvent:
    event_id: str
    channel: str
    message_id: str
    received_at: str
    content: str
    sender_ref: str = "anonymous"

    def to_dict(self) -> dict[str, str]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "FeedbackEvent":
        required = ("event_id", "channel", "message_id", "received_at", "content")
        missing = [name for name in required if not value.get(name)]
        if missing:
            raise ValueError(f"feedback event missing fields: {', '.join(missing)}")
        return cls(
            event_id=str(value["event_id"]),
            channel=str(value["channel"]),
            message_id=str(value["message_id"]),
            received_at=str(value["received_at"]),
            content=str(value["content"]),
            sender_ref=str(value.get("sender_ref", "anonymous")),
        )


@dataclass
class AuditEvent:
    sequence: int
    timestamp: str
    actor_id: str
    actor_role: str
    action: str
    from_state: str
    to_state: str
    revision: int
    evidence: dict[str, str]

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> AuditEvent:
        return cls(
            sequence=int(value["sequence"]),
            timestamp=str(value["timestamp"]),
            actor_id=str(value["actor_id"]),
            actor_role=str(value["actor_role"]),
            action=str(value["action"]),
            from_state=str(value["from_state"]),
            to_state=str(value["to_state"]),
            revision=int(value["revision"]),
            evidence={str(key): str(item) for key, item in value["evidence"].items()},
        )


@dataclass
class WorkItem:
    id: str
    source_event_id: str
    title: str
    summary: str
    risk: RiskLevel
    state: WorkflowState = WorkflowState.RECEIVED
    revision: int = 0
    untrusted_directive_detected: bool = False
    author_id: str | None = None
    plan_approved_by: str | None = None
    production_approved_by: str | None = None
    artifact_digest: str | None = None
    audit: list[AuditEvent] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["risk"] = self.risk.value
        value["state"] = self.state.value
        return value

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> WorkItem:
        return cls(
            id=str(value["id"]),
            source_event_id=str(value["source_event_id"]),
            title=str(value["title"]),
            summary=str(value["summary"]),
            risk=RiskLevel(str(value["risk"])),
            state=WorkflowState(str(value.get("state", WorkflowState.RECEIVED.value))),
            revision=int(value.get("revision", 0)),
            untrusted_directive_detected=bool(value.get("untrusted_directive_detected", False)),
            author_id=str(value["author_id"]) if value.get("author_id") is not None else None,
            plan_approved_by=(
                str(value["plan_approved_by"])
                if value.get("plan_approved_by") is not None
                else None
            ),
            production_approved_by=(
                str(value["production_approved_by"])
                if value.get("production_approved_by") is not None
                else None
            ),
            artifact_digest=(
                str(value["artifact_digest"]) if value.get("artifact_digest") is not None else None
            ),
            audit=[AuditEvent.from_dict(event) for event in value.get("audit", [])],
        )
