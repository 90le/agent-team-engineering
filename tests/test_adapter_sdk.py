from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from core.adapters import (
    AdapterCatalogError,
    AdapterClaimExpired,
    AdapterDisabled,
    AdapterHost,
    AdapterOperationDenied,
    AdapterWorker,
    MappingSecretResolver,
    load_adapter_catalog,
)
from core.approval import HMACApprovalVerifier, issue_hmac_assertion
from core.control_plane import ControlPlane
from core.models import Actor, FeedbackEvent
from core.reference_adapters import (
    GitHubReferenceAdapter,
    LocalDryRunRunnerAdapter,
    RecordingAdapter,
)

ROOT = Path(__file__).resolve().parents[1]
APPROVAL_KEY = b"adapter-test-approval-key-material-32-bytes"
APPROVAL_PROVIDER = "approval-provider.adapter-test"


class FakeClock:
    def __init__(self, value: float = 1_786_334_400.0) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


def instance_with_binding(
    slot: str,
    adapter_id: str,
    *,
    secret_refs: list[str] | None = None,
) -> dict:
    instance = json.loads(
        (ROOT / "examples/team-instance/input/instance.json").read_text(encoding="utf-8")
    )
    instance["adapters"] = [binding for binding in instance["adapters"] if binding["slot"] != slot]
    instance["adapters"].append(
        {
            "slot": slot,
            "adapter_id": adapter_id,
            "enabled": True,
            "config": {},
            "secret_refs": secret_refs or [],
        }
    )
    if slot in {"code-hosting", "model", "runner"}:
        instance["projects"] = [
            {
                "id": "project.example",
                "provider": "github",
                "locator": "owner/repo",
                "default_branch": "main",
                "mode": "proposal-only",
            }
        ]
    return instance


def feedback() -> FeedbackEvent:
    return FeedbackEvent(
        event_id="feedback-adapter-1",
        channel="test-im",
        message_id="message-adapter-1",
        received_at="2026-08-10T00:00:00Z",
        content="Notify the user about accepted feedback.",
        sender_ref="test-user",
    )


def queue_notification(control: ControlPlane, *, max_attempts: int = 3) -> dict:
    created = control.ingest_feedback(feedback(), idempotency_key="adapter:feedback:1")
    work_id = created["work_item"]["id"]
    return control.queue_effect(
        work_id,
        authorization_event_sequence=created["audit_sequence"],
        adapter_slot="notification",
        operation="feedback.notify",
        payload={
            "work_item_id": work_id,
            "status": "received",
            "message_ref": "feedback-message-1",
        },
        idempotency_key="adapter:notification:1",
        max_attempts=max_attempts,
    )["effect"]


def advance_to_open_pr(control: ControlPlane, clock: FakeClock, work_id: str) -> int:
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
            {"spec_id": "spec-runner-1", "acceptance_count": "1"},
        ),
    )
    for revision, (action, actor, evidence) in enumerate(steps):
        lease = control.acquire_lease(
            work_id,
            actor,
            expected_revision=revision,
            ttl_seconds=60,
            idempotency_key=f"adapter:runner:lease:{revision}",
        )["lease"]
        control.apply_transition(
            work_id,
            action,
            actor,
            evidence,
            expected_revision=revision,
            idempotency_key=f"adapter:runner:transition:{revision}",
            lease_id=lease["lease_id"],
        )

    owner = Actor("human.project-owner", "owner", kind="human")
    approval_evidence = {
        "approval_id": "approval-runner-plan-1",
        "scope_hash": "sha256:" + ("a" * 64),
    }
    signed = issue_hmac_assertion(
        key=APPROVAL_KEY,
        provider=APPROVAL_PROVIDER,
        assertion_id=approval_evidence["approval_id"],
        subject=owner.id,
        action="approve_plan",
        work_item_id=work_id,
        expected_revision=4,
        evidence=approval_evidence,
        issued_at_epoch=clock(),
        expires_at_epoch=clock() + 300,
        nonce="nonce-adapter-runner-0001",
        evidence_ref="test-approval://runner/plan-1",
    )
    control.apply_transition(
        work_id,
        "approve_plan",
        owner,
        approval_evidence,
        expected_revision=4,
        idempotency_key="adapter:runner:approve-plan",
        approval_assertion=signed,
    )
    builder = Actor("agent-builder", "builder")
    for revision, action, evidence in (
        (
            5,
            "start_implementation",
            {"workspace": "workspace-runner-1", "branch": "agent/test/work"},
        ),
        (
            6,
            "open_pr",
            {"pull_request": "test://pull/1", "commit": "a" * 40},
        ),
    ):
        lease = control.acquire_lease(
            work_id,
            builder,
            expected_revision=revision,
            ttl_seconds=60,
            idempotency_key=f"adapter:runner:builder-lease:{revision}",
        )["lease"]
        result = control.apply_transition(
            work_id,
            action,
            builder,
            evidence,
            expected_revision=revision,
            idempotency_key=f"adapter:runner:builder-transition:{revision}",
            lease_id=lease["lease_id"],
        )
    return int(result["audit_sequence"])


