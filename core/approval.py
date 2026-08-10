"""Bound approval assertions and a deterministic reference verifier."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Protocol

from core.json_support import loads_strict
from core.schema_validation import validate_schema

ROOT = Path(__file__).resolve().parents[1]
APPROVAL_SCHEMA = ROOT / "schemas" / "approval-assertion.schema.json"
APPROVAL_ACTIONS = frozenset({"approve_plan", "approve_production"})
MAX_APPROVAL_JSON_BYTES = 65_536


class ApprovalVerificationError(RuntimeError):
    """Raised when an approval cannot establish bounded human authority."""


@dataclass(frozen=True)
class VerifiedApproval:
    assertion_id: str
    provider: str
    subject: str
    action: str
    work_item_id: str
    expected_revision: int
    binding_digest: str
    evidence_ref: str
    claim_digest: str


class ApprovalVerifier(Protocol):
    def verify(
        self,
        assertion: dict[str, Any],
        *,
        actor_id: str,
        action: str,
        work_item_id: str,
        expected_revision: int,
        evidence: dict[str, str],
    ) -> VerifiedApproval: ...


def _canonical_json(value: Any) -> str:
    try:
        content = json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError) as exc:
        raise ApprovalVerificationError(f"approval value is not canonical JSON: {exc}") from exc
    if len(content.encode("utf-8")) > MAX_APPROVAL_JSON_BYTES:
        raise ApprovalVerificationError("approval value exceeds 64 KiB")
    return content


def _digest(value: Any) -> str:
    content = _canonical_json(value).encode("utf-8")
    return "sha256:" + hashlib.sha256(content).hexdigest()


def approval_binding_digest(
    action: str,
    work_item_id: str,
    expected_revision: int,
    evidence: dict[str, str],
) -> str:
    """Bind an approval to the exact state transition and evidence."""

    if action not in APPROVAL_ACTIONS:
        raise ApprovalVerificationError(f"unsupported approval action: {action}")
    if not all(isinstance(key, str) and isinstance(value, str) for key, value in evidence.items()):
        raise ApprovalVerificationError("approval evidence must contain string keys and values")
    return _digest(
        {
            "action": action,
            "work_item_id": work_item_id,
            "expected_revision": expected_revision,
            "evidence": dict(sorted(evidence.items())),
        }
    )


def issue_hmac_assertion(
    *,
    key: bytes,
    provider: str,
    assertion_id: str,
    subject: str,
    action: str,
    work_item_id: str,
    expected_revision: int,
    evidence: dict[str, str],
    issued_at_epoch: float,
    expires_at_epoch: float,
    nonce: str,
    evidence_ref: str,
) -> dict[str, Any]:
    """Issue a local reference assertion.

    This helper exists for deterministic tests and controlled local integration.
    A real messaging or identity adapter must authenticate the user before issuing
    an equivalent assertion.
    """

    if len(key) < 32:
        raise ApprovalVerificationError("approval HMAC key must contain at least 32 bytes")
    claim = {
        "assertion_id": assertion_id,
        "provider": provider,
        "subject": subject,
        "decision": "APPROVED",
        "action": action,
        "work_item_id": work_item_id,
        "expected_revision": expected_revision,
        "binding_digest": approval_binding_digest(
            action, work_item_id, expected_revision, evidence
        ),
        "issued_at_epoch": issued_at_epoch,
        "expires_at_epoch": expires_at_epoch,
        "nonce": nonce,
        "evidence_ref": evidence_ref,
    }
    signature = hmac.new(key, _canonical_json(claim).encode("utf-8"), hashlib.sha256).hexdigest()
    return {
        "schema_version": "1.0.0",
        "claim": claim,
        "signature": "hmac-sha256:" + signature,
    }


class HMACApprovalVerifier:
    """Reference verifier with exact binding, expiry, provider, and subject checks."""

    def __init__(
        self,
        provider: str,
        key: bytes,
        *,
        clock: Callable[[], float] = time.time,
        maximum_lifetime_seconds: int = 900,
        future_skew_seconds: int = 30,
    ) -> None:
        if len(key) < 32:
            raise ApprovalVerificationError("approval HMAC key must contain at least 32 bytes")
        if not 1 <= maximum_lifetime_seconds <= 3600:
            raise ApprovalVerificationError("maximum approval lifetime must be 1-3600 seconds")
        if not 0 <= future_skew_seconds <= 300:
            raise ApprovalVerificationError("approval future skew must be 0-300 seconds")
        self.provider = provider
        self.key = key
        self.clock = clock
        self.maximum_lifetime_seconds = maximum_lifetime_seconds
        self.future_skew_seconds = future_skew_seconds
        self.schema = loads_strict(APPROVAL_SCHEMA.read_text(encoding="utf-8"))

    def verify(
        self,
        assertion: dict[str, Any],
        *,
        actor_id: str,
        action: str,
        work_item_id: str,
        expected_revision: int,
        evidence: dict[str, str],
    ) -> VerifiedApproval:
        issues = validate_schema(assertion, self.schema)
        if issues:
            details = "; ".join(f"{issue.path}: {issue.message}" for issue in issues)
            raise ApprovalVerificationError(f"approval assertion violates schema: {details}")
        claim = assertion["claim"]
        expected_signature = (
            "hmac-sha256:"
            + hmac.new(
                self.key,
                _canonical_json(claim).encode("utf-8"),
                hashlib.sha256,
            ).hexdigest()
        )
        if not hmac.compare_digest(str(assertion["signature"]), expected_signature):
            raise ApprovalVerificationError("approval signature is invalid")
        if claim["provider"] != self.provider:
            raise ApprovalVerificationError("approval provider does not match the verifier")
        if claim["subject"] != actor_id:
            raise ApprovalVerificationError("approval subject does not match the owner actor")
        if claim["action"] != action or action not in APPROVAL_ACTIONS:
            raise ApprovalVerificationError("approval action does not match the transition")
        if claim["work_item_id"] != work_item_id:
            raise ApprovalVerificationError("approval work item does not match the transition")
        if claim["expected_revision"] != expected_revision:
            raise ApprovalVerificationError("approval revision does not match the transition")
        expected_binding = approval_binding_digest(
            action, work_item_id, expected_revision, evidence
        )
        if claim["binding_digest"] != expected_binding:
            raise ApprovalVerificationError("approval evidence binding does not match")
        if evidence.get("approval_id") != claim["assertion_id"]:
            raise ApprovalVerificationError("approval_id evidence does not match the assertion")

        issued_at = float(claim["issued_at_epoch"])
        expires_at = float(claim["expires_at_epoch"])
        now = float(self.clock())
        if expires_at <= issued_at:
            raise ApprovalVerificationError("approval expiry must follow issuance")
        if expires_at - issued_at > self.maximum_lifetime_seconds:
            raise ApprovalVerificationError("approval lifetime exceeds verifier policy")
        if issued_at > now + self.future_skew_seconds:
            raise ApprovalVerificationError("approval was issued too far in the future")
        if expires_at <= now:
            raise ApprovalVerificationError("approval assertion has expired")

        return VerifiedApproval(
            assertion_id=str(claim["assertion_id"]),
            provider=str(claim["provider"]),
            subject=str(claim["subject"]),
            action=str(claim["action"]),
            work_item_id=str(claim["work_item_id"]),
            expected_revision=int(claim["expected_revision"]),
            binding_digest=str(claim["binding_digest"]),
            evidence_ref=str(claim["evidence_ref"]),
            claim_digest=_digest(claim),
        )
