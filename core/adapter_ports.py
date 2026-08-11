"""v0.8 replaceable port SDK, explicit binding, and capability negotiation.

The SDK has no dynamic plugin loader and imports no external platform package.
Trusted composition code registers concrete objects explicitly; the controller
receives only narrow port methods and sanitized JSON calls/results.
"""

from __future__ import annotations

import math
import re
import time
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Callable, Protocol, runtime_checkable

from core.contracts import canonical_json, digest_value, require_contract
from core.json_support import loads_strict
from core.security import find_inline_secret

MAX_PORT_JSON_BYTES = 1_000_000
CORE_CONTRACT_VERSION = "1.0.0"

PORT_METHODS = {
    "ingress": "receive",
    "identity": "verify",
    "scm": "apply",
    "agent-executor": "execute",
    "sandbox": "run",
    "ci": "check",
    "state-store": "transact",
    "evidence": "record",
    "notification": "notify",
    "secret": "lease",
}


class AdapterSDKError(RuntimeError):
    code = "ADAPTER_SDK_ERROR"


class AdapterRegistrationError(AdapterSDKError):
    code = "ADAPTER_REGISTRATION_INVALID"


class CapabilityNegotiationError(AdapterSDKError):
    code = "ADAPTER_CAPABILITY_MISMATCH"

    def __init__(self, report: "CapabilityReport") -> None:
        self.report = report
        super().__init__("; ".join(report.errors) or "adapter capability negotiation failed")


class AdapterUnavailable(AdapterSDKError):
    code = "ADAPTER_UNAVAILABLE"


class IdempotencyConflict(AdapterSDKError):
    code = "ADAPTER_IDEMPOTENCY_CONFLICT"


class PortContractError(AdapterSDKError):
    code = "ADAPTER_PORT_CONTRACT_INVALID"


class Outcome(StrEnum):
    SUCCEEDED = "SUCCEEDED"
    RETRYABLE_FAILURE = "RETRYABLE_FAILURE"
    PERMANENT_FAILURE = "PERMANENT_FAILURE"
    UNKNOWN = "UNKNOWN"
    CANCELLED = "CANCELLED"


class SideEffect(StrEnum):
    NONE = "NONE"
    NOT_ATTEMPTED = "NOT_ATTEMPTED"
    APPLIED = "APPLIED"
    UNKNOWN = "UNKNOWN"