def execution_payload(work_id: str) -> dict:
    return {
        "schema_version": "1.0.0",
        "job_id": "job-test-1",
        "work_item_id": work_id,
        "project_id": "project.example",
        "source_ref": "project-source:project.example@main",
        "commit": "a" * 40,
        "command_id": "test",
        "arguments": ["--offline"],
        "workspace_id": "workspace-test-1",
        "timeout_seconds": 60,
        "network_policy": "none",
        "network_allowlist": [],
        "secret_refs": [],
        "source_read_only": True,
        "workspace_ephemeral": True,
        "production_mounts": False,
        "docker_socket": False,
        "privileged": False,
    }


class AdapterCatalogTests(unittest.TestCase):
    def test_catalog_has_versioned_operations_and_safe_schema_refs(self) -> None:
        catalog = load_adapter_catalog()
        self.assertGreaterEqual(len(catalog), 9)
        self.assertEqual(catalog["adapter.github"].version, "0.8.0")
        self.assertEqual(
            catalog["adapter.github"].operations["issue.create"].delivery,
            "reconcile-before-retry",
        )
        self.assertEqual(
            catalog["adapter.local-dry-run"].implementation_mode,
            "python-reference",
        )
        self.assertNotIn("pull-request.merge", catalog["adapter.github"].operations)
        self.assertNotIn("branch.push-default", catalog["adapter.github"].operations)

    def test_disabled_binding_cannot_dispatch(self) -> None:
        instance = instance_with_binding("notification", "adapter.recording")
        instance["adapters"][-1]["enabled"] = False
        host = AdapterHost(instance, [RecordingAdapter()])
        with tempfile.TemporaryDirectory() as temporary:
            with ControlPlane(Path(temporary) / "state.sqlite3") as control:
                queue_notification(control)
                effect = control.claim_effect("worker-disabled")["effect"]
                with self.assertRaises(AdapterDisabled):
                    host.dispatch(
                        effect,
                        control.get_audit_event(effect["authorization_event_sequence"]),
                    )

    def test_host_rejects_non_json_instance_configuration(self) -> None:
        instance = instance_with_binding("notification", "adapter.recording")
        instance["adapters"][-1]["config"] = {"not_json": float("nan")}
        with self.assertRaises(AdapterCatalogError):
            AdapterHost(instance, [RecordingAdapter()])

    def test_binding_configuration_must_match_manifest_schema(self) -> None:
        instance = instance_with_binding("notification", "adapter.recording")
        instance["adapters"][-1]["config"] = {"undeclared_option": True}
        with self.assertRaises(AdapterCatalogError):
            AdapterHost(instance, [RecordingAdapter()])

    def test_operation_cannot_cross_between_adapter_slots(self) -> None:
        class OpenClawProbe:
            adapter_id = "adapter.openclaw"

            def execute(self, request: dict, context: object) -> dict:
                del request, context
                raise AssertionError("wrong-slot operation must not execute")

            def reconcile(self, request: dict, context: object) -> None:
                del request, context
                return None

        instance = instance_with_binding(
            "intake",
            "adapter.openclaw",
            secret_refs=["secret.openclaw-intake"],
        )
        host = AdapterHost(instance, [OpenClawProbe()])
        with tempfile.TemporaryDirectory() as temporary:
            with ControlPlane(Path(temporary) / "state.sqlite3") as control:
                created = control.ingest_feedback(
                    feedback(), idempotency_key="adapter:wrong-slot:feedback:1"
                )
                work_id = created["work_item"]["id"]
                control.queue_effect(
                    work_id,
                    authorization_event_sequence=created["audit_sequence"],
                    adapter_slot="intake",
                    operation="feedback.notify",
                    payload={
                        "work_item_id": work_id,
                        "status": "received",
                        "message_ref": "wrong-slot",
                    },
                    idempotency_key="adapter:wrong-slot:effect:1",
                )
                result = AdapterWorker(control, host, "worker-wrong-slot").run_once()
                self.assertEqual(result["effect"]["state"], "DEAD")
                self.assertEqual(result["effect"]["last_error"], "ADAPTER_OPERATION_DENIED")


