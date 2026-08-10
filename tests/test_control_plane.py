from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from core.control_plane import (
    GENESIS_HASH,
    AuditIntegrityError,
    ControlPlane,
    ControlPlaneError,
    ControlPlanePaused,
    DatabaseVersionError,
    IdempotencyConflict,
    LeaseConflict,
    OutboxConflict,
)
from core.models import Actor, FeedbackEvent, WorkflowState
from core.policy import PermissionDenied
from core.schema_validation import validate_schema
from core.workflow import InvalidTransition


class FakeClock:
    def __init__(self, value: float = 1_786_334_400.0) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


def feedback(content: str = "Improve the mobile feedback card spacing.") -> FeedbackEvent:
    return FeedbackEvent(
        event_id="feedback-runtime-1",
        channel="test-im",
        message_id="message-runtime-1",
        received_at="2026-08-10T00:00:00Z",
        content=content,
        sender_ref="test-user",
    )


INTAKE = Actor("agent-intake", "public-intake")
OWNER = Actor("human-owner", "owner", kind="human")
ROOT = Path(__file__).resolve().parents[1]


class ControlPlanePersistenceTests(unittest.TestCase):
    def test_restart_preserves_lease_transition_and_idempotent_replay(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "state.sqlite3"
            clock = FakeClock()
            with ControlPlane(database, clock=clock) as control:
                created = control.ingest_feedback(feedback(), idempotency_key="feedback:runtime:1")
                repeated = control.ingest_feedback(feedback(), idempotency_key="feedback:runtime:1")
                self.assertFalse(created["replayed"])
                self.assertTrue(repeated["replayed"])
                work_id = created["work_item"]["id"]
                lease = control.acquire_lease(
                    work_id,
                    INTAKE,
                    expected_revision=0,
                    ttl_seconds=60,
                    idempotency_key="lease:normalize:1",
                )["lease"]

            with ControlPlane(database, create=False, clock=clock) as restarted:
                changed = restarted.apply_transition(
                    work_id,
                    "normalize",
                    INTAKE,
                    {"source": "feedback-runtime-1", "content_mode": "untrusted-data"},
                    expected_revision=0,
                    idempotency_key="transition:normalize:1",
                    lease_id=lease["lease_id"],
                )
                replay = restarted.apply_transition(
                    work_id,
                    "normalize",
                    INTAKE,
                    {"source": "feedback-runtime-1", "content_mode": "untrusted-data"},
                    expected_revision=0,
                    idempotency_key="transition:normalize:1",
                    lease_id=lease["lease_id"],
                )
                self.assertFalse(changed["replayed"])
                self.assertTrue(replay["replayed"])
                self.assertEqual(restarted.get_work_item(work_id).state, WorkflowState.NORMALIZED)
                self.assertTrue(restarted.verify_audit()["valid"])

    def test_two_processes_cannot_hold_the_same_work_item_lease(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "state.sqlite3"
            clock = FakeClock()
            with ControlPlane(database, clock=clock) as first:
                work_id = first.ingest_feedback(
                    feedback(), idempotency_key="feedback:concurrent:1"
                )["work_item"]["id"]
                first.acquire_lease(
                    work_id,
                    INTAKE,
                    expected_revision=0,
                    ttl_seconds=60,
                    idempotency_key="lease:concurrent:first",
                )
                with ControlPlane(database, create=False, clock=clock) as second:
                    with self.assertRaises(LeaseConflict):
                        second.acquire_lease(
                            work_id,
                            Actor("agent-intake-2", "public-intake"),
                            expected_revision=0,
                            ttl_seconds=60,
                            idempotency_key="lease:concurrent:second",
                        )

    def test_failed_transition_rolls_back_and_does_not_consume_idempotency_key(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "state.sqlite3"
            with ControlPlane(database) as control:
                work_id = control.ingest_feedback(
                    feedback(), idempotency_key="feedback:rollback:1"
                )["work_item"]["id"]
                lease = control.acquire_lease(
                    work_id,
                    INTAKE,
                    expected_revision=0,
                    ttl_seconds=60,
                    idempotency_key="lease:rollback:1",
                )["lease"]
                with self.assertRaises(InvalidTransition):
                    control.apply_transition(
                        work_id,
                        "open_pr",
                        INTAKE,
                        {"pull_request": "test://pr/1", "commit": "abc"},
                        expected_revision=0,
                        idempotency_key="transition:rollback:reusable",
                        lease_id=lease["lease_id"],
                    )
                self.assertEqual(control.get_work_item(work_id).revision, 0)
                changed = control.apply_transition(
                    work_id,
                    "normalize",
                    INTAKE,
                    {"source": "feedback-runtime-1"},
                    expected_revision=0,
                    idempotency_key="transition:rollback:reusable",
                    lease_id=lease["lease_id"],
                )
                self.assertEqual(changed["work_item"]["revision"], 1)

    def test_expired_lease_is_reconciled_before_reassignment(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            clock = FakeClock()
            with ControlPlane(Path(temporary) / "state.sqlite3", clock=clock) as control:
                work_id = control.ingest_feedback(feedback(), idempotency_key="feedback:expiry:1")[
                    "work_item"
                ]["id"]
                control.acquire_lease(
                    work_id,
                    INTAKE,
                    expected_revision=0,
                    ttl_seconds=10,
                    idempotency_key="lease:expiry:first",
                )
                clock.advance(11)
                self.assertEqual(control.reconcile()["expired_leases"], 1)
                replacement = control.acquire_lease(
                    work_id,
                    Actor("agent-intake-2", "public-intake"),
                    expected_revision=0,
                    ttl_seconds=10,
                    idempotency_key="lease:expiry:second",
                )
                self.assertEqual(replacement["lease"]["actor_id"], "agent-intake-2")

    def test_pause_blocks_new_transitions_and_resume_preserves_existing_lease(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            with ControlPlane(Path(temporary) / "state.sqlite3") as control:
                work_id = control.ingest_feedback(feedback(), idempotency_key="feedback:pause:1")[
                    "work_item"
                ]["id"]
                lease = control.acquire_lease(
                    work_id,
                    INTAKE,
                    expected_revision=0,
                    ttl_seconds=60,
                    idempotency_key="lease:pause:1",
                )["lease"]
                control.set_paused(
                    True, OWNER, reason="operator safety stop", idempotency_key="control:pause:1"
                )
                with self.assertRaises(ControlPlanePaused):
                    control.apply_transition(
                        work_id,
                        "normalize",
                        INTAKE,
                        {"source": "feedback-runtime-1"},
                        expected_revision=0,
                        idempotency_key="transition:pause:blocked",
                        lease_id=lease["lease_id"],
                    )
                control.set_paused(
                    False,
                    OWNER,
                    reason="operator reviewed state",
                    idempotency_key="control:resume:1",
                )
                result = control.apply_transition(
                    work_id,
                    "normalize",
                    INTAKE,
                    {"source": "feedback-runtime-1"},
                    expected_revision=0,
                    idempotency_key="transition:pause:blocked",
                    lease_id=lease["lease_id"],
                )
                self.assertEqual(result["work_item"]["state"], "NORMALIZED")

    def test_only_human_owner_can_change_global_pause(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            with ControlPlane(Path(temporary) / "state.sqlite3") as control:
                with self.assertRaises(PermissionDenied):
                    control.set_paused(
                        True,
                        Actor("agent-owner", "owner"),
                        reason="attempted impersonation",
                        idempotency_key="control:pause:impersonated",
                    )

    def test_same_feedback_source_with_changed_content_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            with ControlPlane(Path(temporary) / "state.sqlite3") as control:
                control.ingest_feedback(feedback(), idempotency_key="feedback:identity:first")
                with self.assertRaises(IdempotencyConflict):
                    control.ingest_feedback(
                        feedback("Different content with the same source identity."),
                        idempotency_key="feedback:identity:second",
                    )


class ControlPlaneOutboxTests(unittest.TestCase):
    def test_expired_claim_recovers_and_effect_completes_once(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            clock = FakeClock()
            database = Path(temporary) / "state.sqlite3"
            with ControlPlane(database, clock=clock) as control:
                created = control.ingest_feedback(feedback(), idempotency_key="feedback:outbox:1")
                work_id = created["work_item"]["id"]
                queued = control.queue_effect(
                    work_id,
                    authorization_event_sequence=created["audit_sequence"],
                    adapter_slot="code-hosting",
                    operation="issue.create",
                    payload={"title": "Normalized feedback", "body_ref": "work-item-summary"},
                    idempotency_key="effect:issue:create:1",
                    max_attempts=3,
                )
                repeated = control.queue_effect(
                    work_id,
                    authorization_event_sequence=created["audit_sequence"],
                    adapter_slot="code-hosting",
                    operation="issue.create",
                    payload={"title": "Normalized feedback", "body_ref": "work-item-summary"},
                    idempotency_key="effect:issue:create:1",
                    max_attempts=3,
                )
                self.assertTrue(repeated["replayed"])
                first_claim = control.claim_effect("worker-1", lease_seconds=10)
                self.assertEqual(first_claim["effect"]["effect_id"], queued["effect"]["effect_id"])

            clock.advance(11)
            with ControlPlane(database, create=False, clock=clock) as restarted:
                self.assertEqual(restarted.reconcile()["expired_effect_claims"], 1)
                second_claim = restarted.claim_effect("worker-2", lease_seconds=10)
                completed = restarted.complete_effect(
                    second_claim["effect"]["effect_id"],
                    "worker-2",
                    second_claim["effect"]["claim_token"],
                    {"external_ref": "test://issues/1", "status": "created"},
                )
                self.assertEqual(completed["effect"]["state"], "COMPLETED")
                self.assertEqual(completed["effect"]["attempts"], 2)
                self.assertIsNone(restarted.claim_effect("worker-3"))
                self.assertTrue(restarted.verify_audit()["valid"])

    def test_effect_reaches_dead_letter_after_bounded_attempts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            with ControlPlane(Path(temporary) / "state.sqlite3") as control:
                created = control.ingest_feedback(feedback(), idempotency_key="feedback:dead:1")
                work_id = created["work_item"]["id"]
                control.queue_effect(
                    work_id,
                    authorization_event_sequence=created["audit_sequence"],
                    adapter_slot="notification",
                    operation="feedback.notify",
                    payload={"work_item_id": work_id},
                    idempotency_key="effect:dead:1",
                    max_attempts=1,
                )
                claim = control.claim_effect("worker-dead")
                failed = control.fail_effect(
                    claim["effect"]["effect_id"],
                    "worker-dead",
                    claim["effect"]["claim_token"],
                    error="simulated provider failure",
                )
                self.assertEqual(failed["effect"]["state"], "DEAD")
                self.assertIsNone(control.claim_effect("worker-other"))

    def test_expired_effect_claim_cannot_acknowledge_after_lease_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            clock = FakeClock()
            with ControlPlane(Path(temporary) / "state.sqlite3", clock=clock) as control:
                created = control.ingest_feedback(
                    feedback(), idempotency_key="feedback:expired-ack:1"
                )
                work_id = created["work_item"]["id"]
                control.queue_effect(
                    work_id,
                    authorization_event_sequence=created["audit_sequence"],
                    adapter_slot="notification",
                    operation="feedback.notify",
                    payload={"work_item_id": work_id},
                    idempotency_key="effect:expired-ack:1",
                )
                claim = control.claim_effect("worker-expired", lease_seconds=10)["effect"]
                clock.advance(10)
                with self.assertRaises(OutboxConflict):
                    control.complete_effect(
                        claim["effect_id"],
                        "worker-expired",
                        claim["claim_token"],
                        {"status": "late"},
                    )
                self.assertEqual(control.reconcile()["expired_effect_claims"], 1)

    def test_outbox_rejects_non_finite_schedule(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            with ControlPlane(Path(temporary) / "state.sqlite3") as control:
                created = control.ingest_feedback(
                    feedback(), idempotency_key="feedback:nonfinite:1"
                )
                with self.assertRaises(ControlPlaneError):
                    control.queue_effect(
                        created["work_item"]["id"],
                        authorization_event_sequence=created["audit_sequence"],
                        adapter_slot="notification",
                        operation="feedback.notify",
                        payload={},
                        idempotency_key="effect:nonfinite:1",
                        available_at=float("nan"),
                    )

    def test_effect_requires_matching_durable_authority(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            with ControlPlane(Path(temporary) / "state.sqlite3") as control:
                created = control.ingest_feedback(
                    feedback(), idempotency_key="feedback:authority:1"
                )
                with self.assertRaises(OutboxConflict):
                    control.queue_effect(
                        created["work_item"]["id"],
                        authorization_event_sequence=9999,
                        adapter_slot="code-hosting",
                        operation="issue.create",
                        payload={},
                        idempotency_key="effect:authority:invalid",
                    )

    def test_runtime_rejects_inline_secrets_before_persistence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            with ControlPlane(Path(temporary) / "state.sqlite3") as control:
                created = control.ingest_feedback(feedback(), idempotency_key="feedback:secret:1")
                work_id = created["work_item"]["id"]
                with self.assertRaises(ControlPlaneError):
                    control.queue_effect(
                        work_id,
                        authorization_event_sequence=created["audit_sequence"],
                        adapter_slot="code-hosting",
                        operation="issue.create",
                        payload={"access_token": "not-allowed"},
                        idempotency_key="effect:secret:1",
                    )
                lease = control.acquire_lease(
                    work_id,
                    INTAKE,
                    expected_revision=0,
                    ttl_seconds=60,
                    idempotency_key="lease:secret:1",
                )["lease"]
                with self.assertRaises(ControlPlaneError):
                    control.apply_transition(
                        work_id,
                        "normalize",
                        INTAKE,
                        {"provider_token": "not-allowed"},
                        expected_revision=0,
                        idempotency_key="transition:secret:1",
                        lease_id=lease["lease_id"],
                    )

    def test_exact_effect_replay_is_available_during_pause(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            with ControlPlane(Path(temporary) / "state.sqlite3") as control:
                created = control.ingest_feedback(
                    feedback(), idempotency_key="feedback:paused-effect:1"
                )
                work_id = created["work_item"]["id"]
                first = control.queue_effect(
                    work_id,
                    authorization_event_sequence=created["audit_sequence"],
                    adapter_slot="notification",
                    operation="feedback.received",
                    payload={"work_item_id": work_id},
                    idempotency_key="effect:paused-replay:1",
                )
                control.set_paused(
                    True,
                    OWNER,
                    reason="operator safety stop",
                    idempotency_key="control:pause:effect-replay",
                )
                replay = control.queue_effect(
                    work_id,
                    authorization_event_sequence=created["audit_sequence"],
                    adapter_slot="notification",
                    operation="feedback.received",
                    payload={"work_item_id": work_id},
                    idempotency_key="effect:paused-replay:1",
                )
                self.assertTrue(replay["replayed"])
                self.assertEqual(replay["effect"]["effect_id"], first["effect"]["effect_id"])
                with self.assertRaises(ControlPlanePaused):
                    control.queue_effect(
                        work_id,
                        authorization_event_sequence=created["audit_sequence"],
                        adapter_slot="notification",
                        operation="feedback.changed",
                        payload={"work_item_id": work_id},
                        idempotency_key="effect:paused-new:1",
                    )


class ControlPlaneRecoveryTests(unittest.TestCase):
    def test_public_runtime_objects_match_open_contract_schemas(self) -> None:
        schemas = {
            name: json.loads((ROOT / "schemas" / name).read_text(encoding="utf-8"))
            for name in (
                "control-plane-audit.schema.json",
                "control-plane-status.schema.json",
                "outbox-effect.schema.json",
                "task-lease.schema.json",
            )
        }
        with tempfile.TemporaryDirectory() as temporary:
            with ControlPlane(Path(temporary) / "state.sqlite3") as control:
                created = control.ingest_feedback(
                    feedback(), idempotency_key="feedback:contracts:1"
                )
                work_id = created["work_item"]["id"]
                lease = control.acquire_lease(
                    work_id,
                    INTAKE,
                    expected_revision=0,
                    ttl_seconds=60,
                    idempotency_key="lease:contracts:1",
                )["lease"]
                effect = control.queue_effect(
                    work_id,
                    authorization_event_sequence=created["audit_sequence"],
                    adapter_slot="notification",
                    operation="feedback.received",
                    payload={"work_item_id": work_id},
                    idempotency_key="effect:contracts:1",
                )["effect"]
                audit_payload = json.loads(
                    control.connection.execute(
                        "SELECT payload_json FROM audit_log WHERE sequence = 1"
                    ).fetchone()[0]
                )
                self.assertEqual(
                    validate_schema(audit_payload, schemas["control-plane-audit.schema.json"]),
                    [],
                )
                self.assertEqual(
                    validate_schema(control.status(), schemas["control-plane-status.schema.json"]),
                    [],
                )
                self.assertEqual(
                    validate_schema(effect, schemas["outbox-effect.schema.json"]),
                    [],
                )
                self.assertEqual(
                    validate_schema(lease, schemas["task-lease.schema.json"]),
                    [],
                )

    def test_audit_hash_chain_detects_tampering(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "state.sqlite3"
            with ControlPlane(database) as control:
                control.ingest_feedback(feedback(), idempotency_key="feedback:audit:1")
                control.connection.execute(
                    "UPDATE audit_log SET payload_json = ? WHERE sequence = 1",
                    ('{"tampered":true}',),
                )
                with self.assertRaises(AuditIntegrityError):
                    control.verify_audit()

    def test_audit_rejects_duplicate_keys_even_with_a_recomputed_hash(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "state.sqlite3"
            with ControlPlane(database) as control:
                control.ingest_feedback(
                    feedback(), idempotency_key="feedback:audit:duplicate-key:1"
                )
                original = str(
                    control.connection.execute(
                        "SELECT payload_json FROM audit_log WHERE sequence = 1"
                    ).fetchone()[0]
                )
                duplicated = original[:-1] + ',"data":{}}'
                event_hash = (
                    "sha256:"
                    + hashlib.sha256((GENESIS_HASH + "\n" + duplicated).encode("utf-8")).hexdigest()
                )
                control.connection.execute(
                    "UPDATE audit_log SET payload_json = ?, event_hash = ? WHERE sequence = 1",
                    (duplicated, event_hash),
                )
                with self.assertRaises(AuditIntegrityError):
                    control.verify_audit()

    def test_audit_hash_chain_detects_index_column_tampering(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "state.sqlite3"
            with ControlPlane(database) as control:
                control.ingest_feedback(feedback(), idempotency_key="feedback:audit:index:1")
                control.connection.execute(
                    "UPDATE audit_log SET event_kind = ? WHERE sequence = 1",
                    ("tampered.event",),
                )
                with self.assertRaises(AuditIntegrityError):
                    control.verify_audit()

    def test_audit_verification_detects_missing_creation_event(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "state.sqlite3"
            with ControlPlane(database) as control:
                control.ingest_feedback(feedback(), idempotency_key="feedback:audit:missing:1")
                control.connection.execute("DELETE FROM audit_log WHERE sequence = 1")
                with self.assertRaises(AuditIntegrityError):
                    control.verify_audit()

    def test_audit_verification_detects_work_item_state_index_tampering(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "state.sqlite3"
            with ControlPlane(database) as control:
                control.ingest_feedback(feedback(), idempotency_key="feedback:state:index:1")
                control.connection.execute(
                    "UPDATE work_items SET state = 'CLOSED' WHERE revision = 0"
                )
                with self.assertRaises(AuditIntegrityError):
                    control.verify_audit()

    def test_runtime_database_is_owner_only(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "state.sqlite3"
            with ControlPlane(database):
                pass
            self.assertEqual(database.stat().st_mode & 0o077, 0)

    def test_backup_and_non_overwriting_restore_preserve_audit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            database = base / "state.sqlite3"
            backup = base / "backups" / "state-backup.sqlite3"
            restored = base / "restored" / "state.sqlite3"
            with ControlPlane(database) as control:
                control.ingest_feedback(feedback(), idempotency_key="feedback:backup:1")
                original_audit = control.verify_audit()
                backup_report = control.backup(backup)
                self.assertEqual(backup_report["audit"], original_audit)
            restore_report = ControlPlane.restore(backup, restored)
            self.assertEqual(restore_report["audit"], original_audit)
            with ControlPlane(restored, create=False) as recovered:
                self.assertEqual(recovered.verify_audit(), original_audit)
            with self.assertRaises(ControlPlaneError):
                ControlPlane.restore(backup, restored)

    def test_unknown_database_schema_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "future.sqlite3"
            connection = sqlite3.connect(database)
            connection.execute("PRAGMA user_version = 99")
            connection.close()
            database.chmod(0o600)
            with self.assertRaises(DatabaseVersionError):
                ControlPlane(database, create=False)


if __name__ == "__main__":
    unittest.main()