class HealthStatus(StrEnum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    UNAVAILABLE = "UNAVAILABLE"


def _portable_object(value: dict[str, Any], label: str) -> dict[str, Any]:
    secret_path = find_inline_secret(value)
    if secret_path is not None:
        raise PortContractError(f"{label} contains inline secret-like data at {secret_path}")
    try:
        encoded = canonical_json(value).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise PortContractError(f"{label} is not strict JSON: {exc}") from exc
    if len(encoded) > MAX_PORT_JSON_BYTES:
        raise PortContractError(f"{label} exceeds the 1 MiB limit")
    copied = loads_strict(encoded)
    if not isinstance(copied, dict):
        raise PortContractError(f"{label} must be an object")
    return copied


@dataclass(frozen=True)
class PortCall:
    request_id: str
    operation: str
    idempotency_key: str
    correlation_id: str
    deadline_epoch: float
    payload: dict[str, Any]

    def __post_init__(self) -> None:
        if re.fullmatch(r"request-[a-z0-9][a-z0-9-]*", self.request_id) is None:
            raise PortContractError("request_id is invalid")
        if re.fullmatch(r"[a-z][a-z0-9.-]*", self.operation) is None:
            raise PortContractError("operation is invalid")
        if not 8 <= len(self.idempotency_key) <= 200:
            raise PortContractError("idempotency_key must contain 8-200 characters")
        if not self.correlation_id or len(self.correlation_id) > 200:
            raise PortContractError("correlation_id is invalid")
        if (
            not isinstance(self.deadline_epoch, (int, float))
            or isinstance(self.deadline_epoch, bool)
            or not math.isfinite(self.deadline_epoch)
            or self.deadline_epoch <= 0
        ):
            raise PortContractError("deadline_epoch must be positive")
        object.__setattr__(self, "payload", _portable_object(self.payload, "port call payload"))

    @property
    def binding_digest(self) -> str:
        return digest_value({"operation": self.operation, "payload": self.payload})


@dataclass(frozen=True)
class PortResult:
    outcome: Outcome
    data: dict[str, Any]
    side_effect: SideEffect
    provider_ref: str | None = None
    evidence_refs: tuple[str, ...] = ()
    error_code: str | None = None
    retry_after_seconds: int | None = None
    reconciled: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "data", _portable_object(self.data, "port result data"))
        metadata = {
            "provider_ref": self.provider_ref,
            "evidence_refs": list(self.evidence_refs),
        }
        secret_path = find_inline_secret(metadata)
        if secret_path is not None:
            raise PortContractError(f"port result metadata contains secret-like data at {secret_path}")
        if self.provider_ref is not None and len(self.provider_ref) > 1000:
            raise PortContractError("provider_ref exceeds 1000 characters")
        if any(not value or len(value) > 1000 for value in self.evidence_refs):
            raise PortContractError("evidence references must contain 1-1000 characters")
        if self.error_code is not None and re.fullmatch(r"[A-Z][A-Z0-9_]*", self.error_code) is None:
            raise PortContractError("error_code must be stable uppercase code")
        if self.outcome == Outcome.SUCCEEDED:
            if self.error_code is not None or self.side_effect == SideEffect.UNKNOWN:
                raise PortContractError("successful results cannot carry an error or unknown effect")
        elif self.error_code is None:
            raise PortContractError("non-success result requires error_code")
        if self.outcome == Outcome.UNKNOWN and self.side_effect != SideEffect.UNKNOWN:
            raise PortContractError("UNKNOWN outcome requires UNKNOWN side effect")
        if self.side_effect == SideEffect.APPLIED and self.outcome != Outcome.SUCCEEDED:
            raise PortContractError("an applied side effect must be reported as success")
        if self.retry_after_seconds is not None:
            if (
                self.outcome != Outcome.RETRYABLE_FAILURE
                or isinstance(self.retry_after_seconds, bool)
                or self.retry_after_seconds < 0
            ):
                raise PortContractError("retry_after_seconds is valid only for retryable failures")

    @classmethod
    def succeeded(
        cls,
        data: dict[str, Any],
        *,
        side_effect: SideEffect = SideEffect.NONE,
        provider_ref: str | None = None,
        evidence_refs: tuple[str, ...] = (),
        reconciled: bool = False,
    ) -> "PortResult":
        return cls(
            outcome=Outcome.SUCCEEDED,
            data=data,
            side_effect=side_effect,
            provider_ref=provider_ref,
            evidence_refs=evidence_refs,
            reconciled=reconciled,
        )

    @classmethod
    def failed(
        cls,
        outcome: Outcome,
        error_code: str,
        *,
        side_effect: SideEffect = SideEffect.NOT_ATTEMPTED,
        retry_after_seconds: int | None = None,
    ) -> "PortResult":
        if outcome == Outcome.SUCCEEDED:
            raise PortContractError("failed result cannot use SUCCEEDED")
        return cls(
            outcome=outcome,
            data={},
            side_effect=side_effect,
            error_code=error_code,
            retry_after_seconds=retry_after_seconds,
        )


@dataclass(frozen=True)
class HealthReport:
    adapter_id: str
    status: HealthStatus
    capabilities: frozenset[str]
    checked_at_epoch: float
    detail_code: str | None = None


@dataclass(frozen=True)
class CapabilityReport:
    accepted: bool
    adapter_id: str
    adapter_version: str
    port: str
    requested_core_version: str
    minimum_core_version: str
    maximum_core_version_exclusive: str
    required_capabilities: tuple[str, ...]
    provided_capabilities: tuple[str, ...]
    missing_capabilities: tuple[str, ...]
    limitations: tuple[str, ...]
    errors: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "accepted": self.accepted,
            "adapter_id": self.adapter_id,
            "adapter_version": self.adapter_version,
            "port": self.port,
            "requested_core_version": self.requested_core_version,
            "minimum_core_version": self.minimum_core_version,
            "maximum_core_version_exclusive": self.maximum_core_version_exclusive,
            "required_capabilities": list(self.required_capabilities),
            "provided_capabilities": list(self.provided_capabilities),
            "missing_capabilities": list(self.missing_capabilities),
            "limitations": list(self.limitations),
            "errors": list(self.errors),
        }