class AdapterWorkerTests(unittest.TestCase):
    def test_expired_claim_cannot_start_an_external_operation(self) -> None:
        instance = instance_with_binding("notification", "adapter.recording")
        adapter = RecordingAdapter()
        clock = FakeClock()
        host = AdapterHost(instance, [adapter], clock=clock)
        with tempfile.TemporaryDirectory() as temporary:
            with ControlPlane(Path(temporary) / "state.sqlite3", clock=clock) as control:
                queue_notification(control)
                effect = control.claim_effect("worker-stale", lease_seconds=10)["effect"]
                clock.advance(11)
                with self.assertRaises(AdapterClaimExpired):
                    host.dispatch(
                        effect,
                        control.get_audit_event(effect["authorization_event_sequence"]),
                    )
                self.assertEqual(adapter.execute_count, 0)
                self.assertEqual(control.reconcile()["expired_effect_claims"], 1)
                self.assertEqual(control.get_effect(effect["effect_id"])["state"], "FAILED")

    def test_worker_reconciles_a_claim_that_expires_before_dispatch(self) -> None:
        class DelayedHost(AdapterHost):
            def dispatch(self, effect: dict, authorization_event: dict) -> dict:
                clock.advance(11)
                return super().dispatch(effect, authorization_event)

        instance = instance_with_binding("notification", "adapter.recording")
        adapter = RecordingAdapter()
        clock = FakeClock()
        host = DelayedHost(instance, [adapter], clock=clock)
        with tempfile.TemporaryDirectory() as temporary:
            with ControlPlane(Path(temporary) / "state.sqlite3", clock=clock) as control:
                queue_notification(control)
                result = AdapterWorker(
                    control,
                    host,
                    "worker-expiring",
                    lease_seconds=10,
                ).run_once()
                self.assertEqual(result["error"], "ADAPTER_CLAIM_EXPIRED")
                self.assertEqual(result["effect"]["state"], "FAILED")
                self.assertEqual(adapter.execute_count, 0)

    def test_worker_completes_schema_valid_recording_effect(self) -> None:
        instance = instance_with_binding("notification", "adapter.recording")
        adapter = RecordingAdapter()
        host = AdapterHost(instance, [adapter])
        with tempfile.TemporaryDirectory() as temporary:
            with ControlPlane(Path(temporary) / "state.sqlite3") as control:
                queue_notification(control)
                result = AdapterWorker(control, host, "worker-recording").run_once()
                self.assertEqual(result["effect"]["state"], "COMPLETED")
                self.assertEqual(adapter.execute_count, 1)
                self.assertTrue(control.verify_audit()["valid"])

    def test_provider_success_before_crash_is_reconciled_without_duplicate_write(self) -> None:
        instance = instance_with_binding("notification", "adapter.recording")
        adapter = RecordingAdapter()
        clock = FakeClock()
        host = AdapterHost(instance, [adapter], clock=clock)
        with tempfile.TemporaryDirectory() as temporary:
            with ControlPlane(Path(temporary) / "state.sqlite3", clock=clock) as control:
                queue_notification(control)
                crashed_claim = control.claim_effect("worker-crashed", lease_seconds=10)["effect"]
                provider_result = host.dispatch(
                    crashed_claim,
                    control.get_audit_event(crashed_claim["authorization_event_sequence"]),
                )
                self.assertEqual(provider_result["status"], "SUCCEEDED")
                self.assertEqual(adapter.execute_count, 1)

                clock.advance(11)
                self.assertEqual(control.reconcile()["expired_effect_claims"], 1)
                recovered = AdapterWorker(control, host, "worker-recovery").run_once()
                self.assertEqual(recovered["effect"]["state"], "COMPLETED")
                self.assertEqual(adapter.execute_count, 1)
                self.assertEqual(adapter.reconcile_count, 1)
                self.assertTrue(recovered["effect"]["result"]["reconciled"])

    def test_contract_violation_is_dead_lettered_without_secret_persistence(self) -> None:
        class LeakingAdapter:
            adapter_id = "adapter.recording"

            def execute(self, request: dict, context: object) -> dict:
                del request, context
                return {
                    "schema_version": "1.0.0",
                    "status": "SUCCEEDED",
                    "output": {
                        "external_ref": "recording://bad",
                        "provider_request_id": "bad-request",
                        "state": "reported",
                        "access_token": "must-not-persist",
                    },
                    "external_ref": "recording://bad",
                    "provider_request_id": "bad-request",
                    "reconciled": False,
                    "error_code": None,
                }

            def reconcile(self, request: dict, context: object) -> None:
                del request, context
                return None

        instance = instance_with_binding("notification", "adapter.recording")
        host = AdapterHost(instance, [LeakingAdapter()])
        with tempfile.TemporaryDirectory() as temporary:
            with ControlPlane(Path(temporary) / "state.sqlite3") as control:
                queue_notification(control)
                result = AdapterWorker(control, host, "worker-leak").run_once()
                self.assertEqual(result["effect"]["state"], "DEAD")
                self.assertEqual(result["effect"]["last_error"], "ADAPTER_CONTRACT_INVALID")
                database_files = sorted(Path(temporary).glob("state.sqlite3*"))
                self.assertTrue(database_files)
                for database_file in database_files:
                    self.assertNotIn(
                        b"must-not-persist",
                        database_file.read_bytes(),
                        database_file.name,
                    )

    def test_unexpected_adapter_exception_is_sanitized_before_persistence(self) -> None:
        class ExplodingAdapter:
            adapter_id = "adapter.recording"

            def execute(self, request: dict, context: object) -> dict:
                del request, context
                raise RuntimeError("provider response contained sensitive-value-123")

            def reconcile(self, request: dict, context: object) -> None:
                del request, context
                return None

        instance = instance_with_binding("notification", "adapter.recording")
        host = AdapterHost(instance, [ExplodingAdapter()])
        with tempfile.TemporaryDirectory() as temporary:
            with ControlPlane(Path(temporary) / "state.sqlite3") as control:
                queue_notification(control)
                result = AdapterWorker(control, host, "worker-exploding").run_once()
                self.assertEqual(result["effect"]["state"], "FAILED")
                self.assertEqual(result["effect"]["last_error"], "ADAPTER_UNEXPECTED_FAILURE")
                for database_file in sorted(Path(temporary).glob("state.sqlite3*")):
                    self.assertNotIn(
                        b"sensitive-value-123",
                        database_file.read_bytes(),
                        database_file.name,
                    )

    def test_at_most_once_contract_refuses_multi_attempt_effect(self) -> None:
        class ModelAdapter:
            adapter_id = "adapter.manual-agent"

            def execute(self, request: dict, context: object) -> dict:
                raise AssertionError("must not execute")

            def reconcile(self, request: dict, context: object) -> None:
                return None

        instance = instance_with_binding("model", "adapter.manual-agent")
        host = AdapterHost(instance, [ModelAdapter()])
        task = {
            "task_id": "task-at-most-once",
            "work_item_id": "work-placeholder",
            "project_id": "project.example",
            "role": "builder",
            "expected_revision": 0,
            "idempotency_key": "model:task:1",
            "context": {
                "framework_commit": "a" * 40,
                "project_commit": "b" * 40,
                "paths": ["README.md"],
            },
            "allowed_capabilities": ["implementation.start"],
            "budget": {"max_attempts": 1, "max_seconds": 60, "max_cost_units": 1},
        }
        with tempfile.TemporaryDirectory() as temporary:
            with ControlPlane(Path(temporary) / "state.sqlite3") as control:
                created = control.ingest_feedback(
                    feedback(), idempotency_key="adapter:model:feedback:1"
                )
                task["work_item_id"] = created["work_item"]["id"]
                control.queue_effect(
                    task["work_item_id"],
                    authorization_event_sequence=created["audit_sequence"],
                    adapter_slot="model",
                    operation="agent.invoke",
                    payload=task,
                    idempotency_key="adapter:model:effect:1",
                    max_attempts=2,
                )
                effect = control.claim_effect("worker-model")["effect"]
                with self.assertRaises(AdapterOperationDenied):
                    host.dispatch(
                        effect,
                        control.get_audit_event(effect["authorization_event_sequence"]),
                    )


