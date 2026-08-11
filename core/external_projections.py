"""Pure, optional projections for external platforms.

No function imports an external SDK, starts a process, performs network I/O, or
accepts an external platform as workflow authority.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from core.contracts import canonical_json, digest_value, require_contract
from core.json_support import loads_strict
from core.schema_validation import validate_schema
from core.security import redact_credential_like

ROOT = Path(__file__).resolve().parents[1]
TASK_SCHEMA = ROOT / "schemas" / "agent-step-task.schema.json"
FEEDBACK_SCHEMA = ROOT / "schemas" / "feedback-event.schema.json"


class ExternalProjectionError(RuntimeError):
    """Raised before optional platform data crosses a narrow adapter boundary."""


def _copy(value: Any) -> Any:
    return loads_strict(canonical_json(value))


def _validate(value: dict[str, Any], schema_path: Path, label: str) -> dict[str, Any]:
    schema = loads_strict(schema_path.read_text(encoding="utf-8"))
    issues = validate_schema(value, schema)
    if issues:
        details = "; ".join(f"{issue.path}: {issue.message}" for issue in issues)
        raise ExternalProjectionError(f"invalid {label}: {details}")
    return _copy(value)


def project_work_item_to_paperclip(
    work_item: dict[str, Any], *, event_sequence: int
) -> dict[str, Any]:
    item = require_contract("work_item", work_item)
    if (
        not isinstance(event_sequence, int)
        or isinstance(event_sequence, bool)
        or event_sequence < 1
    ):
        raise ExternalProjectionError("Paperclip projection requires a positive event sequence")
    return {
        "projection_version": "agent-team.paperclip/1.0.0",
        "projection_only": True,
        "source_authority": "agent-team-native-controller",
        "source_event_sequence": event_sequence,
        "source_revision": item["revision"],
        "work_item_id": item["work_item_id"],
        "title": item["normalized"]["title"],
        "summary": item["normalized"]["summary"],
        "status": item["state"],
        "source_digest": digest_value(item),
        "commands_accepted_from_projection": False,
        "approval_accepted_from_projection": False,
    }


def _agent_projection(
    task: dict[str, Any], *, protocol: str, output_mode: str
) -> dict[str, Any]:
    task = _validate(task, TASK_SCHEMA, "agent step task")
    return {
        "protocol": protocol,
        "operation": "agent.execute",
        "task": task,
        "output_contract": "urn:agent-team:schema:agent-step-result:1.0.0",
        "output_mode": output_mode,
        "authority": {
            "state_transition_allowed": False,
            "approval_allowed": False,
            "merge_allowed": False,
            "deployment_allowed": False,
            "credential_values_allowed": False,
        },
    }


def project_task_to_openhands(task: dict[str, Any]) -> dict[str, Any]:
    return _agent_projection(
        task,
        protocol="agent-team.openhands-agent-server/1.0.0",
        output_mode="schema-bound-result",
    )


def project_task_to_acp(task: dict[str, Any]) -> dict[str, Any]:
    return _agent_projection(
        task,
        protocol="agent-team.acp-bridge/1.0.0",
        output_mode="acp-session-result-adapter",
    )


def normalize_openclaw_feedback(
    *,
    authenticated_delivery_id: str,
    channel: str,
    message_id: str,
    received_at: str,
    content: str,
    sender_ref: str | None = None,
) -> dict[str, Any]:
    if not authenticated_delivery_id or len(authenticated_delivery_id) > 200:
        raise ExternalProjectionError("OpenClaw delivery id is invalid")
    document: dict[str, Any] = {
        "event_id": authenticated_delivery_id,
        "channel": channel,
        "message_id": message_id,
        "received_at": received_at,
        "content": redact_credential_like(content),
    }
    if sender_ref is not None:
        document["sender_ref"] = sender_ref
    return _validate(document, FEEDBACK_SCHEMA, "OpenClaw feedback projection")


def openclaw_status_notification(
    *, work_item_id: str, status: str, message_ref: str
) -> dict[str, str]:
    if not work_item_id or not status or not message_ref:
        raise ExternalProjectionError("OpenClaw notification fields cannot be empty")
    return {
        "work_item_id": work_item_id,
        "status": status,
        "message_ref": message_ref,
    }


def reject_chat_approval() -> None:
    raise ExternalProjectionError(
        "chat content is never an ApprovalGrant; use a separate authenticated identity adapter"
    )