def _semver(value: str) -> tuple[int, int, int]:
    match = re.fullmatch(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)", value)
    if match is None:
        raise PortContractError(f"invalid semantic version: {value}")
    return tuple(int(part) for part in match.groups())  # type: ignore[return-value]


def negotiate_descriptor(
    descriptor: dict[str, Any],
    *,
    port: str,
    required_capabilities: frozenset[str],
    core_version: str = CORE_CONTRACT_VERSION,
) -> CapabilityReport:
    require_contract("adapter_descriptor", descriptor)
    minimum = str(descriptor["core_contract_versions"]["minimum"])
    maximum = str(descriptor["core_contract_versions"]["maximum_exclusive"])
    requested = _semver(core_version)
    errors: list[str] = []
    if not _semver(minimum) <= requested < _semver(maximum):
        errors.append(
            f"core version {core_version} is outside [{minimum}, {maximum})"
        )
    declared_ports = set(str(value) for value in descriptor["ports"])
    if port not in PORT_METHODS:
        errors.append(f"unknown core port: {port}")
    elif port not in declared_ports:
        errors.append(f"adapter does not implement port: {port}")
    provided = frozenset(str(value) for value in descriptor["capabilities"])
    missing = sorted(required_capabilities - provided)
    if missing:
        errors.append(f"missing capabilities: {', '.join(missing)}")
    return CapabilityReport(
        accepted=not errors,
        adapter_id=str(descriptor["adapter_id"]),
        adapter_version=str(descriptor["adapter_version"]),
        port=port,
        requested_core_version=core_version,
        minimum_core_version=minimum,
        maximum_core_version_exclusive=maximum,
        required_capabilities=tuple(sorted(required_capabilities)),
        provided_capabilities=tuple(sorted(provided)),
        missing_capabilities=tuple(missing),
        limitations=tuple(str(value) for value in descriptor["limitations"]),
        errors=tuple(errors),
    )


@runtime_checkable
class IngressPort(Protocol):
    def health(self) -> HealthReport: ...
    def receive(self, call: PortCall) -> PortResult: ...
    def cancel(self, request_id: str) -> bool: ...


@runtime_checkable
class IdentityPort(Protocol):
    def health(self) -> HealthReport: ...
    def verify(self, call: PortCall) -> PortResult: ...
    def cancel(self, request_id: str) -> bool: ...


@runtime_checkable
class SCMPort(Protocol):
    def health(self) -> HealthReport: ...
    def apply(self, call: PortCall) -> PortResult: ...
    def cancel(self, request_id: str) -> bool: ...


@runtime_checkable
class AgentExecutorPort(Protocol):
    def health(self) -> HealthReport: ...
    def execute(self, call: PortCall) -> PortResult: ...
    def cancel(self, request_id: str) -> bool: ...


@runtime_checkable
class SandboxPort(Protocol):
    def health(self) -> HealthReport: ...
    def run(self, call: PortCall) -> PortResult: ...
    def cancel(self, request_id: str) -> bool: ...


@runtime_checkable
class CIPort(Protocol):
    def health(self) -> HealthReport: ...
    def check(self, call: PortCall) -> PortResult: ...
    def cancel(self, request_id: str) -> bool: ...


@runtime_checkable
class StateStorePort(Protocol):
    def health(self) -> HealthReport: ...
    def transact(self, call: PortCall) -> PortResult: ...
    def cancel(self, request_id: str) -> bool: ...


@runtime_checkable
class EvidencePort(Protocol):
    def health(self) -> HealthReport: ...
    def record(self, call: PortCall) -> PortResult: ...
    def cancel(self, request_id: str) -> bool: ...


