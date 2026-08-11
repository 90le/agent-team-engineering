from __future__ import annotations

import copy
import json
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from core.adapter_ports import (
    PORT_METHODS,
    DeterministicFakePort,
    Outcome,
    PortRegistry,
    PortResult,
    SideEffect,
)
from core.contracts import approval_scope_digest, plan_revision_digest
from core.native_controller import (
    InjectedNativeCrash,
    NativeApprovalDenied,
    NativeController,
    NativeControllerError,
    NativeEffectBusy,
    NativeIdempotencyConflict,
    NativeLeaseDenied,
    NativeRevisionConflict,
)

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = json.loads(
    (ROOT / "contracts/native-reference-workflow.json").read_text(encoding="utf-8")
)


class FakeClock:
    def __init__(self, value: float = 1_786_425_600.0) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds

    def iso(self, offset: float = 0) -> str:
        return (
            datetime.fromtimestamp(self.value + offset, timezone.utc)
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z")
        )


def native_ports(clock: FakeClock) -> tuple[PortRegistry, dict[str, DeterministicFakePort]]:
    descriptor = json.loads(
        (ROOT / "examples/v08-contracts/valid/adapter-descriptor.json").read_text(
            encoding="utf-8"
        )
    )
    descriptor["ports"] = list(PORT_METHODS)
    descriptor["capabilities"] = [
        "approval.verify",
        "draft-pr.create",
        "agent.execute",
        "sandbox.execute",
        "ci.check",
        "evidence.record",
        "notification.send",
        "feedback.receive",
        "state.transact",
        "secret.lease-ref",
    ]
    descriptor["idempotency"] = [
        {"port": port, "mode": "provider-key"} for port in PORT_METHODS
    ]
    port_capability = {
        "ingress": "feedback.receive",
        "identity": "approval.verify",
        "scm": "draft-pr.create",
        "agent-executor": "agent.execute",
        "sandbox": "sandbox.execute",
        "ci": "ci.check",
        "state-store": "state.transact",
        "evidence": "evidence.record",
        "notification": "notification.send",
        "secret": "secret.lease-ref",
    }
    fakes = {
        port: DeterministicFakePort(
            descriptor["adapter_id"],
            port,
            frozenset({capability}),
            clock=clock,
        )
        for port, capability in port_capability.items()
    }
    registry = PortRegistry()
    registry.register(descriptor, fakes)
    for port, capability in port_capability.items():
        registry.bind(
            port=port,
            adapter_id=descriptor["adapter_id"],
            required_capabilities=frozenset({capability}),
        )
    return registry, fakes


def work_item() -> dict:
    value = json.loads(
        (ROOT / "examples/v08-contracts/valid/work-item.json").read_text(encoding="utf-8")
    )
    value["state"] = "RECEIVED"
    value["revision"] = 0
    return value


def plan() -> dict:
    value = json.loads(
        (ROOT / "examples/v08-contracts/valid/plan-revision.json").read_text(
            encoding="utf-8"
        )
    )
    value["plan_digest"] = plan_revision_digest(value)
    return value


def approval(clock: FakeClock, approved_plan: dict) -> dict:
    value = json.loads(
        (ROOT / "examples/v08-contracts/valid/approval-grant.json").read_text(
            encoding="utf-8"
        )
    )
    value["work_item_id"] = approved_plan["work_item_id"]
    value["plan_revision"] = approved_plan["revision"]
    value["plan_digest"] = approved_plan["plan_digest"]
    value["repository_id"] = approved_plan["repository_id"]
    value["base_commit"] = approved_plan["base_commit"]
    value["allowed_paths"] = approved_plan["allowed_paths"]
    value["allowed_actions"] = approved_plan["allowed_actions"]
    value["budget_limit"] = approved_plan["budget_limit"]
    value["time_limit_seconds"] = approved_plan["time_limit_seconds"]
    value["agent_capabilities"] = sorted(
        {
            capability
            for task in approved_plan["tasks"]
            for capability in task["required_capabilities"]
        }
    )
    value["issued_at"] = clock.iso(-10)
    value["expires_at"] = clock.iso(3600)
    value["scope_digest"] = approval_scope_digest(value)
    return value


