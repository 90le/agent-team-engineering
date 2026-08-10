"""Small signed-webhook boundary for inbound adapter implementations."""

from __future__ import annotations

import hashlib
import hmac
import re
from pathlib import Path
from typing import Any

from core.json_support import loads_strict
from core.models import FeedbackEvent
from core.schema_validation import validate_schema

ROOT = Path(__file__).resolve().parents[1]
FEEDBACK_SCHEMA = ROOT / "schemas" / "feedback-event.schema.json"
DELIVERY_ID = re.compile(r"^[A-Za-z0-9._:-]{1,200}$")
MAX_WEBHOOK_BYTES = 1_000_000


class WebhookVerificationError(RuntimeError):
    pass


def verify_hmac_sha256(payload: bytes, signature_header: str, secret: bytes) -> None:
    if not secret:
        raise WebhookVerificationError("webhook secret must not be empty")
    if len(payload) > MAX_WEBHOOK_BYTES:
        raise WebhookVerificationError("webhook payload exceeds 1 MiB")
    expected = "sha256=" + hmac.new(secret, payload, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature_header, expected):
        raise WebhookVerificationError("webhook signature is invalid")


def parse_signed_feedback(
    payload: bytes,
    *,
    delivery_id: str,
    signature_header: str,
    secret: bytes,
) -> FeedbackEvent:
    if not DELIVERY_ID.fullmatch(delivery_id):
        raise WebhookVerificationError("webhook delivery id is invalid")
    verify_hmac_sha256(payload, signature_header, secret)
    try:
        value: Any = loads_strict(payload.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise WebhookVerificationError(f"webhook body is not UTF-8 JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise WebhookVerificationError("webhook JSON root must be an object")
    schema = loads_strict(FEEDBACK_SCHEMA.read_text(encoding="utf-8"))
    issues = validate_schema(value, schema)
    if issues:
        details = "; ".join(f"{issue.path}: {issue.message}" for issue in issues)
        raise WebhookVerificationError(f"feedback event violates schema: {details}")
    event = FeedbackEvent.from_dict(value)
    if event.event_id != delivery_id:
        raise WebhookVerificationError("feedback event_id must equal the authenticated delivery id")
    return event