class GitHubReferenceAdapterTests(unittest.TestCase):
    def test_adapter_cannot_resolve_a_secret_outside_its_instance_binding(self) -> None:
        class SecretProbeAdapter:
            adapter_id = "adapter.github"

            def execute(self, request: dict, context: object) -> dict:
                del request
                context.resolve_secret("secret.outside-binding")
                raise AssertionError("secret scope must fail before this line")

            def reconcile(self, request: dict, context: object) -> None:
                del request, context
                return None

        instance = instance_with_binding(
            "code-hosting",
            "adapter.github",
            secret_refs=["secret.github-app"],
        )
        secret_value = b"outside-binding-value-must-not-persist"
        host = AdapterHost(
            instance,
            [SecretProbeAdapter()],
            secret_resolver=MappingSecretResolver(
                {
                    "secret.github-app": b"allowed-but-unused",
                    "secret.outside-binding": secret_value,
                }
            ),
        )
        with tempfile.TemporaryDirectory() as temporary:
            with ControlPlane(Path(temporary) / "state.sqlite3") as control:
                created = control.ingest_feedback(
                    feedback(), idempotency_key="adapter:secret-scope:feedback:1"
                )
                work_id = created["work_item"]["id"]
                control.queue_effect(
                    work_id,
                    authorization_event_sequence=created["audit_sequence"],
                    adapter_slot="code-hosting",
                    operation="issue.create",
                    payload={
                        "repository": "owner/repo",
                        "work_item_id": work_id,
                        "title": "Secret scope test",
                        "body": "No secret value belongs here.",
                    },
                    idempotency_key="adapter:secret-scope:effect:1",
                )
                result = AdapterWorker(control, host, "worker-secret-scope").run_once()
                self.assertEqual(result["effect"]["state"], "DEAD")
                self.assertEqual(result["effect"]["last_error"], "ADAPTER_OPERATION_DENIED")
                for database_file in sorted(Path(temporary).glob("state.sqlite3*")):
                    self.assertNotIn(secret_value, database_file.read_bytes())

    def test_issue_mapping_and_retry_reconciliation_do_not_duplicate_provider_write(self) -> None:
        class MemoryTransport:
            def __init__(self) -> None:
                self.created: list[dict] = []
                self.lookup_count = 0

            def create(self, operation: str, path: str, payload: dict) -> dict:
                record = {
                    "operation": operation,
                    "path": path,
                    "payload": payload,
                    "html_url": "https://github.example/owner/repo/issues/1",
                    "request_id": "github-request-1",
                }
                self.created.append(record)
                return record

            def find_by_marker(self, operation: str, repository: str, marker: str) -> dict | None:
                self.lookup_count += 1
                for record in self.created:
                    if (
                        record["operation"] == operation
                        and repository == "owner/repo"
                        and marker in record["payload"]["body"]
                    ):
                        return record
                return None

        instance = instance_with_binding(
            "code-hosting",
            "adapter.github",
            secret_refs=["secret.github-app"],
        )
        transport = MemoryTransport()
        adapter = GitHubReferenceAdapter(transport)
        clock = FakeClock()
        host = AdapterHost(instance, [adapter], clock=clock)
        with tempfile.TemporaryDirectory() as temporary:
            with ControlPlane(Path(temporary) / "state.sqlite3", clock=clock) as control:
                created = control.ingest_feedback(
                    feedback(), idempotency_key="adapter:github:feedback:1"
                )
                work_id = created["work_item"]["id"]
                control.queue_effect(
                    work_id,
                    authorization_event_sequence=created["audit_sequence"],
                    adapter_slot="code-hosting",
                    operation="issue.create",
                    payload={
                        "repository": "owner/repo",
                        "work_item_id": work_id,
                        "title": "Normalized feedback",
                        "body": "Created from a governed work item.",
                    },
                    idempotency_key="adapter:github:issue:1",
                )
                crashed = control.claim_effect("worker-github-crashed", lease_seconds=10)["effect"]
                host.dispatch(
                    crashed,
                    control.get_audit_event(crashed["authorization_event_sequence"]),
                )
                self.assertEqual(len(transport.created), 1)
                self.assertEqual(transport.created[0]["path"], "/repos/owner/repo/issues")
                self.assertIn("agent-team-effect", transport.created[0]["payload"]["body"])

                clock.advance(11)
                control.reconcile()
                result = AdapterWorker(control, host, "worker-github-recovery").run_once()
                self.assertEqual(result["effect"]["state"], "COMPLETED")
                self.assertEqual(len(transport.created), 1)
                self.assertEqual(transport.lookup_count, 1)
                self.assertTrue(result["effect"]["result"]["reconciled"])

    def test_github_write_cannot_target_an_undeclared_repository(self) -> None:
        class NoWriteTransport:
            def create(self, operation: str, path: str, payload: dict) -> dict:
                del operation, path, payload
                raise AssertionError("undeclared repository must not reach transport")

            def find_by_marker(self, operation: str, repository: str, marker: str) -> None:
                del operation, repository, marker
                return None

        instance = instance_with_binding(
            "code-hosting",
            "adapter.github",
            secret_refs=["secret.github-app"],
        )
        host = AdapterHost(instance, [GitHubReferenceAdapter(NoWriteTransport())])
        with tempfile.TemporaryDirectory() as temporary:
            with ControlPlane(Path(temporary) / "state.sqlite3") as control:
                created = control.ingest_feedback(
                    feedback(), idempotency_key="adapter:github:scope-feedback:1"
                )
                work_id = created["work_item"]["id"]
                control.queue_effect(
                    work_id,
                    authorization_event_sequence=created["audit_sequence"],
                    adapter_slot="code-hosting",
                    operation="issue.create",
                    payload={
                        "repository": "owner/undeclared",
                        "work_item_id": work_id,
                        "title": "Must be denied",
                        "body": "The instance does not own this target.",
                    },
                    idempotency_key="adapter:github:scope-effect:1",
                )
                result = AdapterWorker(control, host, "worker-github-scope").run_once()
                self.assertEqual(result["effect"]["state"], "DEAD")
                self.assertEqual(result["effect"]["last_error"], "ADAPTER_OPERATION_DENIED")

    def test_draft_pull_request_mapping_is_bound_to_the_default_branch(self) -> None:
        class PullTransport:
            def __init__(self) -> None:
                self.created: list[dict] = []

            def create(self, operation: str, path: str, payload: dict) -> dict:
                record = {
                    "operation": operation,
                    "path": path,
                    "payload": payload,
                    "html_url": "https://github.example/owner/repo/pull/1",
                    "request_id": "github-pull-request-1",
                }
                self.created.append(record)
                return record

            def find_by_marker(self, operation: str, repository: str, marker: str) -> None:
                del operation, repository, marker
                return None

        instance = instance_with_binding(
            "code-hosting",
            "adapter.github",
            secret_refs=["secret.github-app"],
        )
        transport = PullTransport()
        clock = FakeClock()
        host = AdapterHost(instance, [GitHubReferenceAdapter(transport)], clock=clock)
        with tempfile.TemporaryDirectory() as temporary:
            verifier = HMACApprovalVerifier(APPROVAL_PROVIDER, APPROVAL_KEY, clock=clock)
            with ControlPlane(
                Path(temporary) / "state.sqlite3",
                clock=clock,
                approval_verifier=verifier,
            ) as control:
                created = control.ingest_feedback(
                    feedback(), idempotency_key="adapter:github:pr-feedback:1"
                )
                work_id = created["work_item"]["id"]
                last_sequence = advance_to_open_pr(control, clock, work_id)
                implementation_sequence = next(
                    sequence
                    for sequence in range(1, last_sequence + 1)
                    if (
                        (event := control.get_audit_event(sequence))["event_kind"]
                        == "workflow.transition"
                        and event["data"]["transition"]["action"] == "start_implementation"
                    )
                )
                base_payload = {
                    "repository": "owner/repo",
                    "work_item_id": work_id,
                    "title": "Governed draft",
                    "body": "Created from the approved implementation transition.",
                    "head": "agent/work-item",
                    "base": "main",
                    "draft": True,
                }
                control.queue_effect(
                    work_id,
                    authorization_event_sequence=implementation_sequence,
                    adapter_slot="code-hosting",
                    operation="pull-request.create",
                    payload=base_payload,
                    idempotency_key="adapter:github:pr-effect:1",
                )
                completed = AdapterWorker(control, host, "worker-github-pr").run_once()
                self.assertEqual(completed["effect"]["state"], "COMPLETED")
                self.assertEqual(transport.created[0]["path"], "/repos/owner/repo/pulls")
                self.assertTrue(transport.created[0]["payload"]["draft"])

                control.queue_effect(
                    work_id,
                    authorization_event_sequence=implementation_sequence,
                    adapter_slot="code-hosting",
                    operation="pull-request.create",
                    payload={**base_payload, "base": "unreviewed-branch"},
                    idempotency_key="adapter:github:pr-effect:wrong-base",
                )
                denied = AdapterWorker(control, host, "worker-github-pr-base").run_once()
                self.assertEqual(denied["effect"]["state"], "DEAD")
                self.assertEqual(denied["effect"]["last_error"], "ADAPTER_OPERATION_DENIED")
                self.assertEqual(len(transport.created), 1)