class CommandFactory:
    def __init__(self, clock: FakeClock) -> None:
        self.clock = clock
        self.sequence = 0

    def make(
        self,
        command_type: str,
        revision: int,
        *,
        actor_id: str = "native-controller",
        actor_kind: str = "controller",
        role_id: str | None = None,
        payload: dict | None = None,
        run_id: str | None = None,
        key: str | None = None,
    ) -> dict:
        self.sequence += 1
        slug = command_type.lower().replace("_", "-")
        return {
            "$schema": "urn:agent-team:schema:command-envelope:1.0.0",
            "schema_version": "1.0.0",
            "command_id": f"command-{slug}-{self.sequence}",
            "command_type": command_type,
            "idempotency_key": key or f"native-{slug}-{self.sequence}",
            "work_item_id": "work-example-1",
            "run_id": run_id,
            "expected_revision": revision,
            "actor": {
                "actor_id": actor_id,
                "actor_kind": actor_kind,
                "role_id": role_id,
            },
            "payload": payload or {},
            "issued_at": self.clock.iso(),
        }


def create(controller: NativeController, commands: CommandFactory) -> dict:
    return controller.create_work_item(commands.make("CREATE_WORK_ITEM", 0), work_item())


def worker_transition(
    controller: NativeController,
    commands: CommandFactory,
    command_type: str,
    revision: int,
    role: str,
    evidence: list[str],
    *,
    payload: dict | None = None,
    run_id: str | None = None,
    actor_id: str | None = None,
    fault: str | None = None,
) -> dict:
    actor = actor_id or role.replace("role.", "worker-")
    lease_command = commands.make(
        "ACQUIRE_LEASE",
        revision,
        actor_id=actor,
        actor_kind="worker",
        role_id=role,
        run_id=run_id,
    )
    lease = controller.acquire_lease(lease_command)["lease"]
    transition_payload = dict(payload or {})
    transition_payload.update(
        {
            "lease_id": lease["lease_id"],
            "evidence_types": evidence,
            "evidence_refs": [f"native://{command_type.lower()}"],
        }
    )
    command = commands.make(
        command_type,
        revision,
        actor_id=actor,
        actor_kind="worker",
        role_id=role,
        payload=transition_payload,
        run_id=run_id,
    )
    return controller.apply_transition(command, fault=fault)


def advance_to_awaiting(
    controller: NativeController, commands: CommandFactory, approved_plan: dict
) -> None:
    worker_transition(controller, commands, "NORMALIZE", 1, "role.intake", ["input-snapshot"])
    worker_transition(
        controller, commands, "TRIAGE_ACCEPT", 2, "role.triage", ["context-manifest"]
    )
    worker_transition(
        controller,
        commands,
        "PLAN_READY",
        3,
        "role.planner",
        ["context-manifest"],
        payload={"plan_revision": approved_plan},
    )
    controller.apply_transition(
        commands.make(
            "REQUEST_APPROVAL",
            4,
            payload={
                "evidence_types": ["plan-revision"],
                "evidence_refs": ["native://plan/example-1"],
            },
        )
    )


def script_identity(fake: DeterministicFakePort, grant: dict) -> None:
    fake.script(
        PortResult.succeeded(
            {
                "verified": True,
                "approval_id": grant["approval_id"],
                "actor_id": grant["actor_id"],
                "identity_provider": grant["identity_provider"],
                "signature_ref": grant["signature_ref"],
            }
        )
    )


def approve_plan(
    controller: NativeController,
    commands: CommandFactory,
    identity: DeterministicFakePort,
    grant: dict,
) -> dict:
    script_identity(identity, grant)
    return controller.apply_transition(
        commands.make(
            "APPROVE_PLAN",
            5,
            actor_id=grant["actor_id"],
            actor_kind="human",
            payload={
                "evidence_types": ["approval"],
                "evidence_refs": [grant["evidence_ref"]],
                "runner_profile": grant["runner_profile"],
                "agent_capabilities": grant["agent_capabilities"],
            },
            run_id="run-example-1",
        ),
        approval_grant=grant,
    )


class NativeControllerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.clock = FakeClock()
        self.ports, self.fakes = native_ports(self.clock)
        self.commands = CommandFactory(self.clock)
        self.controller = NativeController(
            self.root / "native.sqlite3",
            WORKFLOW,
            ports=self.ports,
            clock=self.clock,
        )

    def tearDown(self) -> None:
        self.controller.close()
        self.temporary.cleanup()

    def test_create_is_transactional_revisioned_and_idempotent(self) -> None:
        command = self.commands.make("CREATE_WORK_ITEM", 0)
        first = self.controller.create_work_item(command, work_item())
        replays = [self.controller.create_work_item(command, work_item()) for _ in range(10)]
        self.assertTrue(all(first == replay for replay in replays))
        self.assertEqual(first["work_item"]["revision"], 1)
        self.assertEqual(
            self.controller.connection.execute("SELECT COUNT(*) FROM native_work_items").fetchone()[0],
            1,
        )
        self.assertEqual(
            len(
                [
                    event
                    for event in self.controller.export_events()
                    if event["event_type"] == "WORK_ITEM_CREATED"
                ]
            ),
            1,
        )
        changed = copy.deepcopy(command)
        changed["payload"] = {"changed": True}
        with self.assertRaises(NativeIdempotencyConflict):
            self.controller.create_work_item(changed, work_item())
        self.assertEqual(self.controller.verify_invariants()["status"], "VALID")

    def test_transition_crash_before_commit_rolls_back_and_after_commit_replays(self) -> None:
        create(self.controller, self.commands)
        lease_command = self.commands.make(
            "ACQUIRE_LEASE",
            1,
            actor_id="worker-intake",
            actor_kind="worker",
            role_id="role.intake",
        )
        lease = self.controller.acquire_lease(lease_command)["lease"]
        command = self.commands.make(
            "NORMALIZE",
            1,
            actor_id="worker-intake",
            actor_kind="worker",
            role_id="role.intake",
            payload={
                "lease_id": lease["lease_id"],
                "evidence_types": ["input-snapshot"],
                "evidence_refs": ["native://input"],
            },
        )
        with self.assertRaises(InjectedNativeCrash):
            self.controller.apply_transition(command, fault="before_commit")
        self.assertEqual(self.controller.get_work_item("work-example-1")["work_item"]["state"], "RECEIVED")
        committed = self.controller.apply_transition(command)
        self.assertEqual(committed["work_item"]["state"], "NORMALIZED")

        lease2 = self.controller.acquire_lease(
            self.commands.make(
                "ACQUIRE_LEASE",
                2,
                actor_id="worker-triage",
                actor_kind="worker",
                role_id="role.triage",
            )
        )["lease"]
        command2 = self.commands.make(
            "TRIAGE_ACCEPT",
            2,
            actor_id="worker-triage",
            actor_kind="worker",
            role_id="role.triage",
            payload={
                "lease_id": lease2["lease_id"],
                "evidence_types": ["context-manifest"],
                "evidence_refs": ["native://context"],
            },
        )
        with self.assertRaises(InjectedNativeCrash):
            self.controller.apply_transition(command2, fault="after_commit")
        replay = self.controller.apply_transition(command2)
        self.assertEqual(replay["work_item"]["state"], "TRIAGED")
        events = [e for e in self.controller.export_events() if e["event_type"] == "TRIAGE_ACCEPT_APPLIED"]
        self.assertEqual(len(events), 1)

    def test_exact_approval_identity_and_nonce_are_enforced(self) -> None:
        create(self.controller, self.commands)
        approved_plan = plan()
        advance_to_awaiting(self.controller, self.commands, approved_plan)
        grant = approval(self.clock, approved_plan)
        tampered = copy.deepcopy(grant)
        tampered["base_commit"] = "c" * 40
        tampered["scope_digest"] = approval_scope_digest(tampered)
        with self.assertRaisesRegex(NativeApprovalDenied, "base_commit"):
            approve_plan(
                self.controller, self.commands, self.fakes["identity"], tampered
            )

        result = approve_plan(
            self.controller, self.commands, self.fakes["identity"], grant
        )
        self.assertEqual(result["work_item"]["state"], "APPROVED")
        self.assertFalse(result["approval_grant"]["merge_allowed"])
        self.assertFalse(result["approval_grant"]["deploy_allowed"])
        self.assertEqual(
            self.controller.connection.execute(
                "SELECT COUNT(*) FROM native_approval_nonces WHERE nonce = ?",
                (grant["nonce"],),
            ).fetchone()[0],
            1,
        )
        with self.assertRaises(sqlite3.IntegrityError):
            self.controller.connection.execute(
                "INSERT INTO native_approval_nonces(nonce, approval_id, work_item_id, consumed_at_epoch) VALUES(?, ?, ?, ?)",
                (grant["nonce"], "approval-replay-2", "work-example-1", self.clock()),
            )

    def test_approval_scope_matrix_rejects_every_mismatch(self) -> None:
        approved_plan = plan()
        valid = approval(self.clock, approved_plan)
        command = self.commands.make(
            "APPROVE_PLAN",
            5,
            actor_id=valid["actor_id"],
            actor_kind="human",
            payload={
                "runner_profile": valid["runner_profile"],
                "agent_capabilities": valid["agent_capabilities"],
            },
            run_id="run-example-1",
        )
        mutations = {
            "work_item_id": "work-other-1",
            "plan_revision": 2,
            "plan_digest": "sha256:" + "c" * 64,
            "repository_id": "repo.other",
            "base_commit": "c" * 40,
            "allowed_paths": ["src/other/"],
            "allowed_actions": ["repository.read"],
            "budget_limit": valid["budget_limit"] + 1,
            "time_limit_seconds": valid["time_limit_seconds"] + 1,
            "agent_capabilities": ["code.change"],
            "runner_profile": "runner.other@1.0.0",
        }
        for field, value in mutations.items():
            with self.subTest(field=field):
                changed = copy.deepcopy(valid)
                changed[field] = value
                changed["scope_digest"] = approval_scope_digest(changed)
                with self.assertRaises(NativeApprovalDenied):
                    self.controller._verify_exact_approval(command, approved_plan, changed)

        expired = copy.deepcopy(valid)
        expired["issued_at"] = self.clock.iso(-100)
        expired["expires_at"] = self.clock.iso(-1)
        expired["scope_digest"] = approval_scope_digest(expired)
        with self.assertRaisesRegex(NativeApprovalDenied, "not active"):
            self.controller._verify_exact_approval(command, approved_plan, expired)

    def test_expired_worker_lease_is_recovered_and_cannot_transition(self) -> None:
        create(self.controller, self.commands)
        lease = self.controller.acquire_lease(
            self.commands.make(
                "ACQUIRE_LEASE",
                1,
                actor_id="worker-intake",
                actor_kind="worker",
                role_id="role.intake",
            ),
            ttl_seconds=10,
        )["lease"]
        self.clock.advance(11)
        command = self.commands.make(
            "NORMALIZE",
            1,
            actor_id="worker-intake",
            actor_kind="worker",
            role_id="role.intake",
            payload={
                "lease_id": lease["lease_id"],
                "evidence_types": ["input-snapshot"],
                "evidence_refs": [],
            },
        )
        with self.assertRaises(NativeLeaseDenied):
            self.controller.apply_transition(command)
        recovery = self.controller.recover_orphans()
        self.assertEqual(recovery["recovered_leases"], 1)
        self.assertEqual(self.controller.status()["active_leases"], 0)

    def test_effect_crash_after_provider_success_replays_without_duplicate_side_effect(self) -> None:
        create(self.controller, self.commands)
        self.fakes["scm"].script(
            PortResult.succeeded(
                {"draft": True},
                side_effect=SideEffect.APPLIED,
                provider_ref="mock://draft-pr/1",
            )
        )
        queued = self.controller.queue_effect(
            self.commands.make("QUEUE_EFFECT", 1),
            port="scm",
            operation="draft-pr.create",
            payload={"repository_id": "repo.example", "base_commit": "b" * 40},
        )["effect"]
        with self.assertRaises(InjectedNativeCrash):
            self.controller.run_effect(queued["effect_id"], claim_seconds=10, fault="after_invoke")
        self.assertEqual(len(self.fakes["scm"].calls), 1)
        self.clock.advance(11)
        self.assertEqual(self.controller.recover_orphans()["recovered_effects"], 1)
        final = self.controller.run_effect(queued["effect_id"])
        self.assertEqual(final["status"], "SUCCEEDED")
        self.assertEqual(len(self.fakes["scm"].calls), 2)
        self.assertEqual(len(self.fakes["scm"].executions), 1)
        self.assertEqual(final["result"]["provider_ref"], "mock://draft-pr/1")
        self.assertEqual(
            len([event for event in self.controller.export_events() if event["event_type"] == "EFFECT_SUCCEEDED"]),
            1,
        )

    def test_effect_fault_matrix_recovers_each_claim_and_finalize_boundary(self) -> None:
        create(self.controller, self.commands)
        for index, fault_point in enumerate(
            ("after_claim", "before_invoke", "after_invoke", "before_finalize"),
            start=1,
        ):
            with self.subTest(fault_point=fault_point):
                before_executions = len(self.fakes["scm"].executions)
                self.fakes["scm"].script(
                    PortResult.succeeded(
                        {"draft": True, "case": fault_point},
                        side_effect=SideEffect.APPLIED,
                        provider_ref=f"mock://draft-pr/fault-{index}",
                    )
                )
                effect = self.controller.queue_effect(
                    self.commands.make("QUEUE_EFFECT", 1),
                    port="scm",
                    operation="draft-pr.create",
                    payload={"repository_id": "repo.example", "case": fault_point},
                )["effect"]
                with self.assertRaises(InjectedNativeCrash):
                    self.controller.run_effect(
                        effect["effect_id"], claim_seconds=5, fault=fault_point
                    )
                self.clock.advance(6)
                self.assertEqual(self.controller.recover_orphans()["recovered_effects"], 1)
                final = self.controller.run_effect(effect["effect_id"])
                self.assertEqual(final["status"], "SUCCEEDED")
                self.assertEqual(
                    len(self.fakes["scm"].executions) - before_executions,
                    1,
                )

    def test_unknown_side_effect_stops_without_blind_retry(self) -> None:
        create(self.controller, self.commands)
        self.fakes["scm"].script(
            PortResult.failed(
                Outcome.UNKNOWN,
                "SIDE_EFFECT_UNKNOWN",
                side_effect=SideEffect.UNKNOWN,
            )
        )
        effect = self.controller.queue_effect(
            self.commands.make("QUEUE_EFFECT", 1),
            port="scm",
            operation="draft-pr.create",
            payload={"repository_id": "repo.example"},
        )["effect"]
        first = self.controller.run_effect(effect["effect_id"])
        second = self.controller.run_effect(effect["effect_id"])
        self.assertEqual(first["status"], "UNKNOWN")
        self.assertEqual(first, second)
        self.assertEqual(len(self.fakes["scm"].calls), 1)

    def test_retryable_effect_respects_retry_after_and_attempt_budget(self) -> None:
        create(self.controller, self.commands)
        self.fakes["scm"].script(
            PortResult.failed(
                Outcome.RETRYABLE_FAILURE,
                "PROVIDER_UNAVAILABLE",
                retry_after_seconds=5,
            )
        )
        effect = self.controller.queue_effect(
            self.commands.make("QUEUE_EFFECT", 1),
            port="scm",
            operation="draft-pr.create",
            payload={"repository_id": "repo.example"},
            max_attempts=2,
        )["effect"]
        first = self.controller.run_effect(effect["effect_id"])
        self.assertEqual(first["status"], "PENDING")
        with self.assertRaisesRegex(NativeEffectBusy, "retry delay"):
            self.controller.run_effect(effect["effect_id"])
        self.clock.advance(5)
        second = self.controller.run_effect(effect["effect_id"])
        self.assertEqual(second["status"], "SUCCEEDED")
        self.assertEqual(second["attempt"], 2)

    def test_budget_and_time_limits_force_blocked_state(self) -> None:
        create(self.controller, self.commands)
        approved_plan = plan()
        approved_plan["budget_limit"] = 1
        approved_plan["plan_digest"] = plan_revision_digest(approved_plan)
        advance_to_awaiting(self.controller, self.commands, approved_plan)
        grant = approval(self.clock, approved_plan)
        approve_plan(self.controller, self.commands, self.fakes["identity"], grant)
        result = self.controller.apply_transition(
            self.commands.make(
                "START_EXECUTION",
                6,
                payload={
                    "evidence_types": ["approval"],
                    "evidence_refs": [grant["evidence_ref"]],
                    "cost_units_delta": 2,
                },
                run_id="run-example-1",
            )
        )
        self.assertEqual(result["work_item"]["state"], "BLOCKED")
        self.assertEqual(result["limit_exceeded"], "BUDGET_EXCEEDED")

        time_clock = FakeClock()
        time_ports, time_fakes = native_ports(time_clock)
        time_commands = CommandFactory(time_clock)
        with NativeController(
            self.root / "time-limit.sqlite3",
            WORKFLOW,
            ports=time_ports,
            clock=time_clock,
        ) as time_controller:
            create(time_controller, time_commands)
            time_plan = plan()
            time_plan["time_limit_seconds"] = 10
            time_plan["plan_digest"] = plan_revision_digest(time_plan)
            advance_to_awaiting(time_controller, time_commands, time_plan)
            time_grant = approval(time_clock, time_plan)
            approve_plan(
                time_controller, time_commands, time_fakes["identity"], time_grant
            )
            time_clock.advance(11)
            timed_out = time_controller.apply_transition(
                time_commands.make(
                    "START_EXECUTION",
                    6,
                    payload={
                        "evidence_types": ["approval"],
                        "evidence_refs": [time_grant["evidence_ref"]],
                    },
                    run_id="run-example-1",
                )
            )
            self.assertEqual(timed_out["work_item"]["state"], "BLOCKED")
            self.assertEqual(timed_out["limit_exceeded"], "TIME_LIMIT_EXCEEDED")

    def test_backup_reopen_and_audit_tamper_detection(self) -> None:
        create(self.controller, self.commands)
        backup = self.controller.backup(self.root / "native.backup.sqlite3")
        self.assertEqual(backup["status"], "CREATED")
        with NativeController(
            Path(backup["path"]), WORKFLOW, ports=self.ports, clock=self.clock, create=False
        ) as restored:
            self.assertEqual(restored.verify_invariants()["status"], "VALID")

        self.controller.connection.execute(
            "UPDATE native_events SET event_digest = ? WHERE sequence = 1", ("sha256:" + "0" * 64,)
        )
        with self.assertRaisesRegex(NativeControllerError, "event digest mismatch"):
            self.controller.verify_audit()

    def test_wrong_revision_and_workflow_digest_fail_closed(self) -> None:
        create(self.controller, self.commands)
        with self.assertRaises(NativeRevisionConflict):
            self.controller.acquire_lease(
                self.commands.make(
                    "ACQUIRE_LEASE",
                    0,
                    actor_id="worker-intake",
                    actor_kind="worker",
                    role_id="role.intake",
                )
            )
        different = copy.deepcopy(WORKFLOW)
        different["name"] = "Different authority"
        with self.assertRaisesRegex(NativeControllerError, "workflow_digest"):
            NativeController(
                self.root / "native.sqlite3",
                different,
                ports=self.ports,
                clock=self.clock,
                create=False,
            )

    def test_every_workflow_transition_recovers_before_and_after_commit(self) -> None:
        for fault_point in ("before_commit", "after_commit"):
            with self.subTest(fault_point=fault_point):
                clock = FakeClock()
                ports, fakes = native_ports(clock)
                commands = CommandFactory(clock)
                database = self.root / f"matrix-{fault_point}.sqlite3"
                controller = NativeController(database, WORKFLOW, ports=ports, clock=clock)

                def reopen() -> None:
                    nonlocal controller
                    controller.close()
                    controller = NativeController(
                        database, WORKFLOW, ports=ports, clock=clock, create=False
                    )

                def replay_transition(command: dict, grant: dict | None = None) -> dict:
                    try:
                        controller.apply_transition(
                            command, approval_grant=grant, fault=fault_point
                        )
                    except InjectedNativeCrash:
                        reopen()
                    else:
                        self.fail("fault injection did not interrupt the transition")
                    result = controller.apply_transition(command, approval_grant=grant)
                    self.assertEqual(controller.verify_invariants()["status"], "VALID")
                    return result

                def replay_worker(
                    command_type: str,
                    revision: int,
                    role: str,
                    evidence_types: list[str],
                    *,
                    extra: dict | None = None,
                    run_id: str | None = None,
                    actor_id: str | None = None,
                ) -> dict:
                    actor = actor_id or role.replace("role.", "worker-")
                    lease = controller.acquire_lease(
                        commands.make(
                            "ACQUIRE_LEASE",
                            revision,
                            actor_id=actor,
                            actor_kind="worker",
                            role_id=role,
                            run_id=run_id,
                        )
                    )["lease"]
                    payload = dict(extra or {})
                    payload.update(
                        {
                            "lease_id": lease["lease_id"],
                            "evidence_types": evidence_types,
                            "evidence_refs": [f"native://matrix/{command_type.lower()}"],
                        }
                    )
                    return replay_transition(
                        commands.make(
                            command_type,
                            revision,
                            actor_id=actor,
                            actor_kind="worker",
                            role_id=role,
                            payload=payload,
                            run_id=run_id,
                        )
                    )

                try:
                    create_command = commands.make("CREATE_WORK_ITEM", 0)
                    try:
                        controller.create_work_item(
                            create_command, work_item(), fault=fault_point
                        )
                    except InjectedNativeCrash:
                        reopen()
                    else:
                        self.fail("fault injection did not interrupt WorkItem creation")
                    controller.create_work_item(create_command, work_item())

                    replay_worker(
                        "NORMALIZE", 1, "role.intake", ["input-snapshot"]
                    )
                    replay_worker(
                        "TRIAGE_ACCEPT", 2, "role.triage", ["context-manifest"]
                    )
                    approved_plan = plan()
                    replay_worker(
                        "PLAN_READY",
                        3,
                        "role.planner",
                        ["context-manifest"],
                        extra={"plan_revision": approved_plan},
                    )
                    replay_transition(
                        commands.make(
                            "REQUEST_APPROVAL",
                            4,
                            payload={
                                "evidence_types": ["plan-revision"],
                                "evidence_refs": ["native://matrix/plan"],
                            },
                        )
                    )
                    grant = approval(clock, approved_plan)
                    script_identity(fakes["identity"], grant)
                    replay_transition(
                        commands.make(
                            "APPROVE_PLAN",
                            5,
                            actor_id=grant["actor_id"],
                            actor_kind="human",
                            payload={
                                "evidence_types": ["approval"],
                                "evidence_refs": [grant["evidence_ref"]],
                                "runner_profile": grant["runner_profile"],
                                "agent_capabilities": grant["agent_capabilities"],
                            },
                            run_id="run-example-1",
                        ),
                        grant,
                    )
                    replay_transition(
                        commands.make(
                            "START_EXECUTION",
                            6,
                            payload={
                                "evidence_types": ["approval"],
                                "evidence_refs": [grant["evidence_ref"]],
                            },
                            run_id="run-example-1",
                        )
                    )
                    replay_worker(
                        "IMPLEMENTATION_READY",
                        7,
                        "role.implementer",
                        ["change-commit"],
                        run_id="run-example-1",
                        actor_id="implementer-session-1",
                    )
                    replay_worker(
                        "TESTS_PASSED",
                        8,
                        "role.tester",
                        ["test-result"],
                        run_id="run-example-1",
                        actor_id="tester-session-1",
                    )
                    replay_worker(
                        "CHANGES_REQUESTED",
                        9,
                        "role.reviewer",
                        ["review"],
                        run_id="run-example-1",
                        actor_id="reviewer-session-1",
                    )
                    replay_transition(
                        commands.make(
                            "START_REWORK",
                            10,
                            payload={
                                "evidence_types": ["review"],
                                "evidence_refs": ["native://matrix/review-1"],
                            },
                            run_id="run-example-1",
                        )
                    )
                    replay_worker(
                        "IMPLEMENTATION_READY",
                        11,
                        "role.implementer",
                        ["change-commit"],
                        run_id="run-example-1",
                        actor_id="implementer-session-2",
                    )
                    replay_worker(
                        "TESTS_PASSED",
                        12,
                        "role.tester",
                        ["test-result"],
                        run_id="run-example-1",
                        actor_id="tester-session-2",
                    )
                    final = replay_transition(
                        commands.make(
                            "DRAFT_PR_CREATED",
                            13,
                            payload={
                                "evidence_types": ["review", "test-result", "draft-pr"],
                                "evidence_refs": [
                                    "native://matrix/review-2",
                                    "native://matrix/test-2",
                                    "native://matrix/draft-pr",
                                ],
                            },
                            run_id="run-example-1",
                        )
                    )
                    self.assertEqual(final["work_item"]["state"], "DRAFT_PR_READY")
                    transition_events = [
                        event
                        for event in controller.export_events()
                        if event["event_type"].endswith("_APPLIED")
                    ]
                    self.assertEqual(len(transition_events), 13)
                    self.assertEqual(
                        len({event["event_id"] for event in transition_events}), 13
                    )
                finally:
                    controller.close()


if __name__ == "__main__":
    unittest.main()
