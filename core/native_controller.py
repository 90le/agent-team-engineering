"""Deterministic single-node v0.8 Native reference controller.

This module is an anti-lock-in and recovery reference, not an untrusted-code
runner.  It persists only sanitized contract documents, commands, events,
leases, effect metadata, and evidence indexes in SQLite.  External behavior is
reachable exclusively through explicitly bound v0.8 ports.
"""

from __future__ import annotations

import hashlib
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator

from core.adapter_ports import (
    Outcome,
    PortCall,
    PortRegistry,
    PortResult,
)
from core.contracts import (
    approval_scope_digest,
    canonical_json,
    digest_value,
    require_contract,
)
from core.json_support import loads_strict
from core.security import find_inline_secret

NATIVE_SCHEMA_VERSION = "1"
MAX_NATIVE_JSON_BYTES = 1_000_000
TERMINAL_STATES = frozenset(
    {"COMPLETED", "REJECTED", "DUPLICATE", "CANCELLED", "EXPIRED", "FAILED"}
)


class NativeControllerError(RuntimeError):
    code = "NATIVE_CONTROLLER_ERROR"


class NativeRevisionConflict(NativeControllerError):
    code = "NATIVE_REVISION_CONFLICT"


class NativeTransitionDenied(NativeControllerError):
    code = "NATIVE_TRANSITION_DENIED"


class NativeApprovalDenied(NativeControllerError):
    code = "NATIVE_APPROVAL_DENIED"


class NativeLeaseDenied(NativeControllerError):
    code = "NATIVE_LEASE_DENIED"


class NativeIdempotencyConflict(NativeControllerError):
    code = "NATIVE_IDEMPOTENCY_CONFLICT"


class NativeEffectBusy(NativeControllerError):
    code = "NATIVE_EFFECT_BUSY"


class InjectedNativeCrash(NativeControllerError):
    code = "NATIVE_INJECTED_CRASH"


