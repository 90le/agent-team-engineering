"""Small signed-webhook boundary for inbound adapter implementations."""

from __future__ import annotations

import hashlib
import hmac
import re
import sqlite3
from pathlib import Path
from typing import Any

from core.json_support import loads_strict
from core.models import FeedbackEvent
from core.schema_validation import validate_schema

ROOT = Path(__file__).resolve().parents[1]
FEEDBACK_SCHEMA = ROOT / "schemas" / "feedback-event.schema.json"
DELIVERY_ID = re.compile(r"^[A-Za-z0-9._:-]{1,200}$")
GITHUB_EVENT = re.compile(r"^[a-z][a-z0-9_]{0,99}$")
MAX_WEBHOOK_BYTES = 1_000_000


class WebhookVerificationError(RuntimeError):
    pass


class GitHubWebhookLedger:
    """Durably authenticate and deduplicate GitHub deliveries without storing bodies."""

    def __init__(self, database: Path) -> None:
        self.connection = sqlite3.connect(database)
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS github_webhook_deliveries(
                delivery_id TEXT PRIMARY KEY,
                payload_digest TEXT NOT NULL,
                event_name TEXT NOT NULL,
                repository TEXT NOT NULL
            )
            """
        )
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> "GitHubWebhookLedger":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        del exc_type, exc, traceback
        self.close()

    def accept(
        self,
        payload: bytes,
        *,
        delivery_id: str,
        event_name: str,
        signature_header: str,
        secret: bytes,
        expected_repository: str,
        allowed_events: frozenset[str],
    ) -> dict[str, Any]:
        if not DELIVERY_ID.fullmatch(delivery_id):
            raise WebhookVerificationError("GitHub delivery id is invalid")
        if not GITHUB_EVENT.fullmatch(event_name) or event_name not in allowed_events:
            raise WebhookVerificationError("GitHub event is outside the inbound allowlist")
        verify_hmac_sha256(payload, signature_header, secret)
        try:
            value = loads_strict(payload.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise WebhookVerificationError(f"GitHub webhook is not UTF-8 JSON: {exc}") from exc
        if not isinstance(value, dict):
            raise WebhookVerificationError("GitHub webhook JSON root must be an object")
        repository = value.get("repository")
        if not isinstance(repository, dict) or repository.get("full_name") != expected_repository:
            raise WebhookVerificationError("GitHub webhook repository differs from the binding")
        digest = "sha256:" + hashlib.sha256(payload).hexdigest()
        existing = self.connection.execute(
            "SELECT payload_digest, event_name, repository FROM github_webhook_deliveries WHERE delivery_id = ?",
            (delivery_id,),
        ).fetchone()
        if existing is not None:
            if existing != (digest, event_name, expected_repository):
                raise WebhookVerificationError(
                    "GitHub delivery id was replayed with different authenticated content"
                )
            replayed = True
        else:
            self.connection.execute(
                "INSERT INTO github_webhook_deliveries(delivery_id, payload_digest, event_name, repository) VALUES(?, ?, ?, ?)",
                (delivery_id, digest, event_name, expected_repository),
            )
            self.connection.commit()
            replayed = False
        sender = value.get("sender")
        sender_id = str(sender.get("id")) if isinstance(sender, dict) and sender.get("id") else None
        return {
            "delivery_id": delivery_id,
            "event_name": event_name,
            "repository": expected_repository,
            "payload_digest": digest,
            "sender_id": sender_id,
            "action": str(value.get("action", "")),
            "replayed": replayed,
        }


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
