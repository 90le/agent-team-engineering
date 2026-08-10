from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.approval import (
    ApprovalVerificationError,
    HMACApprovalVerifier,
    issue_hmac_assertion,
)
from core.control_plane import ControlPlane
from core.models import Actor, FeedbackEvent, WorkflowState
from core.policy import PermissionDenied


class FakeClock:
    def __init__(self, value: float = 1_786_334_400.0) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


KEY = b"local-reference-approval-key-material-32-bytes"
PROVIDER = "approval-provider.local-hmac"
OWNER = Actor("human.project-owner", "owner", kind="human")


def feedback() -> FeedbackEvent:
    return FeedbackEvent(
        event_id="feedback-approval-1",
        channel="test-im",
        message_id="message-approval-1",
        received_at="2026-08-10T00:00:00Z",
        content="Add an accessible project status filter.",
        sender_ref="test-user",
    )


def prepare_spec(control: ControlPlane) -> str:
    work_id = control.ingest_feedback(feedback(), idempotency_key="approval:feedback:1")[
        "work_item"
    ]["id"]
    steps = (
        ("normalize", Actor("agent-intake", "public-intake"), {"source": "test"}),
        (
            "queue_triage",
            Actor("agent-intake", "public-intake"),
            {"queue": "software-delivery", "idempotency_key": work_id},
        ),
        (
            "accept_triage",
            Actor("agent-triage", "triage"),
            {"decision": "accepted", "risk": "LOW"},
        ),
        (
            "write_spec",
            Actor("agent-product", "product"),
            {"spec_id": "spec-approval-1", "acceptance_count": "2"},
        ),
    )
    for revision, (action, actor, evidence) in enumerate(steps):
        lease = control.acquire_lease(
            work_id,
            actor,
            expected_revision=revision,
            ttl_seconds=60,
            idempotency_key=f"approval:lease:{revision}",
        )["lease"]
        control.apply_transition(
            work_id,
            action,
            actor,
            evidence,
            expected_revision=revision,
            idempotency_key=f"approval:transition:{revision}",
            lease_id=lease["lease_id"],
        )
    return work_id


def assertion(clock: FakeClock, work_id: str, evidence: dict[str, str]) -> dict:
    return issue_hmac_assertion(
        key=KEY,
        provider=PROVIDER,
        assertion_id=evidence["approval_id"],
        subject=OWNER.id,
        action="approve_plan",
        work_item_id=work_id,
        expected_revision=4,
        evidence=evidence,
        issued_at_epoch=clock(),
        expires_at_epoch=clock() + 300,
        nonce="nonce-approval-0001",
        evidence_ref="local-approval://events/approval-plan-1",
    )