@runtime_checkable
class NotificationPort(Protocol):
    def health(self) -> HealthReport: ...
    def notify(self, call: PortCall) -> PortResult: ...
    def cancel(self, request_id: str) -> bool: ...


@runtime_checkable
class SecretPort(Protocol):
    def health(self) -> HealthReport: ...
    def lease(self, call: PortCall) -> PortResult: ...
    def cancel(self, request_id: str) -> bool: ...


@dataclass(frozen=True)
class BoundPort:
    port: str
    adapter_id: str
    implementation: object
    capability_report: CapabilityReport

    def invoke(self, call: PortCall) -> PortResult:
        method = getattr(self.implementation, PORT_METHODS[self.port])
        result = method(call)
        if not isinstance(result, PortResult):
            raise PortContractError("adapter returned a value outside PortResult")
        return result

    def cancel(self, request_id: str) -> bool:
        return bool(getattr(self.implementation, "cancel")(request_id))


class PortRegistry:
    """Explicit trusted-composition registry; descriptors never load code."""

    def __init__(self) -> None:
        self._adapters: dict[str, tuple[dict[str, Any], dict[str, object]]] = {}
        self._bindings: dict[str, BoundPort] = {}

    def register(
        self,
        descriptor: dict[str, Any],
        implementations: dict[str, object],
    ) -> None:
        document = require_contract("adapter_descriptor", descriptor)
        adapter_id = str(document["adapter_id"])
        if adapter_id in self._adapters:
            raise AdapterRegistrationError(f"adapter is already registered: {adapter_id}")
        declared = set(str(value) for value in document["ports"])
        supplied = set(implementations)
        if supplied != declared:
            missing = sorted(declared - supplied)
            extra = sorted(supplied - declared)
            raise AdapterRegistrationError(
                f"implementation ports differ; missing={missing}, extra={extra}"
            )
        for port, implementation in implementations.items():
            if port not in PORT_METHODS:
                raise AdapterRegistrationError(f"unknown port implementation: {port}")
            for method in (PORT_METHODS[port], "health", "cancel"):
                if not callable(getattr(implementation, method, None)):
                    raise AdapterRegistrationError(
                        f"{adapter_id}:{port} does not implement {method}"
                    )
        copied = loads_strict(canonical_json(document).encode("utf-8"))
        self._adapters[adapter_id] = (copied, dict(implementations))

    def bind(
        self,
        *,
        port: str,
        adapter_id: str,
        required_capabilities: frozenset[str],
        core_version: str = CORE_CONTRACT_VERSION,
    ) -> BoundPort:
        if port in self._bindings:
            raise AdapterRegistrationError(f"port already has an explicit binding: {port}")
        try:
            descriptor, implementations = self._adapters[adapter_id]
        except KeyError as exc:
            raise AdapterRegistrationError(f"adapter is not registered: {adapter_id}") from exc
        report = negotiate_descriptor(
            descriptor,
            port=port,
            required_capabilities=required_capabilities,
            core_version=core_version,
        )
        if not report.accepted:
            raise CapabilityNegotiationError(report)
        implementation = implementations[port]
        health = implementation.health()  # type: ignore[attr-defined]
        if not isinstance(health, HealthReport) or health.adapter_id != adapter_id:
            raise AdapterUnavailable(f"invalid health report for {adapter_id}:{port}")
        if health.status == HealthStatus.UNAVAILABLE:
            raise AdapterUnavailable(f"adapter is unavailable: {adapter_id}:{port}")
        runtime_missing = required_capabilities - health.capabilities
        if runtime_missing:
            runtime_report = CapabilityReport(
                accepted=False,
                adapter_id=report.adapter_id,
                adapter_version=report.adapter_version,
                port=report.port,
                requested_core_version=report.requested_core_version,
                minimum_core_version=report.minimum_core_version,
                maximum_core_version_exclusive=report.maximum_core_version_exclusive,
                required_capabilities=report.required_capabilities,
                provided_capabilities=tuple(sorted(health.capabilities)),
                missing_capabilities=tuple(sorted(runtime_missing)),
                limitations=report.limitations,
                errors=(f"runtime health lacks: {', '.join(sorted(runtime_missing))}",),
            )
            raise CapabilityNegotiationError(runtime_report)
        binding = BoundPort(port, adapter_id, implementation, report)
        self._bindings[port] = binding
        return binding

    def get(self, port: str) -> BoundPort:
        try:
            return self._bindings[port]
        except KeyError as exc:
            raise AdapterRegistrationError(f"port is not bound: {port}") from exc

    def unbind(self, port: str) -> None:
        self._bindings.pop(port, None)

    def capability_reports(self) -> list[dict[str, Any]]:
        return [
            self._bindings[port].capability_report.to_dict()
            for port in sorted(self._bindings)
        ]


