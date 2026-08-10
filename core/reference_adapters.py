"""No-network reference adapters used to prove SDK and recovery contracts."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Iterable, Protocol

from core.adapters import AdapterContext, AdapterContractError, AdapterPermanentError
from core.isolation import execution_plan_digest, validate_execution_request


def _digest(value: Any) -> str:
    content = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(content).hexdigest()


def _operation_digest(request: dict[str, Any]) -> str:
    """Bind provider idempotency to immutable operation content, not retry metadata."""

    return _digest(
        {
            "effect_id": request["effect_id"],
            "work_item_id": request["work_item_id"],
            "authorization_event_sequence": request["authorization_event_sequence"],
            "instance_id": request["instance_id"],
            "adapter_id": request["adapter_id"],
            "slot": request["slot"],
            "operation": request["operation"],
            "idempotency_key": request["idempotency_key"],
            "payload": request["payload"],
        }
    )


class GitHubTransport(Protocol):
    """Authenticated transport supplied by an instance, never loaded dynamically."""

    def create(
        self,
        operation: str,
        path: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]: ...

    def find_by_marker(
        self,
        operation: str,
        repository: str,
        marker: str,
    ) -> dict[str, Any] | None: ...


class GitHubReferenceAdapter:
    """Maps two safe creation contracts onto an injected GitHub transport."""

    adapter_id = "adapter.github"

    def __init__(self, transport: GitHubTransport) -> None:
        self.transport = transport

    @staticmethod
    def _marker(request: dict[str, Any]) -> str:
        stable = _digest(
            {
                "adapter_id": "adapter.github",
                "idempotency_key": request["idempotency_key"],
                "operation_digest": _operation_digest(request),
            }
        )
        return f"<!-- agent-team-effect:{stable} -->"

    @staticmethod
    def _result(response: dict[str, Any], *, reconciled: bool) -> dict[str, Any]:
        try:
            external_ref = str(response["html_url"])
            provider_request_id = str(response["request_id"])
        except KeyError as exc:
            raise AdapterContractError(
                "GitHub transport response lacks a stable reference"
            ) from exc
        output = {
            "external_ref": external_ref,
            "provider_request_id": provider_request_id,
            "state": "created",
        }
        return {
            "schema_version": "1.0.0",
            "status": "SUCCEEDED",
            "output": output,
            "external_ref": external_ref,
            "provider_request_id": provider_request_id,
            "reconciled": reconciled,
            "error_code": None,
        }

    def execute(self, request: dict[str, Any], context: AdapterContext) -> dict[str, Any]:
        del context
        payload = dict(request["payload"])
        repository = str(payload.pop("repository"))
        owner, repo = repository.split("/", 1)
        payload.pop("work_item_id", None)
        marker = self._marker(request)
        payload["body"] = f"{payload.get('body', '').rstrip()}\n\n{marker}\n"
        if request["operation"] == "issue.create":
            path = f"/repos/{owner}/{repo}/issues"
        elif request["operation"] == "pull-request.create":
            if payload.get("draft") is not True:
                raise AdapterPermanentError("GitHub pull requests must be created as drafts")
            path = f"/repos/{owner}/{repo}/pulls"
        else:
            raise AdapterPermanentError("unsupported GitHub reference operation")
        response = self.transport.create(str(request["operation"]), path, payload)
        return self._result(response, reconciled=False)

    def reconcile(self, request: dict[str, Any], context: AdapterContext) -> dict[str, Any] | None:
        del context
        response = self.transport.find_by_marker(
            str(request["operation"]),
            str(request["payload"]["repository"]),
            self._marker(request),
        )
        return self._result(response, reconciled=True) if response is not None else None


class RecordingAdapter:
    """Deterministic provider test double with idempotency and reconciliation."""

    adapter_id = "adapter.recording"

    def __init__(self) -> None:
        self._records: dict[str, tuple[str, dict[str, Any]]] = {}
        self.execute_count = 0
        self.reconcile_count = 0

    def execute(self, request: dict[str, Any], context: AdapterContext) -> dict[str, Any]:
        del context
        key = str(request["idempotency_key"])
        request_digest = _operation_digest(request)
        existing = self._records.get(key)
        if existing:
            if existing[0] != request_digest:
                raise AdapterPermanentError(
                    "recording provider idempotency key received different content"
                )
            return existing[1]
        self.execute_count += 1
        stable = _digest({"adapter": self.adapter_id, "idempotency_key": key})[:24]
        output = {
            "external_ref": f"recording://effects/{stable}",
            "provider_request_id": f"recording-{stable}",
            "state": "reported",
        }
        result = {
            "schema_version": "1.0.0",
            "status": "SUCCEEDED",
            "output": output,
            "external_ref": output["external_ref"],
            "provider_request_id": output["provider_request_id"],
            "reconciled": False,
            "error_code": None,
        }
        self._records[key] = (request_digest, result)
        return result

    def reconcile(self, request: dict[str, Any], context: AdapterContext) -> dict[str, Any] | None:
        del context
        self.reconcile_count += 1
        existing = self._records.get(str(request["idempotency_key"]))
        if existing is None:
            return None
        if existing[0] != _operation_digest(request):
            raise AdapterPermanentError(
                "recording provider idempotency key received different content"
            )
        return existing[1]


class LocalDryRunRunnerAdapter:
    """Validates an isolation plan and never executes a command."""

    adapter_id = "adapter.local-dry-run"

    def __init__(
        self,
        *,
        allowed_command_ids: Iterable[str] = ("test",),
        allowed_secret_refs: Iterable[str] = (),
        maximum_timeout_seconds: int = 3600,
    ) -> None:
        self.allowed_command_ids = frozenset(allowed_command_ids)
        self.allowed_secret_refs = frozenset(allowed_secret_refs)
        self.maximum_timeout_seconds = maximum_timeout_seconds
        self._results: dict[str, tuple[str, dict[str, Any]]] = {}
        self.execute_count = 0

    def execute(self, request: dict[str, Any], context: AdapterContext) -> dict[str, Any]:
        del context
        execution = request["payload"]
        validate_execution_request(
            execution,
            allowed_command_ids=self.allowed_command_ids,
            allowed_secret_refs=self.allowed_secret_refs,
            maximum_timeout_seconds=self.maximum_timeout_seconds,
        )
        key = str(request["idempotency_key"])
        request_digest = _operation_digest(request)
        existing = self._results.get(key)
        if existing is not None:
            if existing[0] != request_digest:
                raise AdapterPermanentError(
                    "dry-run provider idempotency key received different content"
                )
            return existing[1]
        self.execute_count += 1
        plan_digest = execution_plan_digest(execution)
        output = {
            "schema_version": "1.0.0",
            "job_id": execution["job_id"],
            "status": "PLANNED",
            "exit_code": None,
            "artifact_digests": [plan_digest],
            "evidence_refs": [f"dry-run://plans/{plan_digest.removeprefix('sha256:')[:24]}"],
            "executor_ref": "reference://local-dry-run/no-process-started",
        }
        result = {
            "schema_version": "1.0.0",
            "status": "SUCCEEDED",
            "output": output,
            "external_ref": None,
            "provider_request_id": f"dry-run-{plan_digest.removeprefix('sha256:')[:24]}",
            "reconciled": False,
            "error_code": None,
        }
        self._results[key] = (request_digest, result)
        return result

    def reconcile(self, request: dict[str, Any], context: AdapterContext) -> dict[str, Any] | None:
        del context
        existing = self._results.get(str(request["idempotency_key"]))
        if existing is None:
            return None
        if existing[0] != _operation_digest(request):
            raise AdapterPermanentError(
                "dry-run provider idempotency key received different content"
            )
        return existing[1]
