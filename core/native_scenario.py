"""No-network Native reference scenario ending at an independently reviewed Draft PR."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from core.adapter_ports import (
    PORT_METHODS,
    DeterministicFakePort,
    PortCall,
    PortRegistry,
    PortResult,
    SideEffect,
)
from core.contracts import (
    approval_scope_digest,
    digest_value,
    evidence_bundle_digest,
    plan_revision_digest,
)
from core.json_support import loads_strict
from core.native_controller import NativeController

ROOT = Path(__file__).resolve().parents[1]
REFERENCE_WORKFLOW = ROOT / "contracts/native-reference-workflow.json"
REFERENCE_DESCRIPTOR = ROOT / "examples/v08-contracts/valid/adapter-descriptor.json"
REFERENCE_EPOCH = 1_786_425_600.0


def _reference_clock() -> float:
    """Return a stable fixture time so the CLI scenario is replayable across processes."""

    return REFERENCE_EPOCH


def _iso(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def load_reference_workflow() -> dict[str, Any]:
    value = loads_strict(REFERENCE_WORKFLOW.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("Native reference workflow root must be an object")
    return value


def build_native_mock_ports(
    *,
    clock: Callable[[], float] = _reference_clock,
) -> tuple[PortRegistry, dict[str, DeterministicFakePort]]:
    descriptor = loads_strict(REFERENCE_DESCRIPTOR.read_text(encoding="utf-8"))
    if not isinstance(descriptor, dict):
        raise ValueError("Native reference descriptor root must be an object")
    capabilities = {
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
    descriptor["ports"] = list(PORT_METHODS)
    descriptor["capabilities"] = list(capabilities.values())
    descriptor["idempotency"] = [
        {"port": port, "mode": "provider-key"} for port in PORT_METHODS
    ]
    fakes = {
        port: DeterministicFakePort(
            str(descriptor["adapter_id"]),
            port,
            frozenset({capability}),
            clock=clock,
        )
        for port, capability in capabilities.items()
    }
    registry = PortRegistry()
    registry.register(descriptor, fakes)
    for port, capability in capabilities.items():
        registry.bind(
            port=port,
            adapter_id=str(descriptor["adapter_id"]),
            required_capabilities=frozenset({capability}),
        )
    return registry, fakes


class _Commands:
    def __init__(self, clock: Callable[[], float]) -> None:
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
        payload: dict[str, Any] | None = None,
        run_id: str | None = None,
        suffix: str | None = None,
    ) -> dict[str, Any]:
        self.sequence += 1
        slug = command_type.lower().replace("_", "-")
        stable = suffix or str(self.sequence)
        return {
            "$schema": "urn:agent-team:schema:command-envelope:1.0.0",
            "schema_version": "1.0.0",
            "command_id": f"command-{slug}-{stable}",
            "command_type": command_type,
            "idempotency_key": f"native-{slug}-{stable}",
            "work_item_id": "work-native-demo-1",
            "run_id": run_id,
            "expected_revision": revision,
            "actor": {
                "actor_id": actor_id,
                "actor_kind": actor_kind,
                "role_id": role_id,
            },
            "payload": payload or {},
            "issued_at": _iso(float(self.clock())),
        }


def _work_item(now: float) -> dict[str, Any]:
    title = "Add an accessible account menu"
    summary = "Implement the approved account-menu behavior and deterministic tests."
    return {
        "$schema": "urn:agent-team:schema:work-item:2.0.0",
        "schema_version": "2.0.0",
        "work_item_id": "work-native-demo-1",
        "source": {
            "ingress_port": "native.mock",
            "event_id": "feedback-native-demo-1",
            "external_ref": "mock://feedback/1",
            "received_at": _iso(now),
        },
        "normalized": {
            "title": title,
            "summary": summary,
            "untrusted_content_level": "MEDIUM",
            "target_repository_candidates": ["repo.native-demo"],
            "duplicate_fingerprint": digest_value(
                {"title": title.lower(), "summary": summary.lower()}
            ),
            "sensitive_data_flags": [],
        },
        "state": "RECEIVED",
        "revision": 0,
        "created_event_id": "event-native-demo-created",
    }


def _plan(now: float) -> dict[str, Any]:
    document = {
        "$schema": "urn:agent-team:schema:plan-revision:1.0.0",
        "schema_version": "1.0.0",
        "plan_id": "plan-native-demo-1",
        "work_item_id": "work-native-demo-1",
        "revision": 1,
        "previous_plan_digest": None,
        "repository_id": "repo.native-demo",
        "base_commit": "b" * 40,
        "objective": "Implement and test the account menu, obtain independent review, and create only a Draft PR.",
        "assumptions": ["The test double represents a dedicated non-production repository."],
        "tasks": [
            {
                "task_id": "task-implement",
                "role_id": "role.implementer",
                "objective": "Implement the bounded change.",
                "depends_on": [],
                "required_capabilities": ["code.change"],
                "completion_evidence": ["change-commit"],
            },
            {
                "task_id": "task-test",
                "role_id": "role.tester",
                "objective": "Run deterministic tests.",
                "depends_on": ["task-implement"],
                "required_capabilities": ["test.run"],
                "completion_evidence": ["test-result"],
            },
        ],
        "allowed_paths": ["src/account/", "tests/account/"],
        "allowed_actions": [
            "repository.read",
            "workspace.write",
            "test.run",
            "commit.create",
            "draft-pr.create",
            "ci.read",
        ],
        "tests": ["python -m unittest discover -s tests"],
        "risk_level": "MEDIUM",
        "rollback": "Discard the mock workspace and Draft PR projection.",
        "budget_limit": 100,
        "time_limit_seconds": 3600,
        "created_by": "role.planner",
        "created_at": _iso(now),
        "plan_digest": "sha256:" + "0" * 64,
    }
    document["plan_digest"] = plan_revision_digest(document)
    return document


def _approval(now: float, plan: dict[str, Any]) -> dict[str, Any]:
    capabilities = sorted(
        {
            capability
            for task in plan["tasks"]
            for capability in task["required_capabilities"]
        }
    )
    document = {
        "$schema": "urn:agent-team:schema:approval-grant:1.0.0",
        "schema_version": "1.0.0",
        "approval_id": "approval-native-demo-1",
        "actor_id": "owner.native-demo",
        "identity_provider": "native.mock-identity",
        "work_item_id": plan["work_item_id"],
        "plan_revision": plan["revision"],
        "plan_digest": plan["plan_digest"],
        "repository_id": plan["repository_id"],
        "base_commit": plan["base_commit"],
        "allowed_paths": plan["allowed_paths"],
        "allowed_actions": plan["allowed_actions"],
        "runner_profile": "runner.mock-isolated@1.0.0",
        "agent_capabilities": capabilities,
        "budget_limit": plan["budget_limit"],
        "time_limit_seconds": plan["time_limit_seconds"],
        "merge_allowed": False,
        "deploy_allowed": False,
        "issued_at": _iso(now - 1),
        "expires_at": _iso(now + 1800),
        "nonce": "native-demo-nonce-0001",
        "evidence_ref": "mock://approval/1",
        "signature_ref": "mock-identity://signature/1",
        "scope_digest": "sha256:" + "0" * 64,
    }
    document["scope_digest"] = approval_scope_digest(document)
    return document


def _worker_transition(
    controller: NativeController,
    commands: _Commands,
    command_type: str,
    revision: int,
    role_id: str,
    actor_id: str,
    evidence_types: list[str],
    *,
    run_id: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    lease = controller.acquire_lease(
        commands.make(
            "ACQUIRE_LEASE",
            revision,
            actor_id=actor_id,
            actor_kind="worker",
            role_id=role_id,
            run_id=run_id,
        )
    )["lease"]
    payload = dict(extra or {})
    payload.update(
        {
            "lease_id": lease["lease_id"],
            "evidence_types": evidence_types,
            "evidence_refs": [f"mock://evidence/{command_type.lower()}"],
        }
    )
    return controller.apply_transition(
        commands.make(
            command_type,
            revision,
            actor_id=actor_id,
            actor_kind="worker",
            role_id=role_id,
            payload=payload,
            run_id=run_id,
        )
    )


def _effect(
    controller: NativeController,
    commands: _Commands,
    *,
    revision: int,
    port: str,
    operation: str,
    payload: dict[str, Any],
    run_id: str,
    suffix: str,
) -> dict[str, Any]:
    queued = controller.queue_effect(
        commands.make(
            "QUEUE_EFFECT",
            revision,
            run_id=run_id,
            suffix=suffix,
        ),
        port=port,
        operation=operation,
        payload=payload,
    )["effect"]
    return controller.run_effect(queued["effect_id"])


def run_native_reference_scenario(
    database: Path,
    *,
    clock: Callable[[], float] = _reference_clock,
) -> dict[str, Any]:
    """Run the deterministic fake scenario and stop at DRAFT_PR_READY."""

    ports, fakes = build_native_mock_ports(clock=clock)
    commands = _Commands(clock)
    now = float(clock())
    workflow = load_reference_workflow()
    with NativeController(database, workflow, ports=ports, clock=clock, create=True) as controller:
        ingress = ports.get("ingress").invoke(
            PortCall(
                request_id="request-native-ingress-1",
                operation="feedback.receive",
                idempotency_key="native-ingress-feedback-1",
                correlation_id="work-native-demo-1",
                deadline_epoch=now + 30,
                payload={"event_id": "feedback-native-demo-1", "content_class": "untrusted"},
            )
        )
        controller.create_work_item(
            commands.make("CREATE_WORK_ITEM", 0, actor_id="adapter.native-mock", actor_kind="adapter"),
            _work_item(now),
        )
        _worker_transition(
            controller, commands, "NORMALIZE", 1, "role.intake", "worker-intake-1", ["input-snapshot"]
        )
        _worker_transition(
            controller,
            commands,
            "TRIAGE_ACCEPT",
            2,
            "role.triage",
            "worker-triage-1",
            ["context-manifest"],
        )
        plan = _plan(now)
        _worker_transition(
            controller,
            commands,
            "PLAN_READY",
            3,
            "role.planner",
            "worker-planner-1",
            ["context-manifest"],
            extra={"plan_revision": plan},
        )
        controller.apply_transition(
            commands.make(
                "REQUEST_APPROVAL",
                4,
                payload={
                    "evidence_types": ["plan-revision"],
                    "evidence_refs": [f"mock://plan/{plan['plan_digest']}"],
                },
            )
        )
        grant = _approval(now, plan)
        fakes["identity"].script(
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
        controller.apply_transition(
            commands.make(
                "APPROVE_PLAN",
                5,
                actor_id=grant["actor_id"],
                actor_kind="human",
                run_id="run-native-demo-1",
                payload={
                    "evidence_types": ["approval"],
                    "evidence_refs": [grant["evidence_ref"]],
                    "runner_profile": grant["runner_profile"],
                    "agent_capabilities": grant["agent_capabilities"],
                },
            ),
            approval_grant=grant,
        )
        controller.apply_transition(
            commands.make(
                "START_EXECUTION",
                6,
                run_id="run-native-demo-1",
                payload={
                    "evidence_types": ["approval"],
                    "evidence_refs": [grant["evidence_ref"]],
                },
            )
        )

        implementation_1 = _effect(
            controller,
            commands,
            revision=7,
            port="agent-executor",
            operation="agent.implement",
            payload={"role_id": "role.implementer", "session_id": "implementer-session-1"},
            run_id="run-native-demo-1",
            suffix="implement-1",
        )
        _worker_transition(
            controller,
            commands,
            "IMPLEMENTATION_READY",
            7,
            "role.implementer",
            "implementer-session-1",
            ["change-commit"],
            run_id="run-native-demo-1",
            extra={"cost_units_delta": 10},
        )
        sandbox_1 = _effect(
            controller,
            commands,
            revision=8,
            port="sandbox",
            operation="sandbox.test",
            payload={"profile": "runner.mock-isolated@1.0.0", "network": "none"},
            run_id="run-native-demo-1",
            suffix="sandbox-1",
        )
        ci_1 = _effect(
            controller,
            commands,
            revision=8,
            port="ci",
            operation="ci.check",
            payload={"repository_id": "repo.native-demo", "commit": "c" * 40},
            run_id="run-native-demo-1",
            suffix="ci-1",
        )
        _worker_transition(
            controller,
            commands,
            "TESTS_PASSED",
            8,
            "role.tester",
            "tester-session-1",
            ["test-result"],
            run_id="run-native-demo-1",
            extra={"cost_units_delta": 5},
        )
        fakes["agent-executor"].script(
            PortResult.succeeded(
                {"decision": "CHANGES_REQUESTED", "session_id": "reviewer-session-1"}
            )
        )
        review_1 = _effect(
            controller,
            commands,
            revision=9,
            port="agent-executor",
            operation="agent.review",
            payload={"role_id": "role.reviewer", "session_id": "reviewer-session-1"},
            run_id="run-native-demo-1",
            suffix="review-1",
        )
        _worker_transition(
            controller,
            commands,
            "CHANGES_REQUESTED",
            9,
            "role.reviewer",
            "reviewer-session-1",
            ["review"],
            run_id="run-native-demo-1",
            extra={"cost_units_delta": 3},
        )
        controller.apply_transition(
            commands.make(
                "START_REWORK",
                10,
                run_id="run-native-demo-1",
                payload={
                    "evidence_types": ["review"],
                    "evidence_refs": ["mock://review/1"],
                },
            )
        )
        implementation_2 = _effect(
            controller,
            commands,
            revision=11,
            port="agent-executor",
            operation="agent.implement",
            payload={"role_id": "role.implementer", "session_id": "implementer-session-2"},
            run_id="run-native-demo-1",
            suffix="implement-2",
        )
        _worker_transition(
            controller,
            commands,
            "IMPLEMENTATION_READY",
            11,
            "role.implementer",
            "implementer-session-2",
            ["change-commit"],
            run_id="run-native-demo-1",
            extra={"cost_units_delta": 8},
        )
        sandbox_2 = _effect(
            controller,
            commands,
            revision=12,
            port="sandbox",
            operation="sandbox.test",
            payload={"profile": "runner.mock-isolated@1.0.0", "network": "none", "round": 2},
            run_id="run-native-demo-1",
            suffix="sandbox-2",
        )
        ci_2 = _effect(
            controller,
            commands,
            revision=12,
            port="ci",
            operation="ci.check",
            payload={"repository_id": "repo.native-demo", "commit": "d" * 40},
            run_id="run-native-demo-1",
            suffix="ci-2",
        )
        _worker_transition(
            controller,
            commands,
            "TESTS_PASSED",
            12,
            "role.tester",
            "tester-session-2",
            ["test-result"],
            run_id="run-native-demo-1",
            extra={"cost_units_delta": 5},
        )
        fakes["agent-executor"].script(
            PortResult.succeeded(
                {"decision": "APPROVED", "session_id": "reviewer-session-2"}
            )
        )
        review_2 = _effect(
            controller,
            commands,
            revision=13,
            port="agent-executor",
            operation="agent.review",
            payload={"role_id": "role.reviewer", "session_id": "reviewer-session-2"},
            run_id="run-native-demo-1",
            suffix="review-2",
        )
        fakes["scm"].script(
            PortResult.succeeded(
                {"draft": True, "mergeable_claim": False},
                side_effect=SideEffect.APPLIED,
                provider_ref="mock://draft-pr/1",
            )
        )
        draft = _effect(
            controller,
            commands,
            revision=13,
            port="scm",
            operation="draft-pr.create",
            payload={
                "repository_id": "repo.native-demo",
                "base_commit": plan["base_commit"],
                "plan_digest": plan["plan_digest"],
                "draft": True,
            },
            run_id="run-native-demo-1",
            suffix="draft-pr-1",
        )
        final_transition = controller.apply_transition(
            commands.make(
                "DRAFT_PR_CREATED",
                13,
                run_id="run-native-demo-1",
                payload={
                    "evidence_types": ["review", "test-result", "draft-pr"],
                    "evidence_refs": ["mock://review/2", "mock://tests/2", "mock://draft-pr/1"],
                    "cost_units_delta": 3,
                },
            )
        )
        effect_documents = [
            implementation_1,
            sandbox_1,
            ci_1,
            review_1,
            implementation_2,
            sandbox_2,
            ci_2,
            review_2,
            draft,
        ]
        items = [
            {
                "evidence_id": f"item-native-{index}",
                "type": evidence_type,
                "content_ref": f"native-effect:{effect['effect_id']}",
                "content_digest": digest_value(effect),
                "producer": "native-controller",
                "created_at": _iso(float(clock())),
                "classification": "INTERNAL",
                "redacted": True,
            }
            for index, (effect, evidence_type) in enumerate(
                zip(
                    effect_documents,
                    (
                        "change-commit",
                        "test-result",
                        "ci-result",
                        "review",
                        "change-commit",
                        "test-result",
                        "ci-result",
                        "review",
                        "draft-pr",
                    ),
                ),
                start=1,
            )
        ]
        bundle = {
            "$schema": "urn:agent-team:schema:evidence-bundle:1.0.0",
            "schema_version": "1.0.0",
            "bundle_id": "evidence-native-demo-1",
            "run_id": "run-native-demo-1",
            "work_item_id": "work-native-demo-1",
            "items": items,
            "created_at": _iso(float(clock())),
            "created_by": "native-controller",
            "retention": {"policy": "project", "expires_at": None},
            "bundle_digest": "sha256:" + "0" * 64,
        }
        bundle["bundle_digest"] = evidence_bundle_digest(bundle)
        evidence = controller.store_evidence(
            commands.make(
                "STORE_EVIDENCE",
                14,
                run_id="run-native-demo-1",
                suffix="evidence-1",
            ),
            bundle,
        )
        notification = _effect(
            controller,
            commands,
            revision=14,
            port="notification",
            operation="notification.send",
            payload={"state": "DRAFT_PR_READY", "draft_pr_ref": "mock://draft-pr/1"},
            run_id="run-native-demo-1",
            suffix="notification-1",
        )
        snapshot = controller.get_work_item("work-native-demo-1")
        invariants = controller.verify_invariants()
        return {
            "status": "REFERENCE_SCENARIO_PASSED",
            "work_item": snapshot["work_item"],
            "run": snapshot["run"],
            "plan_digest": plan["plan_digest"],
            "approval_scope_digest": grant["scope_digest"],
            "draft_pr_ref": draft["result"]["provider_ref"],
            "evidence_bundle_digest": evidence["bundle"]["bundle_digest"],
            "independent_review": {
                "author_sessions": ["implementer-session-1", "implementer-session-2"],
                "reviewer_sessions": ["reviewer-session-1", "reviewer-session-2"],
                "changes_requested_rounds": 1,
            },
            "ingress_outcome": ingress.outcome.value,
            "notification_status": notification["status"],
            "capability_reports": ports.capability_reports(),
            "controller": controller.status(),
            "invariants": invariants,
            "safety": {
                "external_network_used": False,
                "untrusted_code_executed": False,
                "real_scm_write_used": False,
                "merge_enabled": False,
                "deploy_enabled": False,
                "stopped_at": final_transition["work_item"]["state"],
            },
        }
