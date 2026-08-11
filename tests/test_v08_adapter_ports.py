from __future__ import annotations

import json
import unittest
from pathlib import Path

from core.adapter_ports import (
    PORT_METHODS,
    AdapterRegistrationError,
    AdapterUnavailable,
    CapabilityNegotiationError,
    DeterministicFakePort,
    HealthStatus,
    IdempotencyConflict,
    Outcome,
    PortCall,
    PortContractError,
    PortRegistry,
    PortResult,
    SCMPort,
    SideEffect,
    negotiate_descriptor,
)
from core.schema_validation import validate_schema

ROOT = Path(__file__).resolve().parents[1]


class FakeClock:
    def __init__(self, value: float = 1_786_425_600.0) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


def descriptor_all_ports() -> dict:
    descriptor = json.loads(
        (ROOT / "examples/v08-contracts/valid/adapter-descriptor.json").read_text(
            encoding="utf-8"
        )
    )
    descriptor["ports"] = list(PORT_METHODS)
    descriptor["capabilities"] = [f"cap.{port}" for port in PORT_METHODS]
    descriptor["idempotency"] = [
        {"port": port, "mode": "provider-key"} for port in PORT_METHODS
    ]
    return descriptor


def call(
    clock: FakeClock,
    *,
    request_id: str = "request-example-1",
    key: str = "idempotency-example-1",
    payload: dict | None = None,
) -> PortCall:
    return PortCall(
        request_id=request_id,
        operation="example.execute",
        idempotency_key=key,
        correlation_id="work-example-1",
        deadline_epoch=clock() + 60,
        payload=payload or {"work_item_id": "work-example-1"},
    )