class BoundApprovalTests(unittest.TestCase):
    def test_approval_material_is_size_bounded(self) -> None:
        clock = FakeClock()
        with self.assertRaises(ApprovalVerificationError):
            assertion(
                clock,
                "work-approval-size",
                {
                    "approval_id": "approval-plan-oversized",
                    "scope_hash": "x" * 70_000,
                },
            )

    def test_verified_human_assertion_commits_owner_transition(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            clock = FakeClock()
            verifier = HMACApprovalVerifier(PROVIDER, KEY, clock=clock)
            database = Path(temporary) / "state.sqlite3"
            with ControlPlane(
                database,
                clock=clock,
                approval_verifier=verifier,
            ) as control:
                work_id = prepare_spec(control)
                evidence = {
                    "approval_id": "approval-plan-1",
                    "scope_hash": "sha256:" + ("a" * 64),
                }
                signed = assertion(clock, work_id, evidence)
                result = control.apply_transition(
                    work_id,
                    "approve_plan",
                    OWNER,
                    evidence,
                    expected_revision=4,
                    idempotency_key="approval:plan:verified:1",
                    approval_assertion=signed,
                )
                self.assertEqual(result["work_item"]["state"], WorkflowState.PLAN_APPROVED.value)
                recorded = result["work_item"]["audit"][-1]["evidence"]
                self.assertEqual(recorded["approval_provider"], PROVIDER)
                self.assertIn("approval_claim_digest", recorded)
                signature = signed["signature"].encode("utf-8")
                for database_file in sorted(Path(temporary).glob("state.sqlite3*")):
                    content = database_file.read_bytes()
                    self.assertNotIn(signature, content, database_file.name)
                    self.assertNotIn(KEY, content, database_file.name)

    def test_owner_transition_fails_without_verifier(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            clock = FakeClock()
            with ControlPlane(Path(temporary) / "state.sqlite3", clock=clock) as control:
                work_id = prepare_spec(control)
                evidence = {"approval_id": "approval-plan-1", "scope_hash": "sha256:test"}
                with self.assertRaises(PermissionDenied):
                    control.apply_transition(
                        work_id,
                        "approve_plan",
                        OWNER,
                        evidence,
                        expected_revision=4,
                        idempotency_key="approval:plan:no-verifier",
                        approval_assertion=assertion(clock, work_id, evidence),
                    )

    def test_tampered_or_wrongly_bound_assertion_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            clock = FakeClock()
            verifier = HMACApprovalVerifier(PROVIDER, KEY, clock=clock)
            with ControlPlane(
                Path(temporary) / "state.sqlite3",
                clock=clock,
                approval_verifier=verifier,
            ) as control:
                work_id = prepare_spec(control)
                approved_evidence = {
                    "approval_id": "approval-plan-1",
                    "scope_hash": "sha256:" + ("a" * 64),
                }
                signed = assertion(clock, work_id, approved_evidence)
                with self.assertRaises(ApprovalVerificationError):
                    control.apply_transition(
                        work_id,
                        "approve_plan",
                        OWNER,
                        {
                            "approval_id": "approval-plan-1",
                            "scope_hash": "sha256:" + ("b" * 64),
                        },
                        expected_revision=4,
                        idempotency_key="approval:plan:wrong-binding",
                        approval_assertion=signed,
                    )
                signed["claim"]["subject"] = "human.someone-else"
                with self.assertRaises(ApprovalVerificationError):
                    control.apply_transition(
                        work_id,
                        "approve_plan",
                        OWNER,
                        approved_evidence,
                        expected_revision=4,
                        idempotency_key="approval:plan:tampered",
                        approval_assertion=signed,
                    )

    def test_expired_assertion_fails_but_committed_idempotent_replay_survives_expiry(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            clock = FakeClock()
            verifier = HMACApprovalVerifier(PROVIDER, KEY, clock=clock)
            with ControlPlane(
                Path(temporary) / "state.sqlite3",
                clock=clock,
                approval_verifier=verifier,
            ) as control:
                work_id = prepare_spec(control)
                evidence = {
                    "approval_id": "approval-plan-1",
                    "scope_hash": "sha256:" + ("a" * 64),
                }
                signed = assertion(clock, work_id, evidence)
                first = control.apply_transition(
                    work_id,
                    "approve_plan",
                    OWNER,
                    evidence,
                    expected_revision=4,
                    idempotency_key="approval:plan:replay",
                    approval_assertion=signed,
                )
                clock.advance(301)
                replay = control.apply_transition(
                    work_id,
                    "approve_plan",
                    OWNER,
                    evidence,
                    expected_revision=4,
                    idempotency_key="approval:plan:replay",
                    approval_assertion=signed,
                )
                self.assertFalse(first["replayed"])
                self.assertTrue(replay["replayed"])

            with tempfile.TemporaryDirectory() as second_temporary:
                clock = FakeClock()
                verifier = HMACApprovalVerifier(PROVIDER, KEY, clock=clock)
                with ControlPlane(
                    Path(second_temporary) / "state.sqlite3",
                    clock=clock,
                    approval_verifier=verifier,
                ) as control:
                    work_id = prepare_spec(control)
                    evidence = {
                        "approval_id": "approval-plan-expired",
                        "scope_hash": "sha256:" + ("a" * 64),
                    }
                    signed = assertion(clock, work_id, evidence)
                    clock.advance(301)
                    with self.assertRaises(ApprovalVerificationError):
                        control.apply_transition(
                            work_id,
                            "approve_plan",
                            OWNER,
                            evidence,
                            expected_revision=4,
                            idempotency_key="approval:plan:expired",
                            approval_assertion=signed,
                        )


if __name__ == "__main__":
    unittest.main()