def _iso(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def _epoch(value: str) -> float:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()


def _portable(value: dict[str, Any], label: str) -> dict[str, Any]:
    secret = find_inline_secret(value)
    if secret is not None:
        raise NativeControllerError(f"{label} contains inline secret-like data at {secret}")
    try:
        encoded = canonical_json(value).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise NativeControllerError(f"{label} is not strict JSON: {exc}") from exc
    if len(encoded) > MAX_NATIVE_JSON_BYTES:
        raise NativeControllerError(f"{label} exceeds the 1 MiB limit")
    copied = loads_strict(encoded)
    if not isinstance(copied, dict):
        raise NativeControllerError(f"{label} must be an object")
    return copied


def _result_to_dict(result: PortResult) -> dict[str, Any]:
    return {
        "outcome": result.outcome.value,
        "data": result.data,
        "side_effect": result.side_effect.value,
        "provider_ref": result.provider_ref,
        "evidence_refs": list(result.evidence_refs),
        "error_code": result.error_code,
        "retry_after_seconds": result.retry_after_seconds,
        "reconciled": result.reconciled,
    }


class NativeController:
    """Transactional reference controller with an explicit Draft-PR ceiling."""

    def __init__(
        self,
        database: Path,
        workflow: dict[str, Any],
        *,
        ports: PortRegistry | None = None,
        clock: Callable[[], float] = time.time,
        create: bool = True,
    ) -> None:
        self.database = database.resolve()
        if database.is_symlink():
            raise NativeControllerError("native database must not be a symbolic link")
        if not create and not self.database.is_file():
            raise NativeControllerError(f"native database does not exist: {self.database}")
        if create:
            self.database.parent.mkdir(parents=True, exist_ok=True)
        self.workflow = _portable(require_contract("workflow_spec", workflow), "workflow")
        self.workflow_digest = digest_value(self.workflow)
        self.ports = ports or PortRegistry()
        self.clock = clock
        self._transitions = {
            (str(item["from_state"]), str(item["event"])): item
            for item in self.workflow["transitions"]
        }
        self.connection = sqlite3.connect(
            self.database,
            isolation_level=None,
            timeout=5.0,
        )
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.connection.execute("PRAGMA journal_mode = WAL")
        self.connection.execute("PRAGMA synchronous = FULL")
        self._initialize()

    def __enter__(self) -> "NativeController":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        self.connection.close()

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Cursor]:
        cursor = self.connection.cursor()
        cursor.execute("BEGIN IMMEDIATE")
        try:
            yield cursor
        except BaseException:
            self.connection.rollback()
            raise
        else:
            self.connection.commit()
        finally:
            cursor.close()

    def _initialize(self) -> None:
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS native_meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS native_work_items (
                work_item_id TEXT PRIMARY KEY,
                state TEXT NOT NULL,
                revision INTEGER NOT NULL,
                document_json TEXT NOT NULL,
                plan_json TEXT,
                approval_json TEXT,
                run_json TEXT,
                updated_at_epoch REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS native_commands (
                idempotency_key TEXT PRIMARY KEY,
                command_digest TEXT NOT NULL,
                result_json TEXT NOT NULL,
                created_at_epoch REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS native_events (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id TEXT NOT NULL UNIQUE,
                work_item_id TEXT NOT NULL,
                revision INTEGER NOT NULL,
                event_type TEXT NOT NULL,
                event_json TEXT NOT NULL,
                event_digest TEXT NOT NULL,
                previous_chain_digest TEXT,
                chain_digest TEXT NOT NULL,
                FOREIGN KEY(work_item_id) REFERENCES native_work_items(work_item_id)
            );
            CREATE TABLE IF NOT EXISTS native_approval_nonces (
                nonce TEXT PRIMARY KEY,
                approval_id TEXT NOT NULL UNIQUE,
                work_item_id TEXT NOT NULL,
                consumed_at_epoch REAL NOT NULL,
                FOREIGN KEY(work_item_id) REFERENCES native_work_items(work_item_id)
            );
            CREATE TABLE IF NOT EXISTS native_leases (
                work_item_id TEXT PRIMARY KEY,
                lease_id TEXT NOT NULL UNIQUE,
                worker_id TEXT NOT NULL,
                role_id TEXT NOT NULL,
                work_revision INTEGER NOT NULL,
                acquired_at_epoch REAL NOT NULL,
                expires_at_epoch REAL NOT NULL,
                FOREIGN KEY(work_item_id) REFERENCES native_work_items(work_item_id)
            );
            CREATE TABLE IF NOT EXISTS native_effects (
                effect_id TEXT PRIMARY KEY,
                work_item_id TEXT NOT NULL,
                run_id TEXT,
                port TEXT NOT NULL,
                operation TEXT NOT NULL,
                idempotency_key TEXT NOT NULL UNIQUE,
                binding_digest TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                status TEXT NOT NULL,
                attempt INTEGER NOT NULL,
                max_attempts INTEGER NOT NULL,
                claim_token TEXT,
                claim_expires_at_epoch REAL,
                result_json TEXT,
                not_before_at_epoch REAL,
                updated_at_epoch REAL NOT NULL,
                FOREIGN KEY(work_item_id) REFERENCES native_work_items(work_item_id)
            );
            CREATE TABLE IF NOT EXISTS native_evidence_bundles (
                bundle_id TEXT PRIMARY KEY,
                work_item_id TEXT NOT NULL,
                run_id TEXT NOT NULL,
                bundle_digest TEXT NOT NULL UNIQUE,
                document_json TEXT NOT NULL,
                created_at_epoch REAL NOT NULL,
                FOREIGN KEY(work_item_id) REFERENCES native_work_items(work_item_id)
            );
            """
        )
        with self._transaction() as cursor:
            existing = {
                str(row["key"]): str(row["value"])
                for row in cursor.execute("SELECT key, value FROM native_meta")
            }
            expected = {
                "schema_version": NATIVE_SCHEMA_VERSION,
                "workflow_digest": self.workflow_digest,
                "default_stop_state": "DRAFT_PR_READY",
                "merge_enabled": "false",
                "deploy_enabled": "false",
            }
            if existing:
                for key, value in expected.items():
                    if existing.get(key) != value:
                        raise NativeControllerError(
                            f"native database metadata mismatch for {key}: {existing.get(key)!r}"
                        )
            else:
                cursor.executemany(
                    "INSERT INTO native_meta(key, value) VALUES(?, ?)", expected.items()
                )

    def _command(self, command: dict[str, Any]) -> tuple[dict[str, Any], str]:
        document = _portable(require_contract("command_envelope", command), "command")
        return document, digest_value(document)

    def _cached(
        self,
        cursor: sqlite3.Cursor,
        command: dict[str, Any],
        command_digest: str,
    ) -> dict[str, Any] | None:
        row = cursor.execute(
            "SELECT command_digest, result_json FROM native_commands WHERE idempotency_key = ?",
            (command["idempotency_key"],),
        ).fetchone()
        if row is None:
            return None
        if row["command_digest"] != command_digest:
            raise NativeIdempotencyConflict(
                "idempotency key was reused with a different command"
            )
        value = loads_strict(row["result_json"])
        if not isinstance(value, dict):
            raise NativeControllerError("stored command result is invalid")
        return value

    def _preflight_cached(
        self, command: dict[str, Any], command_digest: str
    ) -> dict[str, Any] | None:
        row = self.connection.execute(
            "SELECT command_digest, result_json FROM native_commands WHERE idempotency_key = ?",
            (command["idempotency_key"],),
        ).fetchone()
        if row is None:
            return None
        if row["command_digest"] != command_digest:
            raise NativeIdempotencyConflict(
                "idempotency key was reused with a different command"
            )
        value = loads_strict(row["result_json"])
        if not isinstance(value, dict):
            raise NativeControllerError("stored command result is invalid")
        return value

    def _save_command(
        self,
        cursor: sqlite3.Cursor,
        command: dict[str, Any],
        command_digest: str,
        result: dict[str, Any],
    ) -> None:
        cursor.execute(
            "INSERT INTO native_commands(idempotency_key, command_digest, result_json, created_at_epoch) VALUES(?, ?, ?, ?)",
            (
                command["idempotency_key"],
                command_digest,
                canonical_json(result),
                float(self.clock()),
            ),
        )

    def _load_work_row(self, cursor: sqlite3.Cursor, work_item_id: str) -> sqlite3.Row:
        row = cursor.execute(
            "SELECT * FROM native_work_items WHERE work_item_id = ?", (work_item_id,)
        ).fetchone()
        if row is None:
            raise NativeTransitionDenied(f"unknown work item: {work_item_id}")
        return row

    def _row_document(self, row: sqlite3.Row, field: str) -> dict[str, Any] | None:
        raw = row[field]
        if raw is None:
            return None
        value = loads_strict(raw)
        if not isinstance(value, dict):
            raise NativeControllerError(f"stored {field} is invalid")
        return value

    def _append_event(
        self,
        cursor: sqlite3.Cursor,
        *,
        command_id: str,
        idempotency_key: str,
        event_type: str,
        work_item_id: str,
        run_id: str | None,
        revision: int,
        payload: dict[str, Any],
        evidence_refs: list[str] | tuple[str, ...] = (),
    ) -> dict[str, Any]:
        event_id = "event-" + hashlib.sha256(
            f"{command_id}:{event_type}:{revision}".encode("utf-8")
        ).hexdigest()[:32]
        event = {
            "$schema": "urn:agent-team:schema:event-envelope:1.0.0",
            "schema_version": "1.0.0",
            "event_id": event_id,
            "event_type": event_type,
            "causation_command_id": command_id,
            "idempotency_key": idempotency_key,
            "work_item_id": work_item_id,
            "run_id": run_id,
            "revision": revision,
            "occurred_at": _iso(float(self.clock())),
            "payload": _portable(payload, "event payload"),
            "evidence_refs": list(evidence_refs),
        }
        require_contract("event_envelope", event)
        event_digest = digest_value(event)
        previous_row = cursor.execute(
            "SELECT chain_digest FROM native_events ORDER BY sequence DESC LIMIT 1"
        ).fetchone()
        previous = str(previous_row["chain_digest"]) if previous_row else None
        chain_digest = digest_value(
            {"previous_chain_digest": previous, "event_digest": event_digest}
        )
        cursor.execute(
            """
            INSERT INTO native_events(
                event_id, work_item_id, revision, event_type, event_json,
                event_digest, previous_chain_digest, chain_digest
            ) VALUES(?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_id,
                work_item_id,
                revision,
                event_type,
                canonical_json(event),
                event_digest,
                previous,
                chain_digest,
            ),
        )
        return event

    @staticmethod
    def _fault(fault: str | None, point: str) -> None:
        if fault == point:
            raise InjectedNativeCrash(f"injected crash at {point}")

    def create_work_item(
        self,
        command: dict[str, Any],
        work_item: dict[str, Any],
        *,
        fault: str | None = None,
    ) -> dict[str, Any]:
        command, command_digest = self._command(command)
        if command["command_type"] != "CREATE_WORK_ITEM":
            raise NativeTransitionDenied("create_work_item requires CREATE_WORK_ITEM")
        document = _portable(require_contract("work_item", work_item), "work item")
        if document["work_item_id"] != command["work_item_id"]:
            raise NativeTransitionDenied("command and WorkItem identifiers differ")
        if command["expected_revision"] != 0:
            raise NativeRevisionConflict("new WorkItem expected_revision must be zero")
        if document["state"] != self.workflow["initial_state"] or document["revision"] != 0:
            raise NativeTransitionDenied("new WorkItem must use the workflow initial state at revision zero")
        with self._transaction() as cursor:
            cached = self._cached(cursor, command, command_digest)
            if cached is not None:
                return cached
            if cursor.execute(
                "SELECT 1 FROM native_work_items WHERE work_item_id = ?",
                (document["work_item_id"],),
            ).fetchone():
                raise NativeTransitionDenied("WorkItem already exists under another command")
            stored = dict(document)
            stored["revision"] = 1
            cursor.execute(
                """
                INSERT INTO native_work_items(
                    work_item_id, state, revision, document_json, updated_at_epoch
                ) VALUES(?, ?, ?, ?, ?)
                """,
                (
                    stored["work_item_id"],
                    stored["state"],
                    stored["revision"],
                    canonical_json(stored),
                    float(self.clock()),
                ),
            )
            event = self._append_event(
                cursor,
                command_id=command["command_id"],
                idempotency_key=command["idempotency_key"],
                event_type="WORK_ITEM_CREATED",
                work_item_id=stored["work_item_id"],
                run_id=None,
                revision=1,
                payload={
                    "source_event_id": stored["source"]["event_id"],
                    "duplicate_fingerprint": stored["normalized"]["duplicate_fingerprint"],
                },
            )
            result = {"work_item": stored, "event": event, "replayed": False}
            self._save_command(cursor, command, command_digest, result)
            self._fault(fault, "before_commit")
        self._fault(fault, "after_commit")
        return result

    def _verify_exact_approval(
        self,
        command: dict[str, Any],
        plan: dict[str, Any],
        approval: dict[str, Any],
    ) -> None:
        grant = require_contract("approval_grant", approval)
        if approval_scope_digest(grant) != grant["scope_digest"]:
            raise NativeApprovalDenied("approval scope digest is invalid")
        comparisons = {
            "work_item_id": plan["work_item_id"],
            "plan_revision": plan["revision"],
            "plan_digest": plan["plan_digest"],
            "repository_id": plan["repository_id"],
            "base_commit": plan["base_commit"],
            "allowed_paths": plan["allowed_paths"],
            "allowed_actions": plan["allowed_actions"],
            "budget_limit": plan["budget_limit"],
            "time_limit_seconds": plan["time_limit_seconds"],
        }
        for field, expected in comparisons.items():
            if grant[field] != expected:
                raise NativeApprovalDenied(f"approval field does not match plan: {field}")
        required_capabilities = sorted(
            {
                capability
                for task in plan["tasks"]
                for capability in task["required_capabilities"]
            }
        )
        if sorted(grant["agent_capabilities"]) != required_capabilities:
            raise NativeApprovalDenied("approval agent capabilities do not exactly match the plan")
        expected_runner = command["payload"].get("runner_profile")
        expected_capabilities = command["payload"].get("agent_capabilities")
        if not isinstance(expected_runner, str) or expected_runner != grant["runner_profile"]:
            raise NativeApprovalDenied("approval runner profile differs from the requested execution")
        if not isinstance(expected_capabilities, list) or sorted(expected_capabilities) != sorted(
            grant["agent_capabilities"]
        ):
            raise NativeApprovalDenied(
                "approval agent capabilities differ from the requested execution"
            )
        if grant["actor_id"] != command["actor"]["actor_id"]:
            raise NativeApprovalDenied("approval actor differs from the command actor")
        if grant["work_item_id"] != command["work_item_id"]:
            raise NativeApprovalDenied("approval work item differs from the command")
        now = float(self.clock())
        if _epoch(grant["issued_at"]) > now or _epoch(grant["expires_at"]) <= now:
            raise NativeApprovalDenied("approval is not active at controller time")
        if grant["merge_allowed"] or grant["deploy_allowed"]:
            raise NativeApprovalDenied("merge and deployment are forbidden in v0.8")

    def _verify_identity(self, command: dict[str, Any], approval: dict[str, Any]) -> None:
        binding = self.ports.get("identity")
        call = PortCall(
            request_id="request-" + hashlib.sha256(
                f"identity:{approval['approval_id']}".encode("utf-8")
            ).hexdigest()[:24],
            operation="approval.verify",
            idempotency_key=f"identity-{approval['approval_id']}",
            correlation_id=command["work_item_id"],
            deadline_epoch=min(float(self.clock()) + 30, _epoch(approval["expires_at"])),
            payload={
                "approval_id": approval["approval_id"],
                "actor_id": approval["actor_id"],
                "identity_provider": approval["identity_provider"],
                "signature_ref": approval["signature_ref"],
                "scope_digest": approval["scope_digest"],
            },
        )
        result = binding.invoke(call)
        if result.outcome != Outcome.SUCCEEDED:
            raise NativeApprovalDenied(
                f"identity verification failed: {result.error_code or result.outcome.value}"
            )
        expected = {
            "verified": True,
            "approval_id": approval["approval_id"],
            "actor_id": approval["actor_id"],
            "identity_provider": approval["identity_provider"],
            "signature_ref": approval["signature_ref"],
        }
        if any(result.data.get(key) != value for key, value in expected.items()):
            raise NativeApprovalDenied("identity result is not bound to the exact approval")

    def _assert_worker_lease(
        self,
        cursor: sqlite3.Cursor,
        command: dict[str, Any],
        required_role: str | None,
    ) -> str | None:
        actor = command["actor"]
        if required_role is not None and actor["role_id"] != required_role:
            raise NativeTransitionDenied(
                f"transition requires {required_role}, received {actor['role_id']}"
            )
        if actor["actor_kind"] != "worker":
            return None
        lease_id = command["payload"].get("lease_id")
        if not isinstance(lease_id, str):
            raise NativeLeaseDenied("worker transition requires lease_id")
        lease = cursor.execute(
            "SELECT * FROM native_leases WHERE work_item_id = ?",
            (command["work_item_id"],),
        ).fetchone()
        if lease is None or lease["lease_id"] != lease_id:
            raise NativeLeaseDenied("worker lease is missing or differs")
        if lease["worker_id"] != actor["actor_id"] or lease["role_id"] != actor["role_id"]:
            raise NativeLeaseDenied("worker lease identity or role differs")
        if lease["work_revision"] != command["expected_revision"]:
            raise NativeLeaseDenied("worker lease is bound to a different revision")
        if float(lease["expires_at_epoch"]) <= float(self.clock()):
            raise NativeLeaseDenied("worker lease has expired")
        return lease_id

    def _limit_exceeded(
        self,
        run: dict[str, Any] | None,
        approval: dict[str, Any] | None,
        cost_delta: int,
    ) -> str | None:
        if run is None or approval is None:
            return None
        if _epoch(approval["expires_at"]) <= float(self.clock()):
            return "APPROVAL_EXPIRED"
        if run["cost_units_used"] + cost_delta > approval["budget_limit"]:
            return "BUDGET_EXCEEDED"
        if float(self.clock()) - _epoch(run["started_at"]) > approval["time_limit_seconds"]:
            return "TIME_LIMIT_EXCEEDED"
        return None

    def apply_transition(
        self,
        command: dict[str, Any],
        *,
        approval_grant: dict[str, Any] | None = None,
        fault: str | None = None,
    ) -> dict[str, Any]:
        command, command_digest = self._command(command)
        cached = self._preflight_cached(command, command_digest)
        if cached is not None:
            return cached
        snapshot = self.connection.execute(
            "SELECT * FROM native_work_items WHERE work_item_id = ?",
            (command["work_item_id"],),
        ).fetchone()
        if snapshot is None:
            raise NativeTransitionDenied(f"unknown work item: {command['work_item_id']}")
        transition = self._transitions.get((snapshot["state"], command["command_type"]))
        if transition is None:
            raise NativeTransitionDenied(
                f"event {command['command_type']} is not legal from {snapshot['state']}"
            )
        if transition["to_state"] in {"MERGED", "DEPLOYED"}:
            raise NativeTransitionDenied("merge and deploy do not exist in the v0.8 controller")

        plan_candidate = command["payload"].get("plan_revision")
        if plan_candidate is not None:
            plan_candidate = _portable(
                require_contract("plan_revision", plan_candidate), "plan revision"
            )
            if plan_candidate["work_item_id"] != command["work_item_id"]:
                raise NativeTransitionDenied("plan belongs to another WorkItem")
        if command["command_type"] == "PLAN_READY" and plan_candidate is None:
            raise NativeTransitionDenied("PLAN_READY requires plan_revision")

        if transition["requires_approval"]:
            if approval_grant is None:
                raise NativeApprovalDenied("transition requires an ApprovalGrant")
            plan = self._row_document(snapshot, "plan_json")
            if plan is None:
                raise NativeApprovalDenied("no immutable plan exists for approval")
            approval_grant = _portable(
                require_contract("approval_grant", approval_grant), "approval grant"
            )
            self._verify_exact_approval(command, plan, approval_grant)
            self._verify_identity(command, approval_grant)

        evidence_types = command["payload"].get("evidence_types", [])
        evidence_refs = command["payload"].get("evidence_refs", [])
        if not isinstance(evidence_types, list) or not all(
            isinstance(value, str) for value in evidence_types
        ):
            raise NativeTransitionDenied("evidence_types must be a string array")
        if not isinstance(evidence_refs, list) or not all(
            isinstance(value, str) for value in evidence_refs
        ):
            raise NativeTransitionDenied("evidence_refs must be a string array")
        missing_evidence = sorted(set(transition["required_evidence"]) - set(evidence_types))
        if missing_evidence:
            raise NativeTransitionDenied(
                f"transition lacks evidence types: {', '.join(missing_evidence)}"
            )
        cost_delta = command["payload"].get("cost_units_delta", 0)
        if not isinstance(cost_delta, int) or isinstance(cost_delta, bool) or cost_delta < 0:
            raise NativeTransitionDenied("cost_units_delta must be a non-negative integer")

        with self._transaction() as cursor:
            cached = self._cached(cursor, command, command_digest)
            if cached is not None:
                return cached
            row = self._load_work_row(cursor, command["work_item_id"])
            if row["revision"] != command["expected_revision"]:
                raise NativeRevisionConflict(
                    f"expected revision {command['expected_revision']}, current is {row['revision']}"
                )
            current_transition = self._transitions.get((row["state"], command["command_type"]))
            if current_transition != transition:
                raise NativeTransitionDenied("workflow state changed during command verification")
            used_lease = self._assert_worker_lease(
                cursor, command, transition["required_role"]
            )
            work = self._row_document(row, "document_json")
            if work is None:
                raise NativeControllerError("stored WorkItem is missing")
            plan = self._row_document(row, "plan_json")
            approval = self._row_document(row, "approval_json")
            run = self._row_document(row, "run_json")
            if plan_candidate is not None:
                plan = plan_candidate

            if transition["requires_approval"]:
                assert approval_grant is not None
                try:
                    cursor.execute(
                        "INSERT INTO native_approval_nonces(nonce, approval_id, work_item_id, consumed_at_epoch) VALUES(?, ?, ?, ?)",
                        (
                            approval_grant["nonce"],
                            approval_grant["approval_id"],
                            command["work_item_id"],
                            float(self.clock()),
                        ),
                    )
                except sqlite3.IntegrityError as exc:
                    raise NativeApprovalDenied("approval nonce or id has already been consumed") from exc
                approval = approval_grant
                if command["run_id"] is None:
                    raise NativeApprovalDenied("approval command must assign a run_id")
                run = {
                    "$schema": "urn:agent-team:schema:run:1.0.0",
                    "schema_version": "1.0.0",
                    "run_id": command["run_id"],
                    "work_item_id": command["work_item_id"],
                    "plan_id": plan["plan_id"],
                    "plan_revision": plan["revision"],
                    "plan_digest": plan["plan_digest"],
                    "approval_id": approval["approval_id"],
                    "state": "APPROVED",
                    "revision": 0,
                    "attempt": 1,
                    "lease": None,
                    "worker_sessions": [],
                    "cost_units_used": 0,
                    "started_at": _iso(float(self.clock())),
                    "updated_at": _iso(float(self.clock())),
                    "artifact_refs": [],
                    "evidence_bundle_refs": [],
                    "idempotency_keys": [command["idempotency_key"]],
                }

            limit_code = self._limit_exceeded(run, approval, cost_delta)
            target_state = "BLOCKED" if limit_code else str(transition["to_state"])
            next_revision = int(row["revision"]) + 1
            work["state"] = target_state
            work["revision"] = next_revision
            require_contract("work_item", work)
            if run is not None:
                run["state"] = target_state if target_state in {
                    "APPROVED",
                    "EXECUTING",
                    "VERIFYING",
                    "REVIEWING",
                    "CHANGES_REQUESTED",
                    "DRAFT_PR_READY",
                    "COMPLETED",
                    "CANCELLED",
                    "EXPIRED",
                    "FAILED",
                    "BLOCKED",
                } else run["state"]
                run["revision"] = int(run["revision"]) + 1
                run["cost_units_used"] = int(run["cost_units_used"]) + cost_delta
                run["updated_at"] = _iso(float(self.clock()))
                run["idempotency_keys"] = list(
                    dict.fromkeys([*run["idempotency_keys"], command["idempotency_key"]])
                )
                if used_lease:
                    run["lease"] = None
                require_contract("run", run)
            cursor.execute(
                """
                UPDATE native_work_items SET
                    state = ?, revision = ?, document_json = ?, plan_json = ?,
                    approval_json = ?, run_json = ?, updated_at_epoch = ?
                WHERE work_item_id = ?
                """,
                (
                    target_state,
                    next_revision,
                    canonical_json(work),
                    canonical_json(plan) if plan is not None else None,
                    canonical_json(approval) if approval is not None else None,
                    canonical_json(run) if run is not None else None,
                    float(self.clock()),
                    command["work_item_id"],
                ),
            )
            if used_lease:
                cursor.execute(
                    "DELETE FROM native_leases WHERE work_item_id = ? AND lease_id = ?",
                    (command["work_item_id"], used_lease),
                )
            event_type = "RUN_LIMIT_EXCEEDED" if limit_code else f"{command['command_type']}_APPLIED"
            payload = {
                "from_state": row["state"],
                "to_state": target_state,
                "actor_id": command["actor"]["actor_id"],
                "role_id": command["actor"]["role_id"],
                "limit_code": limit_code,
                "plan_digest": plan["plan_digest"] if plan is not None else None,
                "approval_id": approval["approval_id"] if approval is not None else None,
            }
            event = self._append_event(
                cursor,
                command_id=command["command_id"],
                idempotency_key=command["idempotency_key"],
                event_type=event_type,
                work_item_id=command["work_item_id"],
                run_id=run["run_id"] if run is not None else command["run_id"],
                revision=next_revision,
                payload=payload,
                evidence_refs=evidence_refs,
            )
            result = {
                "work_item": work,
                "plan_revision": plan,
                "approval_grant": approval,
                "run": run,
                "event": event,
                "limit_exceeded": limit_code,
                "replayed": False,
            }
            self._save_command(cursor, command, command_digest, result)
            self._fault(fault, "before_commit")
        self._fault(fault, "after_commit")
        return result

    def acquire_lease(
        self,
        command: dict[str, Any],
        *,
        ttl_seconds: int = 300,
        fault: str | None = None,
    ) -> dict[str, Any]:
        command, command_digest = self._command(command)
        if command["command_type"] != "ACQUIRE_LEASE":
            raise NativeLeaseDenied("acquire_lease requires ACQUIRE_LEASE")
        actor = command["actor"]
        if actor["actor_kind"] != "worker" or actor["role_id"] is None:
            raise NativeLeaseDenied("only a named worker role can acquire a lease")
        if not 1 <= ttl_seconds <= 3600:
            raise NativeLeaseDenied("lease TTL must be 1-3600 seconds")
        now = float(self.clock())
        lease_id = "lease-" + hashlib.sha256(
            command["idempotency_key"].encode("utf-8")
        ).hexdigest()[:24]
        with self._transaction() as cursor:
            cached = self._cached(cursor, command, command_digest)
            if cached is not None:
                return cached
            row = self._load_work_row(cursor, command["work_item_id"])
            if row["revision"] != command["expected_revision"]:
                raise NativeRevisionConflict("lease expected_revision differs from current")
            if row["state"] in TERMINAL_STATES:
                raise NativeLeaseDenied("terminal WorkItem cannot be leased")
            existing = cursor.execute(
                "SELECT * FROM native_leases WHERE work_item_id = ?",
                (command["work_item_id"],),
            ).fetchone()
            if existing is not None and float(existing["expires_at_epoch"]) > now:
                raise NativeLeaseDenied("WorkItem already has an active lease")
            if existing is not None:
                cursor.execute(
                    "DELETE FROM native_leases WHERE work_item_id = ?",
                    (command["work_item_id"],),
                )
            cursor.execute(
                """
                INSERT INTO native_leases(
                    work_item_id, lease_id, worker_id, role_id, work_revision,
                    acquired_at_epoch, expires_at_epoch
                ) VALUES(?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    command["work_item_id"],
                    lease_id,
                    actor["actor_id"],
                    actor["role_id"],
                    command["expected_revision"],
                    now,
                    now + ttl_seconds,
                ),
            )
            run = self._row_document(row, "run_json")
            if run is not None:
                run["lease"] = {
                    "lease_id": lease_id,
                    "worker_id": actor["actor_id"],
                    "acquired_at": _iso(now),
                    "expires_at": _iso(now + ttl_seconds),
                }
                run["updated_at"] = _iso(now)
                require_contract("run", run)
                cursor.execute(
                    "UPDATE native_work_items SET run_json = ?, updated_at_epoch = ? WHERE work_item_id = ?",
                    (canonical_json(run), now, command["work_item_id"]),
                )
            event = self._append_event(
                cursor,
                command_id=command["command_id"],
                idempotency_key=command["idempotency_key"],
                event_type="LEASE_ACQUIRED",
                work_item_id=command["work_item_id"],
                run_id=command["run_id"],
                revision=command["expected_revision"],
                payload={
                    "lease_id": lease_id,
                    "worker_id": actor["actor_id"],
                    "role_id": actor["role_id"],
                    "expires_at": _iso(now + ttl_seconds),
                },
            )
            result = {
                "lease": {
                    "lease_id": lease_id,
                    "worker_id": actor["actor_id"],
                    "role_id": actor["role_id"],
                    "work_revision": command["expected_revision"],
                    "acquired_at": _iso(now),
                    "expires_at": _iso(now + ttl_seconds),
                },
                "event": event,
                "replayed": False,
            }
            self._save_command(cursor, command, command_digest, result)
            self._fault(fault, "before_commit")
        self._fault(fault, "after_commit")
        return result

    def queue_effect(
        self,
        command: dict[str, Any],
        *,
        port: str,
        operation: str,
        payload: dict[str, Any],
        max_attempts: int = 3,
        fault: str | None = None,
    ) -> dict[str, Any]:
        command, command_digest = self._command(command)
        if command["command_type"] != "QUEUE_EFFECT":
            raise NativeTransitionDenied("queue_effect requires QUEUE_EFFECT")
        if not 1 <= max_attempts <= 20:
            raise NativeControllerError("max_attempts must be 1-20")
        self.ports.get(port)
        payload = _portable(payload, "effect payload")
        binding_digest = digest_value({"port": port, "operation": operation, "payload": payload})
        effect_id = "effect-" + hashlib.sha256(
            f"{port}:{command['idempotency_key']}".encode("utf-8")
        ).hexdigest()[:24]
        with self._transaction() as cursor:
            cached = self._cached(cursor, command, command_digest)
            if cached is not None:
                return cached
            row = self._load_work_row(cursor, command["work_item_id"])
            if row["revision"] != command["expected_revision"]:
                raise NativeRevisionConflict("effect expected_revision differs from current")
            existing = cursor.execute(
                "SELECT * FROM native_effects WHERE idempotency_key = ?",
                (command["idempotency_key"],),
            ).fetchone()
            if existing is not None:
                if existing["binding_digest"] != binding_digest:
                    raise NativeIdempotencyConflict(
                        "effect idempotency key was reused with different content"
                    )
                effect = self._effect_dict(existing)
            else:
                now = float(self.clock())
                cursor.execute(
                    """
                    INSERT INTO native_effects(
                        effect_id, work_item_id, run_id, port, operation,
                        idempotency_key, binding_digest, payload_json, status,
                        attempt, max_attempts, updated_at_epoch
                    ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, 'PENDING', 0, ?, ?)
                    """,
                    (
                        effect_id,
                        command["work_item_id"],
                        command["run_id"],
                        port,
                        operation,
                        command["idempotency_key"],
                        binding_digest,
                        canonical_json(payload),
                        max_attempts,
                        now,
                    ),
                )
                effect = self._effect_dict(
                    cursor.execute(
                        "SELECT * FROM native_effects WHERE effect_id = ?", (effect_id,)
                    ).fetchone()
                )
            event = self._append_event(
                cursor,
                command_id=command["command_id"],
                idempotency_key=command["idempotency_key"],
                event_type="EFFECT_QUEUED",
                work_item_id=command["work_item_id"],
                run_id=command["run_id"],
                revision=command["expected_revision"],
                payload={
                    "effect_id": effect_id,
                    "port": port,
                    "operation": operation,
                    "binding_digest": binding_digest,
                },
            )
            result = {"effect": effect, "event": event, "replayed": False}
            self._save_command(cursor, command, command_digest, result)
            self._fault(fault, "before_commit")
        self._fault(fault, "after_commit")
        return result

    def _effect_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        result = loads_strict(row["result_json"]) if row["result_json"] else None
        return {
            "effect_id": row["effect_id"],
            "work_item_id": row["work_item_id"],
            "run_id": row["run_id"],
            "port": row["port"],
            "operation": row["operation"],
            "idempotency_key": row["idempotency_key"],
            "binding_digest": row["binding_digest"],
            "status": row["status"],
            "attempt": row["attempt"],
            "max_attempts": row["max_attempts"],
            "claim_expires_at_epoch": row["claim_expires_at_epoch"],
            "not_before_at_epoch": row["not_before_at_epoch"],
            "result": result,
        }

    def run_effect(
        self,
        effect_id: str,
        *,
        claim_seconds: int = 30,
        fault: str | None = None,
    ) -> dict[str, Any]:
        if not 1 <= claim_seconds <= 300:
            raise NativeControllerError("effect claim must be 1-300 seconds")
        now = float(self.clock())
        with self._transaction() as cursor:
            row = cursor.execute(
                "SELECT * FROM native_effects WHERE effect_id = ?", (effect_id,)
            ).fetchone()
            if row is None:
                raise NativeControllerError(f"unknown effect: {effect_id}")
            if row["status"] in {"SUCCEEDED", "UNKNOWN", "DEAD"}:
                return self._effect_dict(row)
            if row["status"] == "CLAIMED" and float(row["claim_expires_at_epoch"]) > now:
                raise NativeEffectBusy("effect has an active claim")
            if row["not_before_at_epoch"] is not None and float(
                row["not_before_at_epoch"]
            ) > now:
                raise NativeEffectBusy("effect retry delay has not elapsed")
            attempt = int(row["attempt"]) + 1
            claim_token = "claim-" + hashlib.sha256(
                f"{effect_id}:{attempt}:{now}".encode("utf-8")
            ).hexdigest()[:24]
            cursor.execute(
                """
                UPDATE native_effects SET status = 'CLAIMED', attempt = ?,
                    claim_token = ?, claim_expires_at_epoch = ?, updated_at_epoch = ?
                WHERE effect_id = ?
                """,
                (attempt, claim_token, now + claim_seconds, now, effect_id),
            )
            claimed = cursor.execute(
                "SELECT * FROM native_effects WHERE effect_id = ?", (effect_id,)
            ).fetchone()
        self._fault(fault, "after_claim")

        payload = loads_strict(claimed["payload_json"])
        if not isinstance(payload, dict):
            raise NativeControllerError("stored effect payload is invalid")
        call = PortCall(
            request_id=f"request-{effect_id.removeprefix('effect-')}-{attempt}",
            operation=str(claimed["operation"]),
            idempotency_key=str(claimed["idempotency_key"]),
            correlation_id=str(claimed["work_item_id"]),
            deadline_epoch=float(self.clock()) + claim_seconds,
            payload=payload,
        )
        self._fault(fault, "before_invoke")
        result = self.ports.get(str(claimed["port"])).invoke(call)
        self._fault(fault, "after_invoke")

        if result.outcome == Outcome.SUCCEEDED:
            status = "SUCCEEDED"
        elif result.outcome == Outcome.UNKNOWN:
            status = "UNKNOWN"
        elif result.outcome == Outcome.RETRYABLE_FAILURE and attempt < int(
            claimed["max_attempts"]
        ):
            status = "PENDING"
        else:
            status = "DEAD"
        result_document = _portable(_result_to_dict(result), "effect result")
        not_before = (
            float(self.clock()) + int(result.retry_after_seconds or 0)
            if status == "PENDING"
            else None
        )
        self._fault(fault, "before_finalize")
        with self._transaction() as cursor:
            current = cursor.execute(
                "SELECT * FROM native_effects WHERE effect_id = ?", (effect_id,)
            ).fetchone()
            if current is None or current["claim_token"] != claim_token:
                raise NativeEffectBusy("effect claim was lost before finalization")
            cursor.execute(
                """
                UPDATE native_effects SET status = ?, claim_token = NULL,
                    claim_expires_at_epoch = NULL, result_json = ?,
                    not_before_at_epoch = ?, updated_at_epoch = ?
                WHERE effect_id = ?
                """,
                (
                    status,
                    canonical_json(result_document),
                    not_before,
                    float(self.clock()),
                    effect_id,
                ),
            )
            work = self._load_work_row(cursor, str(claimed["work_item_id"]))
            synthetic_command = "command-effect-" + hashlib.sha256(
                f"{effect_id}:{attempt}".encode("utf-8")
            ).hexdigest()[:20]
            self._append_event(
                cursor,
                command_id=synthetic_command,
                idempotency_key=f"effect-result-{effect_id}-{attempt}",
                event_type=f"EFFECT_{status}",
                work_item_id=str(claimed["work_item_id"]),
                run_id=claimed["run_id"],
                revision=int(work["revision"]),
                payload={
                    "effect_id": effect_id,
                    "port": claimed["port"],
                    "operation": claimed["operation"],
                    "attempt": attempt,
                    "outcome": result.outcome.value,
                    "side_effect": result.side_effect.value,
                    "error_code": result.error_code,
                },
                evidence_refs=result.evidence_refs,
            )
            final = self._effect_dict(
                cursor.execute(
                    "SELECT * FROM native_effects WHERE effect_id = ?", (effect_id,)
                ).fetchone()
            )
        return final

    def store_evidence(
        self,
        command: dict[str, Any],
        bundle: dict[str, Any],
        *,
        fault: str | None = None,
    ) -> dict[str, Any]:
        command, command_digest = self._command(command)
        if command["command_type"] != "STORE_EVIDENCE":
            raise NativeTransitionDenied("store_evidence requires STORE_EVIDENCE")
        bundle = _portable(require_contract("evidence_bundle", bundle), "evidence bundle")
        if bundle["work_item_id"] != command["work_item_id"] or bundle["run_id"] != command["run_id"]:
            raise NativeTransitionDenied("evidence bundle belongs to another work item or run")
        with self._transaction() as cursor:
            cached = self._cached(cursor, command, command_digest)
            if cached is not None:
                return cached
            row = self._load_work_row(cursor, command["work_item_id"])
            if row["revision"] != command["expected_revision"]:
                raise NativeRevisionConflict("evidence expected_revision differs from current")
            existing = cursor.execute(
                "SELECT document_json FROM native_evidence_bundles WHERE bundle_id = ?",
                (bundle["bundle_id"],),
            ).fetchone()
            if existing is not None:
                if loads_strict(existing["document_json"]) != bundle:
                    raise NativeIdempotencyConflict("evidence bundle id was reused with new content")
            else:
                cursor.execute(
                    """
                    INSERT INTO native_evidence_bundles(
                        bundle_id, work_item_id, run_id, bundle_digest,
                        document_json, created_at_epoch
                    ) VALUES(?, ?, ?, ?, ?, ?)
                    """,
                    (
                        bundle["bundle_id"],
                        bundle["work_item_id"],
                        bundle["run_id"],
                        bundle["bundle_digest"],
                        canonical_json(bundle),
                        float(self.clock()),
                    ),
                )
            run = self._row_document(row, "run_json")
            if run is None or run["run_id"] != bundle["run_id"]:
                raise NativeTransitionDenied("current Run does not match evidence bundle")
            reference = f"evidence:{bundle['bundle_id']}@{bundle['bundle_digest']}"
            run["evidence_bundle_refs"] = list(
                dict.fromkeys([*run["evidence_bundle_refs"], reference])
            )
            run["updated_at"] = _iso(float(self.clock()))
            require_contract("run", run)
            cursor.execute(
                "UPDATE native_work_items SET run_json = ?, updated_at_epoch = ? WHERE work_item_id = ?",
                (canonical_json(run), float(self.clock()), command["work_item_id"]),
            )
            event = self._append_event(
                cursor,
                command_id=command["command_id"],
                idempotency_key=command["idempotency_key"],
                event_type="EVIDENCE_STORED",
                work_item_id=command["work_item_id"],
                run_id=command["run_id"],
                revision=command["expected_revision"],
                payload={
                    "bundle_id": bundle["bundle_id"],
                    "bundle_digest": bundle["bundle_digest"],
                },
                evidence_refs=[reference],
            )
            result = {"bundle": bundle, "run": run, "event": event, "replayed": False}
            self._save_command(cursor, command, command_digest, result)
            self._fault(fault, "before_commit")
        self._fault(fault, "after_commit")
        return result

    def recover_orphans(self) -> dict[str, Any]:
        now = float(self.clock())
        recovered_leases = 0
        recovered_effects = 0
        with self._transaction() as cursor:
            leases = list(
                cursor.execute(
                    "SELECT * FROM native_leases WHERE expires_at_epoch <= ?", (now,)
                )
            )
            for lease in leases:
                row = self._load_work_row(cursor, lease["work_item_id"])
                run = self._row_document(row, "run_json")
                if run is not None and isinstance(run.get("lease"), dict):
                    if run["lease"].get("lease_id") == lease["lease_id"]:
                        run["lease"] = None
                        run["updated_at"] = _iso(now)
                        require_contract("run", run)
                        cursor.execute(
                            "UPDATE native_work_items SET run_json = ?, updated_at_epoch = ? WHERE work_item_id = ?",
                            (canonical_json(run), now, lease["work_item_id"]),
                        )
                cursor.execute(
                    "DELETE FROM native_leases WHERE work_item_id = ?",
                    (lease["work_item_id"],),
                )
                command_id = "command-recover-" + hashlib.sha256(
                    str(lease["lease_id"]).encode("utf-8")
                ).hexdigest()[:20]
                self._append_event(
                    cursor,
                    command_id=command_id,
                    idempotency_key=f"recover-{lease['lease_id']}",
                    event_type="LEASE_EXPIRED_RECOVERED",
                    work_item_id=lease["work_item_id"],
                    run_id=run["run_id"] if run is not None else None,
                    revision=int(row["revision"]),
                    payload={"lease_id": lease["lease_id"]},
                )
                recovered_leases += 1
            effects = list(
                cursor.execute(
                    "SELECT effect_id FROM native_effects WHERE status = 'CLAIMED' AND claim_expires_at_epoch <= ?",
                    (now,),
                )
            )
            for effect in effects:
                cursor.execute(
                    """
                    UPDATE native_effects SET status = 'PENDING', claim_token = NULL,
                        claim_expires_at_epoch = NULL, updated_at_epoch = ?
                    WHERE effect_id = ?
                    """,
                    (now, effect["effect_id"]),
                )
                recovered_effects += 1
        return {
            "recovered_leases": recovered_leases,
            "recovered_effects": recovered_effects,
            "recovered_at": _iso(now),
        }

    def get_work_item(self, work_item_id: str) -> dict[str, Any]:
        row = self.connection.execute(
            "SELECT * FROM native_work_items WHERE work_item_id = ?", (work_item_id,)
        ).fetchone()
        if row is None:
            raise NativeTransitionDenied(f"unknown work item: {work_item_id}")
        return {
            "work_item": self._row_document(row, "document_json"),
            "plan_revision": self._row_document(row, "plan_json"),
            "approval_grant": self._row_document(row, "approval_json"),
            "run": self._row_document(row, "run_json"),
        }

    def get_effect(self, effect_id: str) -> dict[str, Any]:
        row = self.connection.execute(
            "SELECT * FROM native_effects WHERE effect_id = ?", (effect_id,)
        ).fetchone()
        if row is None:
            raise NativeControllerError(f"unknown effect: {effect_id}")
        return self._effect_dict(row)

    def export_events(self, work_item_id: str | None = None) -> list[dict[str, Any]]:
        if work_item_id is None:
            rows = self.connection.execute(
                "SELECT event_json FROM native_events ORDER BY sequence"
            )
        else:
            rows = self.connection.execute(
                "SELECT event_json FROM native_events WHERE work_item_id = ? ORDER BY sequence",
                (work_item_id,),
            )
        events: list[dict[str, Any]] = []
        for row in rows:
            event = loads_strict(row["event_json"])
            events.append(require_contract("event_envelope", event))
        return events

    def verify_audit(self) -> dict[str, Any]:
        previous: str | None = None
        count = 0
        for row in self.connection.execute("SELECT * FROM native_events ORDER BY sequence"):
            event = loads_strict(row["event_json"])
            require_contract("event_envelope", event)
            event_digest = digest_value(event)
            if event_digest != row["event_digest"]:
                raise NativeControllerError(f"event digest mismatch at sequence {row['sequence']}")
            if row["previous_chain_digest"] != previous:
                raise NativeControllerError(f"event chain predecessor mismatch at {row['sequence']}")
            chain = digest_value(
                {"previous_chain_digest": previous, "event_digest": event_digest}
            )
            if chain != row["chain_digest"]:
                raise NativeControllerError(f"event chain digest mismatch at {row['sequence']}")
            previous = chain
            count += 1
        return {"status": "VALID", "events": count, "head_chain_digest": previous}

    def verify_invariants(self) -> dict[str, Any]:
        work_items = 0
        for row in self.connection.execute("SELECT * FROM native_work_items"):
            work = self._row_document(row, "document_json")
            if work is None:
                raise NativeControllerError("stored WorkItem is missing")
            require_contract("work_item", work)
            if work["state"] != row["state"] or work["revision"] != row["revision"]:
                raise NativeControllerError("WorkItem columns and document differ")
            for field, contract in (
                ("plan_json", "plan_revision"),
                ("approval_json", "approval_grant"),
                ("run_json", "run"),
            ):
                document = self._row_document(row, field)
                if document is not None:
                    require_contract(contract, document)
            work_items += 1
        effects = int(
            self.connection.execute("SELECT COUNT(*) FROM native_effects").fetchone()[0]
        )
        evidence = int(
            self.connection.execute("SELECT COUNT(*) FROM native_evidence_bundles").fetchone()[0]
        )
        return {
            "status": "VALID",
            "work_items": work_items,
            "effects": effects,
            "evidence_bundles": evidence,
            "audit": self.verify_audit(),
        }

    def status(self) -> dict[str, Any]:
        states = {
            str(row["state"]): int(row["count"])
            for row in self.connection.execute(
                "SELECT state, COUNT(*) AS count FROM native_work_items GROUP BY state"
            )
        }
        effects = {
            str(row["status"]): int(row["count"])
            for row in self.connection.execute(
                "SELECT status, COUNT(*) AS count FROM native_effects GROUP BY status"
            )
        }
        return {
            "schema_version": NATIVE_SCHEMA_VERSION,
            "database": str(self.database),
            "workflow_digest": self.workflow_digest,
            "default_stop_state": "DRAFT_PR_READY",
            "merge_enabled": False,
            "deploy_enabled": False,
            "states": states,
            "effects": effects,
            "active_leases": int(
                self.connection.execute("SELECT COUNT(*) FROM native_leases").fetchone()[0]
            ),
        }

    def backup(self, output: Path) -> dict[str, Any]:
        target = output.resolve()
        if output.is_symlink() or target.exists():
            raise NativeControllerError("backup target must be a new non-symlink path")
        target.parent.mkdir(parents=True, exist_ok=True)
        destination = sqlite3.connect(target)
        try:
            self.connection.backup(destination)
        finally:
            destination.close()
        digest = "sha256:" + hashlib.sha256(target.read_bytes()).hexdigest()
        return {
            "status": "CREATED",
            "path": str(target),
            "digest": digest,
            "bytes": target.stat().st_size,
            "audit": self.verify_audit(),
        }