class DeterministicFakePort:
    """No-network test double with replay, timeout, cancellation, and fault scripting."""

    def __init__(
        self,
        adapter_id: str,
        port: str,
        capabilities: frozenset[str],
        *,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if port not in PORT_METHODS:
            raise AdapterRegistrationError(f"unknown fake port: {port}")
        self.adapter_id = adapter_id
        self.port = port
        self.capabilities = capabilities
        self.clock = clock
        self.health_status = HealthStatus.HEALTHY
        self.calls: list[PortCall] = []
        self.executions: list[PortCall] = []
        self._scripted: list[PortResult] = []
        self._stable: dict[str, tuple[str, PortResult]] = {}
        self._cancelled: set[str] = set()

    def script(self, result: PortResult) -> None:
        self._scripted.append(result)

    def health(self) -> HealthReport:
        return HealthReport(
            adapter_id=self.adapter_id,
            status=self.health_status,
            capabilities=self.capabilities,
            checked_at_epoch=float(self.clock()),
            detail_code=None if self.health_status == HealthStatus.HEALTHY else "FAKE_HEALTH",
        )

    def cancel(self, request_id: str) -> bool:
        self._cancelled.add(request_id)
        return True

    def _invoke(self, expected_port: str, call: PortCall) -> PortResult:
        if self.port != expected_port:
            raise AdapterRegistrationError(
                f"fake for {self.port} cannot execute the {expected_port} port"
            )
        self.calls.append(call)
        stable = self._stable.get(call.idempotency_key)
        if stable is not None:
            digest, result = stable
            if digest != call.binding_digest:
                raise IdempotencyConflict(
                    "the idempotency key was reused with a different operation or payload"
                )
            return result
        self.executions.append(call)
        if call.request_id in self._cancelled:
            result = PortResult.failed(Outcome.CANCELLED, "REQUEST_CANCELLED")
        elif call.deadline_epoch <= float(self.clock()):
            result = PortResult.failed(
                Outcome.RETRYABLE_FAILURE,
                "DEADLINE_EXCEEDED",
                retry_after_seconds=0,
            )
        elif self._scripted:
            result = self._scripted.pop(0)
        else:
            result = PortResult.succeeded(
                {
                    "adapter_id": self.adapter_id,
                    "port": self.port,
                    "operation": call.operation,
                    "request_digest": call.binding_digest,
                }
            )
        if result.outcome != Outcome.RETRYABLE_FAILURE:
            self._stable[call.idempotency_key] = (call.binding_digest, result)
        return result

    def receive(self, call: PortCall) -> PortResult:
        return self._invoke("ingress", call)

    def verify(self, call: PortCall) -> PortResult:
        return self._invoke("identity", call)

    def apply(self, call: PortCall) -> PortResult:
        return self._invoke("scm", call)

    def execute(self, call: PortCall) -> PortResult:
        return self._invoke("agent-executor", call)

    def run(self, call: PortCall) -> PortResult:
        return self._invoke("sandbox", call)

    def check(self, call: PortCall) -> PortResult:
        return self._invoke("ci", call)

    def transact(self, call: PortCall) -> PortResult:
        return self._invoke("state-store", call)

    def record(self, call: PortCall) -> PortResult:
        return self._invoke("evidence", call)

    def notify(self, call: PortCall) -> PortResult:
        return self._invoke("notification", call)

    def lease(self, call: PortCall) -> PortResult:
        return self._invoke("secret", call)
