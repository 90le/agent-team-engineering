"""Versioned adapter catalog, fail-closed host, and outbox worker."""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Protocol

from core.control_plane import ControlPlane
from core.json_support import loads_strict
from core.schema_validation import validate_schema
from core.security import find_inline_secret

ROOT = Path(__file__).resolve().parents[1]
ADAPTER_SCHEMA = ROOT / "schemas" / "adapter.schema.json"
REQUEST_SCHEMA = ROOT / "schemas" / "adapter-request.schema.json"
RESULT_SCHEMA = ROOT / "schemas" / "adapter-result.schema.json"
OUTBOX_SCHEMA = ROOT / "schemas" / "outbox-effect.schema.json"
AUDIT_SCHEMA = ROOT / "schemas" / "control-plane-audit.schema.json"
AUTHORITY_POLICY_SCHEMA = ROOT / "schemas" / "adapter-authority-policy.schema.json"
AUTHORITY_POLICY = ROOT / "policies" / "adapter-authority.json"
MAX_ADAPTER_JSON_BYTES = 1_000_000


class AdapterError(RuntimeError):
    code = "ADAPTER_ERROR"


class AdapterCatalogError(AdapterError):
    code = "ADAPTER_CATALOG_INVALID"


class AdapterDisabled(AdapterError):
    code = "ADAPTER_DISABLED"


class AdapterOperationDenied(AdapterError):
    code = "ADAPTER_OPERATION_DENIED"


class AdapterContractError(AdapterError):
    code = "ADAPTER_CONTRACT_INVALID"


class AdapterRetryableError(AdapterError):
    code = "ADAPTER_RETRYABLE_FAILURE"


class AdapterPermanentError(AdapterError):
    code = "ADAPTER_PERMANENT_FAILURE"


class AdapterClaimExpired(AdapterError):
    code = "ADAPTER_CLAIM_EXPIRED"


@dataclass(frozen=True)
class ProjectScope:
    match_by: str
    payload_field: str
    provider: str | None
    allowed_modes: frozenset[str]
    default_branch_field: str | None
    source_ref_field: str | None


@dataclass(frozen=True)
class OperationContract:
    name: str
    slots: frozenset[str]
    direction: str
    external_effect: str
    delivery: str
    capability: str
    input_schema: Path
    output_schema: Path
    timeout_seconds: int
    project_scope: ProjectScope | None


@dataclass(frozen=True)
class AdapterManifest:
    adapter_id: str
    version: str
    kind: str
    status: str
    slots: frozenset[str]
    config_schema: Path
    operations: dict[str, OperationContract]
    trust_boundaries: frozenset[str]
    credentials: frozenset[str]
    implementation_mode: str
    entrypoint: str | None
    source: Path

    def summary(self) -> dict[str, Any]:
        return {
            "id": self.adapter_id,
            "version": self.version,
            "kind": self.kind,
            "status": self.status,
            "slots": sorted(self.slots),
            "operations": [
                {
                    "name": operation.name,
                    "slots": sorted(operation.slots),
                    "direction": operation.direction,
                    "external_effect": operation.external_effect,
                    "delivery": operation.delivery,
                    "capability": operation.capability,
                    "project_scoped": operation.project_scope is not None,
                }
                for operation in (self.operations[name] for name in sorted(self.operations))
            ],
            "implementation_mode": self.implementation_mode,
            "credentials": sorted(self.credentials),
        }


@dataclass(frozen=True)
class AdapterBindingIssue:
    path: str
    message: str


class SecretResolver(Protocol):
    def resolve(self, reference: str) -> bytes: ...


class DenySecretResolver:
    def resolve(self, reference: str) -> bytes:
        raise AdapterOperationDenied(f"secret resolution is disabled: {reference}")


class MappingSecretResolver:
    """In-memory test resolver; production adapters should use a secret manager."""

    def __init__(self, values: dict[str, bytes]) -> None:
        self._values = dict(values)

    def resolve(self, reference: str) -> bytes:
        try:
            return self._values[reference]
        except KeyError as exc:
            raise AdapterOperationDenied(f"secret reference is unavailable: {reference}") from exc


@dataclass(frozen=True)
class AdapterContext:
    instance_id: str
    binding_config: dict[str, Any]
    allowed_secret_refs: frozenset[str]
    _resolver: SecretResolver

    def resolve_secret(self, reference: str) -> bytes:
        if reference not in self.allowed_secret_refs:
            raise AdapterOperationDenied("adapter requested a secret outside its binding")
        return self._resolver.resolve(reference)