class V08AdapterPortTests(unittest.TestCase):
    def test_capability_report_schema_accepts_examples_and_generated_gaps(self) -> None:
        schema = json.loads(
            (ROOT / "schemas/capability-report.schema.json").read_text(encoding="utf-8")
        )
        example = json.loads(
            (ROOT / "examples/v08-contracts/valid/capability-report.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(validate_schema(example, schema), [])
        missing = negotiate_descriptor(
            descriptor_all_ports(),
            port="scm",
            required_capabilities=frozenset({"draft-pr.create"}),
        )
        self.assertEqual(validate_schema(missing.to_dict(), schema), [])

    def test_all_ten_ports_require_explicit_registration_and_binding(self) -> None:
        clock = FakeClock()
        descriptor = descriptor_all_ports()
        implementations = {
            port: DeterministicFakePort(
                descriptor["adapter_id"],
                port,
                frozenset({f"cap.{port}"}),
                clock=clock,
            )
            for port in PORT_METHODS
        }
        registry = PortRegistry()
        registry.register(descriptor, implementations)
        for index, port in enumerate(PORT_METHODS, start=1):
            binding = registry.bind(
                port=port,
                adapter_id=descriptor["adapter_id"],
                required_capabilities=frozenset({f"cap.{port}"}),
            )
            result = binding.invoke(
                call(
                    clock,
                    request_id=f"request-port-{index}",
                    key=f"idempotency-port-{index}",
                )
            )
            self.assertEqual(result.outcome, Outcome.SUCCEEDED)
            self.assertEqual(result.data["port"], port)
        self.assertEqual(len(registry.capability_reports()), len(PORT_METHODS))

    def test_descriptor_capability_and_version_gaps_are_machine_readable(self) -> None:
        descriptor = descriptor_all_ports()
        missing = negotiate_descriptor(
            descriptor,
            port="scm",
            required_capabilities=frozenset({"draft-pr.create"}),
        )
        self.assertFalse(missing.accepted)
        self.assertEqual(missing.missing_capabilities, ("draft-pr.create",))
        self.assertIn("missing capabilities", missing.errors[0])

        incompatible = negotiate_descriptor(
            descriptor,
            port="scm",
            required_capabilities=frozenset(),
            core_version="2.0.0",
        )
        self.assertFalse(incompatible.accepted)
        self.assertIn("outside", incompatible.errors[0])

    def test_binding_rechecks_runtime_health_capabilities(self) -> None:
        descriptor = descriptor_all_ports()
        clock = FakeClock()
        fake = DeterministicFakePort(
            descriptor["adapter_id"], "scm", frozenset(), clock=clock
        )
        implementations = {
            port: (
                fake
                if port == "scm"
                else DeterministicFakePort(
                    descriptor["adapter_id"],
                    port,
                    frozenset({f"cap.{port}"}),
                    clock=clock,
                )
            )
            for port in PORT_METHODS
        }
        registry = PortRegistry()
        registry.register(descriptor, implementations)
        with self.assertRaises(CapabilityNegotiationError) as raised:
            registry.bind(
                port="scm",
                adapter_id=descriptor["adapter_id"],
                required_capabilities=frozenset({"cap.scm"}),
            )
        self.assertEqual(raised.exception.report.missing_capabilities, ("cap.scm",))

        fake.capabilities = frozenset({"cap.scm"})
        fake.health_status = HealthStatus.UNAVAILABLE
        with self.assertRaises(AdapterUnavailable):
            registry.bind(
                port="scm",
                adapter_id=descriptor["adapter_id"],
                required_capabilities=frozenset({"cap.scm"}),
            )

    def test_registration_is_exact_and_does_not_load_manifest_code(self) -> None:
        descriptor = descriptor_all_ports()
        descriptor["external_product"] = {
            "name": "Untrusted metadata only",
            "version": "1",
            "api_version": "import os",
        }
        with self.assertRaises(AdapterRegistrationError):
            PortRegistry().register(descriptor, {})

        incomplete = {
            port: DeterministicFakePort(
                descriptor["adapter_id"], port, frozenset({f"cap.{port}"})
            )
            for port in list(PORT_METHODS)[:-1]
        }
        with self.assertRaises(AdapterRegistrationError):
            PortRegistry().register(descriptor, incomplete)

    def test_idempotency_replay_returns_the_original_result_and_detects_conflict(self) -> None:
        clock = FakeClock()
        fake = DeterministicFakePort(
            "adapter.native-mock", "scm", frozenset({"draft-pr.create"}), clock=clock
        )
        first = fake.apply(call(clock))
        replay = fake.apply(call(clock, request_id="request-example-2"))
        self.assertIs(first, replay)
        with self.assertRaises(IdempotencyConflict):
            fake.apply(
                call(
                    clock,
                    request_id="request-example-3",
                    payload={"work_item_id": "work-different"},
                )
            )

    def test_retryable_failure_can_retry_but_unknown_effect_is_stable(self) -> None:
        clock = FakeClock()
        fake = DeterministicFakePort(
            "adapter.native-mock", "scm", frozenset({"draft-pr.create"}), clock=clock
        )
        fake.script(
            PortResult.failed(
                Outcome.RETRYABLE_FAILURE,
                "PROVIDER_UNAVAILABLE",
                retry_after_seconds=2,
            )
        )
        self.assertEqual(fake.apply(call(clock)).outcome, Outcome.RETRYABLE_FAILURE)
        self.assertEqual(
            fake.apply(call(clock, request_id="request-example-2")).outcome,
            Outcome.SUCCEEDED,
        )

        unknown = PortResult.failed(
            Outcome.UNKNOWN,
            "SIDE_EFFECT_UNKNOWN",
            side_effect=SideEffect.UNKNOWN,
        )
        fake.script(unknown)
        uncertain_call = call(
            clock,
            request_id="request-unknown-1",
            key="idempotency-unknown-1",
        )
        self.assertIs(fake.apply(uncertain_call), unknown)
        self.assertIs(
            fake.apply(
                call(
                    clock,
                    request_id="request-unknown-2",
                    key="idempotency-unknown-1",
                )
            ),
            unknown,
        )

    def test_timeout_and_cancellation_do_not_attempt_a_side_effect(self) -> None:
        clock = FakeClock()
        fake = DeterministicFakePort(
            "adapter.native-mock", "agent-executor", frozenset({"agent.execute"}), clock=clock
        )
        expired = call(clock, request_id="request-expired-1", key="idempotency-expired-1")
        clock.advance(61)
        timeout = fake.execute(expired)
        self.assertEqual(timeout.outcome, Outcome.RETRYABLE_FAILURE)
        self.assertEqual(timeout.side_effect, SideEffect.NOT_ATTEMPTED)

        current = call(clock, request_id="request-cancelled-1", key="idempotency-cancel-1")
        self.assertTrue(fake.cancel(current.request_id))
        cancelled = fake.execute(current)
        self.assertEqual(cancelled.outcome, Outcome.CANCELLED)
        self.assertEqual(cancelled.side_effect, SideEffect.NOT_ATTEMPTED)

    def test_inline_secrets_and_invalid_results_are_rejected_at_the_port(self) -> None:
        clock = FakeClock()
        with self.assertRaises(PortContractError):
            call(clock, payload={"api_key": "do-not-pass-inline"})
        with self.assertRaises(PortContractError):
            call(clock, payload={"cost": float("nan")})
        with self.assertRaises(PortContractError):
            PortCall(
                request_id="request-invalid-deadline",
                operation="example.execute",
                idempotency_key="idempotency-invalid-deadline",
                correlation_id="work-example-1",
                deadline_epoch=float("nan"),
                payload={},
            )
        with self.assertRaises(PortContractError):
            PortResult(
                outcome=Outcome.SUCCEEDED,
                data={},
                side_effect=SideEffect.UNKNOWN,
            )
        with self.assertRaises(PortContractError):
            PortResult.failed(Outcome.PERMANENT_FAILURE, "lowercase-error")

    def test_protocol_shape_and_explicit_rebinding(self) -> None:
        descriptor = descriptor_all_ports()
        clock = FakeClock()
        implementations = {
            port: DeterministicFakePort(
                descriptor["adapter_id"], port, frozenset({f"cap.{port}"}), clock=clock
            )
            for port in PORT_METHODS
        }
        self.assertIsInstance(implementations["scm"], SCMPort)
        registry = PortRegistry()
        registry.register(descriptor, implementations)
        registry.bind(
            port="scm",
            adapter_id=descriptor["adapter_id"],
            required_capabilities=frozenset({"cap.scm"}),
        )
        with self.assertRaises(AdapterRegistrationError):
            registry.bind(
                port="scm",
                adapter_id=descriptor["adapter_id"],
                required_capabilities=frozenset({"cap.scm"}),
            )
        registry.unbind("scm")
        registry.bind(
            port="scm",
            adapter_id=descriptor["adapter_id"],
            required_capabilities=frozenset({"cap.scm"}),
        )


if __name__ == "__main__":
    unittest.main()
