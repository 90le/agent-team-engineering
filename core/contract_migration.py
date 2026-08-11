"""Fail-closed, one-way import helpers from the v0.7 portable model.

Migration never edits a source document or grants new authority.  Contracts
whose meaning cannot be preserved require a reviewed recompile or a new human
approval instead of an automatic conversion.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from core.contracts import digest_value, require_contract


class MigrationError(ValueError):
    pass


@dataclass(frozen=True)
class MigrationResult:
    source_contract: str
    target_contract: str
    document: dict[str, Any]
    warnings: tuple[str, ...]


SAFE_STATE_MAP = {
    "RECEIVED": "RECEIVED",
    "NORMALIZED": "NORMALIZED",
    "TRIAGE_PENDING": "NORMALIZED",
    "ACCEPTED": "TRIAGED",
    "SPEC_READY": "PLANNED",
    "PLAN_APPROVED": "APPROVED",
    "IMPLEMENTING": "EXECUTING",
    "PR_OPEN": "DRAFT_PR_READY",
    "CI_PASSED": "DRAFT_PR_READY",
    "REVIEW_APPROVED": "DRAFT_PR_READY",
    "CLOSED": "COMPLETED",
    "REJECTED": "REJECTED",
    "BLOCKED": "BLOCKED",
    "ROLLED_BACK": "CANCELLED",
}

POST_DRAFT_V07_STATES = frozenset(
    {
        "STAGING_DEPLOYED",
        "PROD_APPROVAL_PENDING",
        "PROD_APPROVED",
        "DEPLOYED",
        "VERIFIED",
    }
)


def _received_at(source: dict[str, Any], migrated_at: str | None) -> str:
    audit = source.get("audit", [])
    if isinstance(audit, list):
        for event in audit:
            if isinstance(event, dict) and isinstance(event.get("timestamp"), str):
                return str(event["timestamp"])
    if migrated_at is None:
        raise MigrationError("migrated_at is required when the v0.7 audit has no timestamp")
    return migrated_at


def migrate_work_item_v1(
    source: dict[str, Any],
    *,
    migrated_at: str | None = None,
    repository_candidates: tuple[str, ...] = (),
) -> MigrationResult:
    """Import the safe subset of a v0.7 WorkItem as a new v0.8 document.

    The caller retains the original source as rollback evidence.  States that
    imply staging, production approval, deployment, or post-deploy verification
    are rejected because v0.8 stops at a draft pull request.
    """

    required = ("id", "source_event_id", "title", "summary", "risk", "state", "revision")
    missing = [field for field in required if field not in source]
    if missing:
        raise MigrationError(f"v0.7 work item is missing fields: {', '.join(missing)}")
    state = str(source["state"])
    if state in POST_DRAFT_V07_STATES:
        raise MigrationError(
            f"v0.7 state {state} exceeds the v0.8 DRAFT_PR_READY authority boundary"
        )
    try:
        target_state = SAFE_STATE_MAP[state]
    except KeyError as exc:
        raise MigrationError(f"v0.7 state has no reviewed v0.8 mapping: {state}") from exc

    work_item_id = str(source["id"])
    if not work_item_id.startswith("work-"):
        raise MigrationError("v0.7 work item id is not portable")
    title = str(source["title"])
    summary = str(source["summary"])
    risk = str(source["risk"])
    if risk not in {"LOW", "MEDIUM", "HIGH", "CRITICAL"}:
        raise MigrationError(f"unknown v0.7 risk level: {risk}")
    content_level = "HIGH" if risk in {"HIGH", "CRITICAL"} else risk
    if bool(source.get("untrusted_directive_detected", False)):
        content_level = "HIGH"

    document = {
        "$schema": "urn:agent-team:schema:work-item:2.0.0",
        "schema_version": "2.0.0",
        "work_item_id": work_item_id,
        "source": {
            "ingress_port": "native.v07-import",
            "event_id": str(source["source_event_id"]),
            "external_ref": f"v0.7:{work_item_id}",
            "received_at": _received_at(source, migrated_at),
        },
        "normalized": {
            "title": title,
            "summary": summary,
            "untrusted_content_level": content_level,
            "target_repository_candidates": list(repository_candidates),
            "duplicate_fingerprint": digest_value(
                {"title": title.strip().lower(), "summary": summary.strip().lower()}
            ),
            "sensitive_data_flags": [],
        },
        "state": target_state,
        "revision": int(source["revision"]),
        "created_event_id": f"migration-{work_item_id}",
    }
    require_contract("work_item", document)
    warnings = [
        "Repository candidates are caller-supplied and require project binding review.",
        "v0.7 audit events remain source evidence; they are not rewritten as v0.8 controller events.",
    ]
    if risk == "CRITICAL":
        warnings.append("CRITICAL risk is represented as HIGH untrusted-content level; risk review remains external.")
    return MigrationResult(
        source_contract="urn:agent-team:schema:work-item:1.0.0",
        target_contract="urn:agent-team:schema:work-item:2.0.0",
        document=document,
        warnings=tuple(warnings),
    )