class Adapter(Protocol):
    adapter_id: str

    def execute(self, request: dict[str, Any], context: AdapterContext) -> dict[str, Any]: ...

    def reconcile(
        self, request: dict[str, Any], context: AdapterContext
    ) -> dict[str, Any] | None: ...


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = loads_strict(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise AdapterCatalogError(f"cannot load JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise AdapterCatalogError(f"JSON root must be an object: {path}")
    return value


def _schema_path(relative: str, root: Path = ROOT) -> Path:
    path = (root / relative).resolve()
    schema_root = (root / "schemas").resolve()
    if schema_root not in path.parents or not path.is_file():
        raise AdapterCatalogError(f"adapter schema reference is unsafe or missing: {relative}")
    _load_json(path)
    return path


def load_adapter_catalog(root: Path = ROOT) -> dict[str, AdapterManifest]:
    schema = _load_json(root / ADAPTER_SCHEMA.relative_to(ROOT))
    catalog: dict[str, AdapterManifest] = {}
    for path in sorted((root / "adapters").glob("*/adapter.json")):
        document = _load_json(path)
        issues = validate_schema(document, schema)
        if issues:
            details = "; ".join(f"{issue.path}: {issue.message}" for issue in issues)
            raise AdapterCatalogError(f"invalid adapter manifest {path}: {details}")
        adapter_id = str(document["id"])
        if adapter_id in catalog:
            raise AdapterCatalogError(f"duplicate adapter id: {adapter_id}")
        operations: dict[str, OperationContract] = {}
        manifest_slots = frozenset(str(slot) for slot in document["slots"])
        for record in document["operations"]:
            name = str(record["name"])
            if name in operations:
                raise AdapterCatalogError(f"duplicate operation {adapter_id}:{name}")
            if record["external_effect"] == "write" and record["delivery"] not in {
                "provider-idempotency",
                "reconcile-before-retry",
                "at-most-once",
            }:
                raise AdapterCatalogError(
                    f"write operation {adapter_id}:{name} lacks bounded delivery"
                )
            if record["delivery"] == "read-only" and record["external_effect"] != "read":
                raise AdapterCatalogError(
                    f"read-only delivery differs from effect type for {adapter_id}:{name}"
                )
            operation_slots = frozenset(str(slot) for slot in record["slots"])
            if not operation_slots <= manifest_slots:
                raise AdapterCatalogError(
                    f"operation slots exceed adapter slots for {adapter_id}:{name}"
                )
            scope_record = record["project_scope"]
            project_scope = (
                ProjectScope(
                    match_by=str(scope_record["match_by"]),
                    payload_field=str(scope_record["payload_field"]),
                    provider=(
                        str(scope_record["provider"])
                        if scope_record["provider"] is not None
                        else None
                    ),
                    allowed_modes=frozenset(str(mode) for mode in scope_record["allowed_modes"]),
                    default_branch_field=(
                        str(scope_record["default_branch_field"])
                        if scope_record["default_branch_field"] is not None
                        else None
                    ),
                    source_ref_field=(
                        str(scope_record["source_ref_field"])
                        if scope_record["source_ref_field"] is not None
                        else None
                    ),
                )
                if isinstance(scope_record, dict)
                else None
            )
            operations[name] = OperationContract(
                name=name,
                slots=operation_slots,
                direction=str(record["direction"]),
                external_effect=str(record["external_effect"]),
                delivery=str(record["delivery"]),
                capability=str(record["capability"]),
                input_schema=_schema_path(str(record["input_schema"]), root),
                output_schema=_schema_path(str(record["output_schema"]), root),
                timeout_seconds=int(record["timeout_seconds"]),
                project_scope=project_scope,
            )
        implementation = document["implementation"]
        entrypoint = implementation["entrypoint"]
        if implementation["mode"] == "contract-only" and entrypoint is not None:
            raise AdapterCatalogError(f"contract-only adapter has an entrypoint: {adapter_id}")
        if implementation["mode"] == "python-reference" and not entrypoint:
            raise AdapterCatalogError(f"reference adapter lacks an entrypoint: {adapter_id}")
        catalog[adapter_id] = AdapterManifest(
            adapter_id=adapter_id,
            version=str(document["version"]),
            kind=str(document["kind"]),
            status=str(document["status"]),
            slots=manifest_slots,
            config_schema=_schema_path(str(document["config_schema"]), root),
            operations=operations,
            trust_boundaries=frozenset(str(boundary) for boundary in document["trust_boundaries"]),
            credentials=frozenset(str(value) for value in document["credentials"]),
            implementation_mode=str(implementation["mode"]),
            entrypoint=str(entrypoint) if entrypoint else None,
            source=path,
        )
    if not catalog:
        raise AdapterCatalogError("adapter catalog is empty")
    return catalog


def validate_instance_adapter_bindings(
    instance: dict[str, Any], catalog: dict[str, AdapterManifest] | None = None
) -> list[AdapterBindingIssue]:
    available = catalog or load_adapter_catalog()
    errors: list[AdapterBindingIssue] = []
    for index, binding in enumerate(instance.get("adapters", [])):
        adapter_id = binding.get("adapter_id")
        slot = binding.get("slot")
        manifest = available.get(adapter_id)
        if manifest is None:
            errors.append(
                AdapterBindingIssue(
                    f"$.adapters[{index}].adapter_id",
                    f"unknown adapter {adapter_id}",
                )
            )
        elif slot not in manifest.slots:
            errors.append(
                AdapterBindingIssue(
                    f"$.adapters[{index}].slot",
                    f"adapter {adapter_id} does not support {slot}",
                )
            )
        else:
            config_schema = _load_json(manifest.config_schema)
            for issue in validate_schema(binding.get("config"), config_schema):
                suffix = issue.path.removeprefix("$")
                errors.append(
                    AdapterBindingIssue(
                        f"$.adapters[{index}].config{suffix}",
                        issue.message,
                    )
                )
    return errors


def _validate_document(value: dict[str, Any], schema_path: Path, label: str) -> None:
    schema = _load_json(schema_path)
    issues = validate_schema(value, schema)
    if issues:
        details = "; ".join(f"{issue.path}: {issue.message}" for issue in issues)
        raise AdapterContractError(f"{label} violates contract: {details}")


def _bounded_json(value: Any) -> None:
    try:
        content = json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise AdapterContractError(f"adapter value is not JSON serializable: {exc}") from exc
    if len(content) > MAX_ADAPTER_JSON_BYTES:
        raise AdapterContractError("adapter request or result exceeds 1 MiB")


def _safe_json_copy(value: Any, *, label: str) -> Any:
    try:
        content = json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError) as exc:
        raise AdapterCatalogError(f"{label} is not strict JSON: {exc}") from exc
    if len(content.encode("utf-8")) > MAX_ADAPTER_JSON_BYTES:
        raise AdapterCatalogError(f"{label} exceeds 1 MiB")
    return loads_strict(content)


class AdapterHost:
    """Binds explicit implementations to one validated team instance."""

    def __init__(
        self,
        instance: dict[str, Any],
        implementations: list[Adapter],
        *,
        catalog: dict[str, AdapterManifest] | None = None,
        secret_resolver: SecretResolver | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.instance = _safe_json_copy(instance, label="adapter host instance")
        self.catalog = catalog or load_adapter_catalog()
        from core.instance import validate_instance_document

        instance_errors = [
            finding
            for finding in validate_instance_document(self.instance)
            if finding.severity == "ERROR"
        ]
        if instance_errors:
            details = "; ".join(f"{finding.path}: {finding.message}" for finding in instance_errors)
            raise AdapterCatalogError(f"instance is invalid: {details}")
        binding_errors = validate_instance_adapter_bindings(self.instance, self.catalog)
        if binding_errors:
            raise AdapterCatalogError(
                "; ".join(f"{issue.path}: {issue.message}" for issue in binding_errors)
            )
        self.implementations: dict[str, Adapter] = {}
        for adapter in implementations:
            if adapter.adapter_id in self.implementations:
                raise AdapterCatalogError(f"duplicate adapter implementation: {adapter.adapter_id}")
            self.implementations[adapter.adapter_id] = adapter
        self.secret_resolver = secret_resolver or DenySecretResolver()
        self.clock = clock
        self.authority_policy = _load_json(AUTHORITY_POLICY)
        _validate_document(
            self.authority_policy,
            AUTHORITY_POLICY_SCHEMA,
            "adapter authority policy",
        )

    def _binding(self, slot: str) -> dict[str, Any]:
        for binding in self.instance["adapters"]:
            if binding["slot"] == slot and binding["enabled"]:
                return binding
        raise AdapterDisabled(f"no enabled adapter is bound to slot {slot}")

    def _result(
        self,
        value: dict[str, Any],
        operation: OperationContract,
        *,
        reconciled: bool | None = None,
    ) -> dict[str, Any]:
        if reconciled is not None:
            value = {**value, "reconciled": reconciled}
        _bounded_json(value)
        secret_path = find_inline_secret(value)
        if secret_path:
            raise AdapterContractError(f"adapter result contains an inline secret at {secret_path}")
        _validate_document(value, RESULT_SCHEMA, "adapter result")
        if value["status"] == "SUCCEEDED":
            if value["error_code"] is not None:
                raise AdapterContractError("successful adapter result cannot contain error_code")
            _validate_document(value["output"], operation.output_schema, "adapter output")
            if value["external_ref"] != value["output"].get("external_ref"):
                raise AdapterContractError("adapter result external_ref differs from its output")
        elif value["error_code"] is None:
            raise AdapterContractError("failed adapter result requires a stable error_code")
        return value

    def _require_authority(
        self,
        effect: dict[str, Any],
        operation: OperationContract,
        authorization_event: dict[str, Any],
    ) -> None:
        _validate_document(authorization_event, AUDIT_SCHEMA, "authorization audit event")
        if (
            authorization_event["sequence"] != effect["authorization_event_sequence"]
            or authorization_event["work_item_id"] != effect["work_item_id"]
        ):
            raise AdapterOperationDenied(
                "adapter effect does not match its durable authorization event"
            )
        action = None
        if authorization_event["event_kind"] == "workflow.transition":
            action = authorization_event["data"].get("transition", {}).get("action")
        for grant in self.authority_policy["grants"]:
            if (
                grant["operation"] == operation.name
                and grant["capability"] == operation.capability
                and grant["event_kind"] == authorization_event["event_kind"]
            ):
                actions = grant["actions"]
                if authorization_event["event_kind"] == "work.created" and not actions:
                    return
                if action and (action in actions or "*" in actions):
                    return
        raise AdapterOperationDenied(
            "durable event does not grant the adapter operation capability"
        )

    def _require_project_scope(
        self,
        operation: OperationContract,
        payload: dict[str, Any],
    ) -> None:
        scope = operation.project_scope
        if scope is None:
            return
        target = payload.get(scope.payload_field)
        if not isinstance(target, str):
            raise AdapterOperationDenied("adapter payload lacks its project scope field")
        project = None
        for candidate in self.instance["projects"]:
            candidate_value = candidate["id"] if scope.match_by == "id" else candidate["locator"]
            if candidate_value != target:
                continue
            if scope.provider is not None and candidate["provider"] != scope.provider:
                continue
            project = candidate
            break
        if project is None:
            raise AdapterOperationDenied("adapter target is not declared by this team instance")
        if project["mode"] not in scope.allowed_modes:
            raise AdapterOperationDenied(
                "adapter operation is not allowed by the declared project mode"
            )
        if scope.default_branch_field is not None:
            if payload.get(scope.default_branch_field) != project["default_branch"]:
                raise AdapterOperationDenied(
                    "adapter operation base branch differs from the declared project"
                )
        if scope.source_ref_field is not None:
            source_ref = payload.get(scope.source_ref_field)
            expected_prefix = f"project-source:{project['id']}@"
            if not isinstance(source_ref, str) or not source_ref.startswith(expected_prefix):
                raise AdapterOperationDenied(
                    "runner source reference differs from the declared project"
                )

    def dispatch(
        self,
        effect: dict[str, Any],
        authorization_event: dict[str, Any],
    ) -> dict[str, Any]:
        _validate_document(effect, OUTBOX_SCHEMA, "outbox effect")
        if (
            effect["state"] != "CLAIMED"
            or effect["claim_owner"] is None
            or effect["claim_token"] is None
            or effect["claim_expires_at"] is None
        ):
            raise AdapterOperationDenied("adapter dispatch requires an active outbox claim")
        now = self.clock()
        if float(effect["claim_expires_at"]) <= now:
            raise AdapterClaimExpired("outbox claim expired before adapter dispatch")
        binding = self._binding(str(effect["adapter_slot"]))
        adapter_id = str(binding["adapter_id"])
        manifest = self.catalog[adapter_id]
        operation = manifest.operations.get(str(effect["operation"]))
        if (
            operation is None
            or operation.direction != "outbound"
            or effect["adapter_slot"] not in operation.slots
        ):
            raise AdapterOperationDenied(
                f"adapter {adapter_id} does not expose outbound {effect['operation']}"
            )
        self._require_authority(effect, operation, authorization_event)
        implementation = self.implementations.get(adapter_id)
        if implementation is None:
            raise AdapterDisabled(f"no explicitly registered implementation for {adapter_id}")
        if implementation.adapter_id != adapter_id:
            raise AdapterCatalogError("adapter implementation identity differs from its binding")
        _bounded_json(effect["payload"])
        secret_path = find_inline_secret(effect["payload"])
        if secret_path:
            raise AdapterContractError(
                f"adapter payload contains an inline secret at {secret_path}"
            )
        _validate_document(effect["payload"], operation.input_schema, "adapter input")
        self._require_project_scope(operation, effect["payload"])

        attempt = int(effect["attempts"])
        if operation.delivery == "at-most-once" and int(effect["max_attempts"]) != 1:
            raise AdapterOperationDenied("at-most-once operation requires outbox max_attempts=1")
        request_id = (
            "request-"
            + hashlib.sha256(
                f"{effect['effect_id']}\0{adapter_id}\0{operation.name}".encode("utf-8")
            ).hexdigest()[:32]
        )
        deadline = now + operation.timeout_seconds
        if effect["claim_expires_at"] is not None:
            deadline = min(deadline, float(effect["claim_expires_at"]))
        request = {
            "schema_version": "1.0.0",
            "request_id": request_id,
            "effect_id": effect["effect_id"],
            "work_item_id": effect["work_item_id"],
            "authorization_event_sequence": effect["authorization_event_sequence"],
            "instance_id": self.instance["instance_id"],
            "adapter_id": adapter_id,
            "slot": effect["adapter_slot"],
            "operation": effect["operation"],
            "idempotency_key": effect["idempotency_key"],
            "attempt": attempt,
            "deadline_epoch": deadline,
            "payload": effect["payload"],
        }
        _bounded_json(request)
        _validate_document(request, REQUEST_SCHEMA, "adapter request")
        context = AdapterContext(
            instance_id=str(self.instance["instance_id"]),
            binding_config=_safe_json_copy(
                binding["config"], label=f"adapter {adapter_id} binding config"
            ),
            allowed_secret_refs=frozenset(str(ref) for ref in binding["secret_refs"]),
            _resolver=self.secret_resolver,
        )

        if float(effect["claim_expires_at"]) <= self.clock():
            raise AdapterClaimExpired("outbox claim expired before provider invocation")

        if attempt > 1 and operation.delivery == "reconcile-before-retry":
            reconciled = implementation.reconcile(request, context)
            if reconciled is not None:
                return self._result(reconciled, operation, reconciled=True)
        if attempt > 1 and operation.delivery == "at-most-once":
            raise AdapterPermanentError("uncertain at-most-once operation cannot be replayed")
        return self._result(implementation.execute(request, context), operation)


class AdapterWorker:
    """Claims one durable effect and acknowledges only schema-valid results."""

    def __init__(
        self,
        control_plane: ControlPlane,
        host: AdapterHost,
        worker_id: str,
        *,
        lease_seconds: int = 60,
        retry_delay_seconds: int = 5,
    ) -> None:
        self.control_plane = control_plane
        self.host = host
        self.worker_id = worker_id
        self.lease_seconds = lease_seconds
        self.retry_delay_seconds = retry_delay_seconds

    def run_once(self) -> dict[str, Any] | None:
        self.control_plane.verify_audit()
        claim = self.control_plane.claim_effect(self.worker_id, lease_seconds=self.lease_seconds)
        if claim is None:
            return None
        effect = claim["effect"]
        authorization_event = self.control_plane.get_audit_event(
            int(effect["authorization_event_sequence"])
        )
        try:
            result = self.host.dispatch(effect, authorization_event)
        except AdapterRetryableError as exc:
            return self.control_plane.fail_effect(
                effect["effect_id"],
                self.worker_id,
                effect["claim_token"],
                error=exc.code,
                retry_delay_seconds=self.retry_delay_seconds,
            )
        except AdapterClaimExpired as exc:
            reconciliation = self.control_plane.reconcile()
            return {
                "effect": self.control_plane.get_effect(effect["effect_id"]),
                "reconciliation": reconciliation,
                "error": exc.code,
            }
        except (
            AdapterPermanentError,
            AdapterContractError,
            AdapterOperationDenied,
            AdapterDisabled,
            AdapterCatalogError,
        ) as exc:
            return self.control_plane.fail_effect(
                effect["effect_id"],
                self.worker_id,
                effect["claim_token"],
                error=exc.code,
                permanent=True,
            )
        except Exception:
            return self.control_plane.fail_effect(
                effect["effect_id"],
                self.worker_id,
                effect["claim_token"],
                error="ADAPTER_UNEXPECTED_FAILURE",
                retry_delay_seconds=self.retry_delay_seconds,
            )
        if result["status"] == "SUCCEEDED":
            return self.control_plane.complete_effect(
                effect["effect_id"],
                self.worker_id,
                effect["claim_token"],
                result,
            )
        permanent = result["status"] == "PERMANENT_FAILURE"
        return self.control_plane.fail_effect(
            effect["effect_id"],
            self.worker_id,
            effect["claim_token"],
            error=str(result["error_code"]),
            retry_delay_seconds=self.retry_delay_seconds,
            permanent=permanent,
        )