class DryRunRunnerTests(unittest.TestCase):
    def test_runner_effect_without_open_pr_authority_is_dead_lettered(self) -> None:
        instance = instance_with_binding("runner", "adapter.local-dry-run")
        adapter = LocalDryRunRunnerAdapter(allowed_command_ids=("test",))
        host = AdapterHost(instance, [adapter])
        with tempfile.TemporaryDirectory() as temporary:
            with ControlPlane(Path(temporary) / "state.sqlite3") as control:
                created = control.ingest_feedback(
                    feedback(), idempotency_key="adapter:runner:unauthorized-feedback:1"
                )
                work_id = created["work_item"]["id"]
                control.queue_effect(
                    work_id,
                    authorization_event_sequence=created["audit_sequence"],
                    adapter_slot="runner",
                    operation="runner.execute",
                    payload=execution_payload(work_id),
                    idempotency_key="adapter:runner:unauthorized-effect:1",
                )
                result = AdapterWorker(control, host, "worker-unauthorized").run_once()
                self.assertEqual(result["effect"]["state"], "DEAD")
                self.assertEqual(result["effect"]["last_error"], "ADAPTER_OPERATION_DENIED")
                self.assertEqual(adapter.execute_count, 0)

    def test_runner_source_must_match_the_declared_project(self) -> None:
        instance = instance_with_binding("runner", "adapter.local-dry-run")
        adapter = LocalDryRunRunnerAdapter(allowed_command_ids=("test",))
        clock = FakeClock()
        host = AdapterHost(instance, [adapter], clock=clock)
        with tempfile.TemporaryDirectory() as temporary:
            verifier = HMACApprovalVerifier(APPROVAL_PROVIDER, APPROVAL_KEY, clock=clock)
            with ControlPlane(
                Path(temporary) / "state.sqlite3",
                clock=clock,
                approval_verifier=verifier,
            ) as control:
                created = control.ingest_feedback(
                    feedback(), idempotency_key="adapter:runner:scope-feedback:1"
                )
                execution = execution_payload(created["work_item"]["id"])
                execution["source_ref"] = "project-source:project.other@main"
                authorization_sequence = advance_to_open_pr(
                    control, clock, execution["work_item_id"]
                )
                control.queue_effect(
                    execution["work_item_id"],
                    authorization_event_sequence=authorization_sequence,
                    adapter_slot="runner",
                    operation="runner.execute",
                    payload=execution,
                    idempotency_key="adapter:runner:scope-effect:1",
                )
                result = AdapterWorker(control, host, "worker-runner-scope").run_once()
                self.assertEqual(result["effect"]["state"], "DEAD")
                self.assertEqual(result["effect"]["last_error"], "ADAPTER_OPERATION_DENIED")
                self.assertEqual(adapter.execute_count, 0)

    def test_runner_returns_plan_without_starting_process(self) -> None:
        instance = instance_with_binding("runner", "adapter.local-dry-run")
        adapter = LocalDryRunRunnerAdapter(allowed_command_ids=("test",))
        clock = FakeClock()
        host = AdapterHost(instance, [adapter], clock=clock)
        with tempfile.TemporaryDirectory() as temporary:
            verifier = HMACApprovalVerifier(APPROVAL_PROVIDER, APPROVAL_KEY, clock=clock)
            with ControlPlane(
                Path(temporary) / "state.sqlite3",
                clock=clock,
                approval_verifier=verifier,
            ) as control:
                created = control.ingest_feedback(
                    feedback(), idempotency_key="adapter:runner:feedback:1"
                )
                execution = execution_payload(created["work_item"]["id"])
                authorization_sequence = advance_to_open_pr(
                    control, clock, execution["work_item_id"]
                )
                control.queue_effect(
                    execution["work_item_id"],
                    authorization_event_sequence=authorization_sequence,
                    adapter_slot="runner",
                    operation="runner.execute",
                    payload=execution,
                    idempotency_key="adapter:runner:effect:1",
                )
                result = AdapterWorker(control, host, "worker-dry-run").run_once()
                self.assertEqual(result["effect"]["state"], "COMPLETED")
                self.assertEqual(result["effect"]["result"]["output"]["status"], "PLANNED")
                self.assertEqual(adapter.execute_count, 1)

    def test_provider_idempotency_retry_ignores_attempt_and_deadline_metadata(self) -> None:
        instance = instance_with_binding("runner", "adapter.local-dry-run")
        adapter = LocalDryRunRunnerAdapter(allowed_command_ids=("test",))
        clock = FakeClock()
        host = AdapterHost(instance, [adapter], clock=clock)
        with tempfile.TemporaryDirectory() as temporary:
            verifier = HMACApprovalVerifier(APPROVAL_PROVIDER, APPROVAL_KEY, clock=clock)
            with ControlPlane(
                Path(temporary) / "state.sqlite3",
                clock=clock,
                approval_verifier=verifier,
            ) as control:
                created = control.ingest_feedback(
                    feedback(), idempotency_key="adapter:runner:retry-feedback:1"
                )
                execution = execution_payload(created["work_item"]["id"])
                authorization_sequence = advance_to_open_pr(
                    control, clock, execution["work_item_id"]
                )
                control.queue_effect(
                    execution["work_item_id"],
                    authorization_event_sequence=authorization_sequence,
                    adapter_slot="runner",
                    operation="runner.execute",
                    payload=execution,
                    idempotency_key="adapter:runner:retry-effect:1",
                )
                crashed = control.claim_effect("worker-runner-crashed", lease_seconds=10)["effect"]
                first = host.dispatch(
                    crashed,
                    control.get_audit_event(crashed["authorization_event_sequence"]),
                )
                self.assertEqual(first["status"], "SUCCEEDED")
                self.assertEqual(adapter.execute_count, 1)

                clock.advance(11)
                control.reconcile()
                result = AdapterWorker(control, host, "worker-runner-retry").run_once()
                self.assertEqual(result["effect"]["state"], "COMPLETED")
                self.assertEqual(adapter.execute_count, 1)


if __name__ == "__main__":
    unittest.main()
