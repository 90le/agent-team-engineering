"""Transactional, restart-safe control plane with leases, audit, and an outbox."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import sqlite3
import tempfile
import time
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from core.approval import ApprovalVerifier
from core.json_support import loads_strict
from core.models import Actor, FeedbackEvent, WorkItem
from core.policy import ROLE_CAPABILITIES, PermissionDenied
from core.security import find_inline_secret
from core.simulation import create_work_item
from core.workflow import TRANSITIONS, RevisionConflict, transition

DATABASE_SCHEMA_VERSION = 1
GENESIS_HASH = "sha256:" + ("0" * 64)
MAX_JSON_BYTES = 1_000_000
MAX_LEASE_SECONDS = 3600
MAX_EFFECT_LEASE_SECONDS = 3600
IDEMPOTENCY_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}$")


SCHEMA_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS schema_migrations (
        version INTEGER PRIMARY KEY,
        applied_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS control_state (
        singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
        paused INTEGER NOT NULL CHECK (paused IN (0, 1)),
        reason TEXT,
        changed_by TEXT,
        changed_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS work_items (
        id TEXT PRIMARY KEY,
        source_key TEXT NOT NULL UNIQUE,
        source_digest TEXT NOT NULL,
        item_json TEXT NOT NULL,
        state TEXT NOT NULL,
        revision INTEGER NOT NULL CHECK (revision >= 0),
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS idempotency_records (
        idempotency_key TEXT PRIMARY KEY,
        operation_kind TEXT NOT NULL,
        request_hash TEXT NOT NULL,
        result_json TEXT NOT NULL,
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS leases (
        work_item_id TEXT PRIMARY KEY REFERENCES work_items(id) ON DELETE CASCADE,
        lease_id TEXT NOT NULL UNIQUE,
        actor_id TEXT NOT NULL,
        actor_role TEXT NOT NULL,
        revision INTEGER NOT NULL,
        expires_at REAL NOT NULL,
        created_at TEXT NOT NULL,
        renewed_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS audit_log (
        sequence INTEGER PRIMARY KEY,
        event_id TEXT NOT NULL UNIQUE,
        event_kind TEXT NOT NULL,
        work_item_id TEXT REFERENCES work_items(id) ON DELETE RESTRICT,
        payload_json TEXT NOT NULL,
        previous_hash TEXT NOT NULL,
        event_hash TEXT NOT NULL UNIQUE,
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS outbox (
        effect_id TEXT PRIMARY KEY,
        work_item_id TEXT NOT NULL REFERENCES work_items(id) ON DELETE RESTRICT,
        authorization_event_sequence INTEGER NOT NULL REFERENCES audit_log(sequence) ON DELETE RESTRICT,
        adapter_slot TEXT NOT NULL,
        operation TEXT NOT NULL,
        idempotency_key TEXT NOT NULL UNIQUE,
        request_hash TEXT NOT NULL,
        payload_json TEXT NOT NULL,
        state TEXT NOT NULL CHECK (state IN ('PENDING', 'CLAIMED', 'FAILED', 'COMPLETED', 'DEAD')),
        attempts INTEGER NOT NULL CHECK (attempts >= 0),
        max_attempts INTEGER NOT NULL CHECK (max_attempts >= 1),
        available_at REAL NOT NULL,
        claim_owner TEXT,
        claim_token TEXT,
        claim_expires_at REAL,
        result_json TEXT,
        last_error TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_outbox_dispatch ON outbox(state, available_at, effect_id)",
    "CREATE INDEX IF NOT EXISTS idx_audit_work_item ON audit_log(work_item_id, sequence)",
)


class ControlPlaneError(RuntimeError):
    pass


class DatabaseVersionError(ControlPlaneError):
    pass


class WorkItemNotFound(ControlPlaneError):
    pass


class IdempotencyConflict(ControlPlaneError):
    pass


class LeaseConflict(ControlPlaneError):
    pass


class LeaseRequired(ControlPlaneError):
    pass


class ControlPlanePaused(ControlPlaneError):
    pass


class AuditIntegrityError(ControlPlaneError):
    pass


class OutboxConflict(ControlPlaneError):
    pass


def _canonical_json(value: Any) -> str:
    try:
        content = json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError) as exc:
        raise ControlPlaneError(f"value is not JSON serializable: {exc}") from exc
    if len(content.encode("utf-8")) > MAX_JSON_BYTES:
        raise ControlPlaneError(f"JSON payload exceeds {MAX_JSON_BYTES} bytes")
    return content


def _sha256(value: str | bytes) -> str:
    content = value.encode("utf-8") if isinstance(value, str) else value
    return "sha256:" + hashlib.sha256(content).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _timestamp(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, tz=UTC).replace(microsecond=0).isoformat()


def _validate_idempotency_key(value: str) -> None:
    if not IDEMPOTENCY_KEY.fullmatch(value):
        raise ControlPlaneError("idempotency key must use 1-200 safe ASCII characters")


def _validate_bounded_text(name: str, value: str, maximum: int = 500) -> str:
    if not isinstance(value, str):
        raise ControlPlaneError(f"{name} must be a string")
    normalized = value.strip()
    if not normalized or len(normalized) > maximum:
        raise ControlPlaneError(f"{name} must contain 1-{maximum} characters")
    return normalized


def _require_no_inline_secret(name: str, value: Any) -> None:
    location = find_inline_secret(value)
    if location:
        raise ControlPlaneError(
            f"{name} contains an inline secret field or credential-like value at {location}"
        )


class ControlPlane:
    """A single SQLite-backed instance control plane.

    Each process uses its own connection. SQLite `BEGIN IMMEDIATE`, optimistic
    work-item revisions, persistent leases, and idempotency records serialize
    competing writers without depending on an agent's memory.
    """

    def __init__(
        self,
        database: Path,
        *,
        create: bool = True,
        clock: Callable[[], float] = time.time,
        approval_verifier: ApprovalVerifier | None = None,
    ) -> None:
        self.path = database.resolve()
        self.clock = clock
        self.approval_verifier = approval_verifier
        if database.is_symlink():
            raise ControlPlaneError("control-plane database must not be a symbolic link")
        if not self.path.exists() and not create:
            raise ControlPlaneError(f"control-plane database does not exist: {self.path}")
        if create:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path, timeout=5.0, isolation_level=None)
        try:
            self.connection.row_factory = sqlite3.Row
            self.connection.execute("PRAGMA foreign_keys = ON")
            self.connection.execute("PRAGMA busy_timeout = 5000")
            self.connection.execute("PRAGMA synchronous = FULL")
            self.connection.execute("PRAGMA journal_mode = WAL")
            if create:
                os.chmod(self.path, 0o600)
                self._initialize()
            else:
                if self.path.stat().st_mode & 0o077:
                    raise ControlPlaneError(
                        "control-plane database permissions must deny group and other access"
                    )
                self._assert_schema()
        except Exception:
            self.connection.close()
            raise

    def __enter__(self) -> ControlPlane:
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
        except Exception:
            self.connection.rollback()
            raise
        else:
            self.connection.commit()
        finally:
            cursor.close()

    def _initialize(self) -> None:
        current = int(self.connection.execute("PRAGMA user_version").fetchone()[0])
        if current not in {0, DATABASE_SCHEMA_VERSION}:
            raise DatabaseVersionError(
                f"database schema {current} is not supported by runtime {DATABASE_SCHEMA_VERSION}"
            )
        with self._transaction() as cursor:
            for statement in SCHEMA_STATEMENTS:
                cursor.execute(statement)
            now = _timestamp(self.clock())
            cursor.execute(
                "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                (DATABASE_SCHEMA_VERSION, now),
            )
            cursor.execute(
                """
                INSERT OR IGNORE INTO control_state(singleton, paused, reason, changed_by, changed_at)
                VALUES (1, 0, NULL, NULL, ?)
                """,
                (now,),
            )
            cursor.execute(f"PRAGMA user_version = {DATABASE_SCHEMA_VERSION}")
        self._assert_schema()

    def _assert_schema(self) -> None:
        current = int(self.connection.execute("PRAGMA user_version").fetchone()[0])
        if current != DATABASE_SCHEMA_VERSION:
            raise DatabaseVersionError(
                f"database schema {current} is not supported by runtime {DATABASE_SCHEMA_VERSION}"
            )
        required = {
            "schema_migrations",
            "control_state",
            "work_items",
            "idempotency_records",
            "leases",
            "audit_log",
            "outbox",
        }
        present = {
            str(row[0])
            for row in self.connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        missing = required - present
        if missing:
            raise DatabaseVersionError(f"control-plane database is incomplete: {sorted(missing)}")

    def _is_paused(self, cursor: sqlite3.Cursor) -> bool:
        row = cursor.execute("SELECT paused FROM control_state WHERE singleton = 1").fetchone()
        return bool(row["paused"])

    def _require_running(self, cursor: sqlite3.Cursor) -> None:
        if self._is_paused(cursor):
            raise ControlPlanePaused("control plane is paused; no new work may start")

    def _append_audit(
        self,
        cursor: sqlite3.Cursor,
        event_kind: str,
        data: dict[str, Any],
        *,
        work_item_id: str | None = None,
    ) -> dict[str, Any]:
        last = cursor.execute(
            "SELECT sequence, event_hash FROM audit_log ORDER BY sequence DESC LIMIT 1"
        ).fetchone()
        sequence = int(last["sequence"]) + 1 if last else 1
        previous_hash = str(last["event_hash"]) if last else GENESIS_HASH
        created_at = _timestamp(self.clock())
        envelope = {
            "schema_version": "1.0.0",
            "sequence": sequence,
            "event_id": f"audit-{uuid.uuid4()}",
            "event_kind": event_kind,
            "work_item_id": work_item_id,
            "created_at": created_at,
            "data": data,
        }
        payload_json = _canonical_json(envelope)
        event_hash = _sha256(previous_hash + "\n" + payload_json)
        cursor.execute(
            """
            INSERT INTO audit_log(
                sequence, event_id, event_kind, work_item_id, payload_json,
                previous_hash, event_hash, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                sequence,
                envelope["event_id"],
                event_kind,
                work_item_id,
                payload_json,
                previous_hash,
                event_hash,
                created_at,
            ),
        )
        return {**envelope, "previous_hash": previous_hash, "event_hash": event_hash}

    def _idempotent_replay(
        self,
        cursor: sqlite3.Cursor,
        idempotency_key: str,
        operation_kind: str,
        request: dict[str, Any],
    ) -> tuple[str, dict[str, Any] | None]:
        _validate_idempotency_key(idempotency_key)
        request_hash = _sha256(_canonical_json(request))
        row = cursor.execute(
            """
            SELECT operation_kind, request_hash, result_json
            FROM idempotency_records WHERE idempotency_key = ?
            """,
            (idempotency_key,),
        ).fetchone()
        if not row:
            return request_hash, None
        if row["operation_kind"] != operation_kind or row["request_hash"] != request_hash:
            raise IdempotencyConflict(
                "idempotency key was already used for a different operation or request"
            )
        result = loads_strict(str(row["result_json"]))
        result["replayed"] = True
        return request_hash, result

    def _record_idempotency(
        self,
        cursor: sqlite3.Cursor,
        idempotency_key: str,
        operation_kind: str,
        request_hash: str,
        result: dict[str, Any],
    ) -> None:
        cursor.execute(
            """
            INSERT INTO idempotency_records(
                idempotency_key, operation_kind, request_hash, result_json, created_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                idempotency_key,
                operation_kind,
                request_hash,
                _canonical_json(result),
                _timestamp(self.clock()),
            ),
        )

    def _load_item(self, cursor: sqlite3.Cursor, work_item_id: str) -> WorkItem:
        row = cursor.execute(
            "SELECT item_json FROM work_items WHERE id = ?", (work_item_id,)
        ).fetchone()
        if not row:
            raise WorkItemNotFound(work_item_id)
        value = loads_strict(str(row["item_json"]))
        return WorkItem.from_dict(value)

    def get_work_item(self, work_item_id: str) -> WorkItem:
        cursor = self.connection.cursor()
        try:
            return self._load_item(cursor, work_item_id)
        finally:
            cursor.close()

    def list_work_items(self) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            "SELECT id, state, revision, updated_at FROM work_items ORDER BY id"
        ).fetchall()
        return [dict(row) for row in rows]

    def get_audit_event(self, sequence: int) -> dict[str, Any]:
        if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 1:
            raise ControlPlaneError("audit sequence must be a positive integer")
        row = self.connection.execute(
            "SELECT payload_json FROM audit_log WHERE sequence = ?", (sequence,)
        ).fetchone()
        if not row:
            raise ControlPlaneError(f"audit event does not exist: {sequence}")
        try:
            value = loads_strict(str(row["payload_json"]))
        except ValueError as exc:
            raise AuditIntegrityError(f"invalid audit JSON at sequence {sequence}: {exc}") from exc
        if not isinstance(value, dict):
            raise AuditIntegrityError(f"audit event is not an object: {sequence}")
        return value

    def latest_authorization_event(self, work_item_id: str) -> dict[str, Any]:
        """Return the newest durable event that may authorize a bound outbox effect."""

        work_item_id = _validate_bounded_text("work_item_id", work_item_id, 200)
        row = self.connection.execute(
            """
            SELECT sequence, payload_json FROM audit_log
            WHERE work_item_id = ?
              AND event_kind IN ('work.created', 'workflow.transition')
            ORDER BY sequence DESC
            LIMIT 1
            """,
            (work_item_id,),
        ).fetchone()
        if not row:
            raise ControlPlaneError(
                f"work item has no durable authorization event: {work_item_id}"
            )
        try:
            event = loads_strict(str(row["payload_json"]))
        except ValueError as exc:
            raise AuditIntegrityError(
                f"invalid audit JSON at sequence {row['sequence']}: {exc}"
            ) from exc
        if not isinstance(event, dict):
            raise AuditIntegrityError(
                f"audit event is not an object: {row['sequence']}"
            )
        return {"sequence": int(row["sequence"]), "event": event}

    def ingest_feedback(
        self,
        event: FeedbackEvent,
        *,
        idempotency_key: str,
    ) -> dict[str, Any]:
        request = {"event": event.to_dict()}
        with self._transaction() as cursor:
            request_hash, replay = self._idempotent_replay(
                cursor, idempotency_key, "feedback.ingest", request
            )
            if replay is not None:
                return replay
            self._require_running(cursor)
            source_key = f"{event.channel}\0{event.message_id}"
            source_digest = _sha256(_canonical_json(event.to_dict()))
            existing = cursor.execute(
                "SELECT source_digest, item_json FROM work_items WHERE source_key = ?",
                (source_key,),
            ).fetchone()
            if existing:
                if existing["source_digest"] != source_digest:
                    raise IdempotencyConflict(
                        "feedback source identity was reused with different content"
                    )
                item = WorkItem.from_dict(loads_strict(str(existing["item_json"])))
                result = {"replayed": True, "work_item": item.to_dict(), "audit_sequence": None}
                self._record_idempotency(
                    cursor, idempotency_key, "feedback.ingest", request_hash, result
                )
                return result

            item = create_work_item(event)
            now = _timestamp(self.clock())
            cursor.execute(
                """
                INSERT INTO work_items(
                    id, source_key, source_digest, item_json, state, revision, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item.id,
                    source_key,
                    source_digest,
                    _canonical_json(item.to_dict()),
                    item.state.value,
                    item.revision,
                    now,
                    now,
                ),
            )
            audit = self._append_audit(
                cursor,
                "work.created",
                {
                    "source_event_id": event.event_id,
                    "source_channel": event.channel,
                    "source_message_id": event.message_id,
                    "risk": item.risk.value,
                    "untrusted_directive_detected": item.untrusted_directive_detected,
                },
                work_item_id=item.id,
            )
            result = {
                "replayed": False,
                "work_item": item.to_dict(),
                "audit_sequence": audit["sequence"],
            }
            self._record_idempotency(
                cursor, idempotency_key, "feedback.ingest", request_hash, result
            )
            return result

    def _role_has_next_action(self, item: WorkItem, actor: Actor) -> bool:
        capabilities = ROLE_CAPABILITIES.get(actor.role, frozenset())
        return any(
            item.state in rule.from_states and rule.capability in capabilities
            for rule in TRANSITIONS.values()
        )

    def acquire_lease(
        self,
        work_item_id: str,
        actor: Actor,
        *,
        expected_revision: int,
        ttl_seconds: int,
        idempotency_key: str,
    ) -> dict[str, Any]:
        if actor.kind == "human" or actor.role == "owner":
            raise PermissionDenied("human owner approvals do not use agent task leases")
        if not 1 <= ttl_seconds <= MAX_LEASE_SECONDS:
            raise ControlPlaneError(f"lease ttl must be between 1 and {MAX_LEASE_SECONDS} seconds")
        request = {
            "work_item_id": work_item_id,
            "actor": actor.to_dict(),
            "expected_revision": expected_revision,
            "ttl_seconds": ttl_seconds,
        }
        with self._transaction() as cursor:
            request_hash, replay = self._idempotent_replay(
                cursor, idempotency_key, "lease.acquire", request
            )
            if replay is not None:
                return replay
            self._require_running(cursor)
            item = self._load_item(cursor, work_item_id)
            if item.revision != expected_revision:
                raise RevisionConflict(
                    f"expected revision {expected_revision}, current revision is {item.revision}"
                )
            if not self._role_has_next_action(item, actor):
                raise PermissionDenied(
                    f"role {actor.role} has no permitted action from {item.state.value}"
                )
            now_epoch = self.clock()
            existing = cursor.execute(
                "SELECT * FROM leases WHERE work_item_id = ?", (work_item_id,)
            ).fetchone()
            if existing and float(existing["expires_at"]) > now_epoch:
                raise LeaseConflict(
                    f"work item already leased by {existing['actor_id']} until {existing['expires_at']}"
                )
            if existing:
                cursor.execute("DELETE FROM leases WHERE work_item_id = ?", (work_item_id,))
                self._append_audit(
                    cursor,
                    "lease.expired",
                    {
                        "lease_id": existing["lease_id"],
                        "actor_id": existing["actor_id"],
                        "revision": existing["revision"],
                    },
                    work_item_id=work_item_id,
                )

            lease_id = f"lease-{uuid.uuid4()}"
            expires_at = now_epoch + ttl_seconds
            now = _timestamp(now_epoch)
            cursor.execute(
                """
                INSERT INTO leases(
                    work_item_id, lease_id, actor_id, actor_role, revision,
                    expires_at, created_at, renewed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    work_item_id,
                    lease_id,
                    actor.id,
                    actor.role,
                    item.revision,
                    expires_at,
                    now,
                    now,
                ),
            )
            audit = self._append_audit(
                cursor,
                "lease.acquired",
                {
                    "lease_id": lease_id,
                    "actor_id": actor.id,
                    "actor_role": actor.role,
                    "revision": item.revision,
                    "expires_at": expires_at,
                },
                work_item_id=work_item_id,
            )
            result = {
                "replayed": False,
                "lease": {
                    "lease_id": lease_id,
                    "work_item_id": work_item_id,
                    "actor_id": actor.id,
                    "actor_role": actor.role,
                    "revision": item.revision,
                    "expires_at": expires_at,
                },
                "audit_sequence": audit["sequence"],
            }
            self._record_idempotency(cursor, idempotency_key, "lease.acquire", request_hash, result)
            return result

    def active_lease(self, work_item_id: str) -> dict[str, Any] | None:
        """Return a non-expired lease for crash-safe coordinator resumption."""

        work_item_id = _validate_bounded_text("work_item_id", work_item_id, 200)
        row = self.connection.execute(
            "SELECT * FROM leases WHERE work_item_id = ?", (work_item_id,)
        ).fetchone()
        if not row or float(row["expires_at"]) <= self.clock():
            return None
        return {
            "lease_id": str(row["lease_id"]),
            "work_item_id": str(row["work_item_id"]),
            "actor_id": str(row["actor_id"]),
            "actor_role": str(row["actor_role"]),
            "revision": int(row["revision"]),
            "expires_at": float(row["expires_at"]),
        }

    def renew_lease(
        self,
        lease_id: str,
        actor: Actor,
        *,
        ttl_seconds: int,
        idempotency_key: str,
    ) -> dict[str, Any]:
        if not 1 <= ttl_seconds <= MAX_LEASE_SECONDS:
            raise ControlPlaneError(f"lease ttl must be between 1 and {MAX_LEASE_SECONDS} seconds")
        request = {"lease_id": lease_id, "actor": actor.to_dict(), "ttl_seconds": ttl_seconds}
        with self._transaction() as cursor:
            request_hash, replay = self._idempotent_replay(
                cursor, idempotency_key, "lease.renew", request
            )
            if replay is not None:
                return replay
            self._require_running(cursor)
            row = cursor.execute("SELECT * FROM leases WHERE lease_id = ?", (lease_id,)).fetchone()
            now_epoch = self.clock()
            if not row or float(row["expires_at"]) <= now_epoch:
                raise LeaseConflict("lease is missing or expired")
            if row["actor_id"] != actor.id or row["actor_role"] != actor.role:
                raise LeaseConflict("only the lease holder may renew it")
            item = self._load_item(cursor, str(row["work_item_id"]))
            if item.revision != int(row["revision"]):
                raise LeaseConflict("work item revision changed after lease acquisition")
            expires_at = now_epoch + ttl_seconds
            cursor.execute(
                "UPDATE leases SET expires_at = ?, renewed_at = ? WHERE lease_id = ?",
                (expires_at, _timestamp(now_epoch), lease_id),
            )
            audit = self._append_audit(
                cursor,
                "lease.renewed",
                {"lease_id": lease_id, "actor_id": actor.id, "expires_at": expires_at},
                work_item_id=str(row["work_item_id"]),
            )
            result = {
                "replayed": False,
                "lease_id": lease_id,
                "expires_at": expires_at,
                "audit_sequence": audit["sequence"],
            }
            self._record_idempotency(cursor, idempotency_key, "lease.renew", request_hash, result)
            return result

    def release_lease(
        self,
        lease_id: str,
        actor: Actor,
        *,
        idempotency_key: str,
    ) -> dict[str, Any]:
        request = {"lease_id": lease_id, "actor": actor.to_dict()}
        with self._transaction() as cursor:
            request_hash, replay = self._idempotent_replay(
                cursor, idempotency_key, "lease.release", request
            )
            if replay is not None:
                return replay
            row = cursor.execute("SELECT * FROM leases WHERE lease_id = ?", (lease_id,)).fetchone()
            if not row:
                raise LeaseConflict("lease does not exist")
            if row["actor_id"] != actor.id or row["actor_role"] != actor.role:
                raise LeaseConflict("only the lease holder may release it")
            cursor.execute("DELETE FROM leases WHERE lease_id = ?", (lease_id,))
            audit = self._append_audit(
                cursor,
                "lease.released",
                {"lease_id": lease_id, "actor_id": actor.id},
                work_item_id=str(row["work_item_id"]),
            )
            result = {
                "replayed": False,
                "released": True,
                "audit_sequence": audit["sequence"],
            }
            self._record_idempotency(cursor, idempotency_key, "lease.release", request_hash, result)
            return result

    def apply_transition(
        self,
        work_item_id: str,
        action: str,
        actor: Actor,
        evidence: dict[str, str],
        *,
        expected_revision: int,
        idempotency_key: str,
        lease_id: str | None = None,
        approval_assertion: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not all(
            isinstance(key, str) and isinstance(value, str) for key, value in evidence.items()
        ):
            raise ControlPlaneError("transition evidence must contain only string keys and values")
        _require_no_inline_secret("transition evidence", evidence)
        if approval_assertion is not None:
            _require_no_inline_secret("approval assertion", approval_assertion)
            assertion_digest: str | None = _sha256(_canonical_json(approval_assertion))
        else:
            assertion_digest = None
        request = {
            "work_item_id": work_item_id,
            "action": action,
            "actor": actor.to_dict(),
            "evidence": dict(sorted(evidence.items())),
            "expected_revision": expected_revision,
            "lease_id": lease_id,
            "approval_assertion_digest": assertion_digest,
        }
        with self._transaction() as cursor:
            request_hash, replay = self._idempotent_replay(
                cursor, idempotency_key, "workflow.transition", request
            )
            if replay is not None:
                return replay
            self._require_running(cursor)
            item = self._load_item(cursor, work_item_id)
            if item.revision != expected_revision:
                raise RevisionConflict(
                    f"expected revision {expected_revision}, current revision is {item.revision}"
                )

            held_lease: sqlite3.Row | None = None
            transition_evidence = dict(evidence)
            if actor.role == "owner":
                if actor.kind != "human":
                    raise PermissionDenied("owner approval actor must be human")
                if self.approval_verifier is None or approval_assertion is None:
                    raise PermissionDenied(
                        "owner transition requires an authenticated approval verifier and assertion"
                    )
                verified = self.approval_verifier.verify(
                    approval_assertion,
                    actor_id=actor.id,
                    action=action,
                    work_item_id=work_item_id,
                    expected_revision=expected_revision,
                    evidence=evidence,
                )
                transition_evidence.update(
                    {
                        "approval_provider": verified.provider,
                        "approval_evidence_ref": verified.evidence_ref,
                        "approval_claim_digest": verified.claim_digest,
                    }
                )
            else:
                if approval_assertion is not None:
                    raise PermissionDenied(
                        "approval assertions are accepted only for owner transitions"
                    )
                if not lease_id:
                    raise LeaseRequired("non-owner transitions require an active task lease")
                held_lease = cursor.execute(
                    "SELECT * FROM leases WHERE lease_id = ? AND work_item_id = ?",
                    (lease_id, work_item_id),
                ).fetchone()
                if not held_lease:
                    raise LeaseRequired("task lease does not exist for this work item")
                if (
                    held_lease["actor_id"] != actor.id
                    or held_lease["actor_role"] != actor.role
                    or int(held_lease["revision"]) != item.revision
                ):
                    raise LeaseConflict("task lease holder, role, or revision does not match")
                if float(held_lease["expires_at"]) <= self.clock():
                    raise LeaseConflict("task lease expired before transition commit")

            old_revision = item.revision
            transition(
                item,
                action,
                actor,
                transition_evidence,
                expected_revision=expected_revision,
            )
            updated = cursor.execute(
                """
                UPDATE work_items
                SET item_json = ?, state = ?, revision = ?, updated_at = ?
                WHERE id = ? AND revision = ?
                """,
                (
                    _canonical_json(item.to_dict()),
                    item.state.value,
                    item.revision,
                    _timestamp(self.clock()),
                    work_item_id,
                    old_revision,
                ),
            )
            if updated.rowcount != 1:
                raise RevisionConflict("concurrent transition changed the work item")
            if held_lease:
                cursor.execute("DELETE FROM leases WHERE lease_id = ?", (lease_id,))
            audit = self._append_audit(
                cursor,
                "workflow.transition",
                {
                    "transition": asdict(item.audit[-1]),
                    "idempotency_key": idempotency_key,
                    "lease_id": lease_id,
                },
                work_item_id=work_item_id,
            )
            result = {
                "replayed": False,
                "work_item": item.to_dict(),
                "audit_sequence": audit["sequence"],
                "audit_hash": audit["event_hash"],
            }
            self._record_idempotency(
                cursor, idempotency_key, "workflow.transition", request_hash, result
            )
            return result

    def set_paused(
        self,
        paused: bool,
        actor: Actor,
        *,
        reason: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        if actor.role != "owner" or actor.kind != "human":
            raise PermissionDenied("only a human owner may pause or resume the control plane")
        reason = _validate_bounded_text("reason", reason)
        _require_no_inline_secret("pause reason", reason)
        operation_kind = "control.pause" if paused else "control.resume"
        request = {"paused": paused, "actor": actor.to_dict(), "reason": reason}
        with self._transaction() as cursor:
            request_hash, replay = self._idempotent_replay(
                cursor, idempotency_key, operation_kind, request
            )
            if replay is not None:
                return replay
            current = self._is_paused(cursor)
            if current != paused:
                now = _timestamp(self.clock())
                cursor.execute(
                    """
                    UPDATE control_state
                    SET paused = ?, reason = ?, changed_by = ?, changed_at = ?
                    WHERE singleton = 1
                    """,
                    (int(paused), reason, actor.id, now),
                )
                audit = self._append_audit(
                    cursor,
                    operation_kind,
                    {"actor_id": actor.id, "reason": reason},
                )
                audit_sequence: int | None = int(audit["sequence"])
            else:
                audit_sequence = None
            result = {
                "replayed": False,
                "paused": paused,
                "changed": current != paused,
                "audit_sequence": audit_sequence,
            }
            self._record_idempotency(cursor, idempotency_key, operation_kind, request_hash, result)
            return result

    def queue_effect(
        self,
        work_item_id: str,
        *,
        authorization_event_sequence: int,
        adapter_slot: str,
        operation: str,
        payload: dict[str, Any],
        idempotency_key: str,
        max_attempts: int = 3,
        available_at: float | None = None,
    ) -> dict[str, Any]:
        _validate_idempotency_key(idempotency_key)
        adapter_slot = _validate_bounded_text("adapter_slot", adapter_slot, 100)
        operation = _validate_bounded_text("operation", operation, 100)
        if not 1 <= max_attempts <= 10:
            raise ControlPlaneError("outbox max_attempts must be between 1 and 10")
        if (
            isinstance(authorization_event_sequence, bool)
            or not isinstance(authorization_event_sequence, int)
            or authorization_event_sequence < 1
        ):
            raise ControlPlaneError("authorization_event_sequence must be a positive integer")
        if available_at is not None and (
            isinstance(available_at, bool)
            or not isinstance(available_at, (int, float))
            or not math.isfinite(available_at)
            or available_at < 0
        ):
            raise ControlPlaneError("available_at must be a finite non-negative number")
        _require_no_inline_secret("outbox payload", payload)
        request = {
            "work_item_id": work_item_id,
            "authorization_event_sequence": authorization_event_sequence,
            "adapter_slot": adapter_slot,
            "operation": operation,
            "payload": payload,
            "max_attempts": max_attempts,
            "available_at": available_at,
        }
        request_hash = _sha256(_canonical_json(request))
        with self._transaction() as cursor:
            existing = cursor.execute(
                "SELECT * FROM outbox WHERE idempotency_key = ?", (idempotency_key,)
            ).fetchone()
            if existing:
                if existing["request_hash"] != request_hash:
                    raise IdempotencyConflict(
                        "outbox idempotency key was reused with a different request"
                    )
                return {"replayed": True, "effect": self._effect_from_row(existing)}
            self._require_running(cursor)
            self._load_item(cursor, work_item_id)
            authority = cursor.execute(
                "SELECT work_item_id, event_kind FROM audit_log WHERE sequence = ?",
                (authorization_event_sequence,),
            ).fetchone()
            if (
                not authority
                or authority["work_item_id"] != work_item_id
                or authority["event_kind"] not in {"work.created", "workflow.transition"}
            ):
                raise OutboxConflict(
                    "outbox effect requires a durable work-item authorization event"
                )
            now_epoch = self.clock()
            effect_id = f"effect-{uuid.uuid4()}"
            now = _timestamp(now_epoch)
            cursor.execute(
                """
                INSERT INTO outbox(
                    effect_id, work_item_id, authorization_event_sequence,
                    adapter_slot, operation, idempotency_key, request_hash,
                    payload_json, state, attempts, max_attempts, available_at,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'PENDING', 0, ?, ?, ?, ?)
                """,
                (
                    effect_id,
                    work_item_id,
                    authorization_event_sequence,
                    adapter_slot,
                    operation,
                    idempotency_key,
                    request_hash,
                    _canonical_json(payload),
                    max_attempts,
                    available_at if available_at is not None else now_epoch,
                    now,
                    now,
                ),
            )
            audit = self._append_audit(
                cursor,
                "outbox.queued",
                {
                    "effect_id": effect_id,
                    "authorization_event_sequence": authorization_event_sequence,
                    "adapter_slot": adapter_slot,
                    "operation": operation,
                    "idempotency_key": idempotency_key,
                },
                work_item_id=work_item_id,
            )
            row = cursor.execute(
                "SELECT * FROM outbox WHERE effect_id = ?", (effect_id,)
            ).fetchone()
            return {
                "replayed": False,
                "effect": self._effect_from_row(row),
                "audit_sequence": audit["sequence"],
            }

    @staticmethod
    def _effect_from_row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "effect_id": row["effect_id"],
            "work_item_id": row["work_item_id"],
            "authorization_event_sequence": row["authorization_event_sequence"],
            "adapter_slot": row["adapter_slot"],
            "operation": row["operation"],
            "idempotency_key": row["idempotency_key"],
            "payload": loads_strict(str(row["payload_json"])),
            "state": row["state"],
            "attempts": row["attempts"],
            "max_attempts": row["max_attempts"],
            "available_at": row["available_at"],
            "claim_owner": row["claim_owner"],
            "claim_token": row["claim_token"],
            "claim_expires_at": row["claim_expires_at"],
            "result": loads_strict(str(row["result_json"])) if row["result_json"] else None,
            "last_error": row["last_error"],
        }

    def get_effect(self, effect_id: str) -> dict[str, Any]:
        effect_id = _validate_bounded_text("effect_id", effect_id, 200)
        row = self.connection.execute(
            "SELECT * FROM outbox WHERE effect_id = ?", (effect_id,)
        ).fetchone()
        if not row:
            raise OutboxConflict("outbox effect does not exist")
        return self._effect_from_row(row)

    def _recover_expired_effects(self, cursor: sqlite3.Cursor, now_epoch: float) -> int:
        rows = cursor.execute(
            "SELECT * FROM outbox WHERE state = 'CLAIMED' AND claim_expires_at <= ? ORDER BY effect_id",
            (now_epoch,),
        ).fetchall()
        for row in rows:
            state = "DEAD" if int(row["attempts"]) >= int(row["max_attempts"]) else "FAILED"
            cursor.execute(
                """
                UPDATE outbox
                SET state = ?, available_at = ?, claim_owner = NULL,
                    claim_token = NULL, claim_expires_at = NULL,
                    last_error = 'claim expired before acknowledgement', updated_at = ?
                WHERE effect_id = ? AND state = 'CLAIMED'
                """,
                (state, now_epoch, _timestamp(now_epoch), row["effect_id"]),
            )
            self._append_audit(
                cursor,
                "outbox.claim-expired",
                {
                    "effect_id": row["effect_id"],
                    "previous_claim_owner": row["claim_owner"],
                    "attempts": row["attempts"],
                    "new_state": state,
                },
                work_item_id=str(row["work_item_id"]),
            )
        return len(rows)

    def claim_effect(
        self,
        worker_id: str,
        *,
        lease_seconds: int = 60,
        effect_id: str | None = None,
    ) -> dict[str, Any] | None:
        worker_id = _validate_bounded_text("worker_id", worker_id, 200)
        if effect_id is not None:
            effect_id = _validate_bounded_text("effect_id", effect_id, 200)
        if not 1 <= lease_seconds <= MAX_EFFECT_LEASE_SECONDS:
            raise ControlPlaneError(
                f"effect lease must be between 1 and {MAX_EFFECT_LEASE_SECONDS} seconds"
            )
        with self._transaction() as cursor:
            self._require_running(cursor)
            now_epoch = self.clock()
            self._recover_expired_effects(cursor, now_epoch)
            if effect_id is None:
                row = cursor.execute(
                    """
                    SELECT * FROM outbox
                    WHERE state IN ('PENDING', 'FAILED')
                      AND available_at <= ?
                      AND attempts < max_attempts
                    ORDER BY available_at, effect_id
                    LIMIT 1
                    """,
                    (now_epoch,),
                ).fetchone()
            else:
                row = cursor.execute(
                    """
                    SELECT * FROM outbox
                    WHERE effect_id = ?
                      AND state IN ('PENDING', 'FAILED')
                      AND available_at <= ?
                      AND attempts < max_attempts
                    LIMIT 1
                    """,
                    (effect_id, now_epoch),
                ).fetchone()
            if not row:
                return None
            claim_token = f"claim-{uuid.uuid4()}"
            claim_expires_at = now_epoch + lease_seconds
            cursor.execute(
                """
                UPDATE outbox
                SET state = 'CLAIMED', attempts = attempts + 1,
                    claim_owner = ?, claim_token = ?, claim_expires_at = ?, updated_at = ?
                WHERE effect_id = ? AND state IN ('PENDING', 'FAILED')
                """,
                (
                    worker_id,
                    claim_token,
                    claim_expires_at,
                    _timestamp(now_epoch),
                    row["effect_id"],
                ),
            )
            claimed = cursor.execute(
                "SELECT * FROM outbox WHERE effect_id = ?", (row["effect_id"],)
            ).fetchone()
            audit = self._append_audit(
                cursor,
                "outbox.claimed",
                {
                    "effect_id": row["effect_id"],
                    "worker_id": worker_id,
                    "claim_token": claim_token,
                    "claim_expires_at": claim_expires_at,
                    "attempt": claimed["attempts"],
                },
                work_item_id=str(row["work_item_id"]),
            )
            return {"effect": self._effect_from_row(claimed), "audit_sequence": audit["sequence"]}

    def _require_effect_claim(
        self,
        cursor: sqlite3.Cursor,
        effect_id: str,
        worker_id: str,
        claim_token: str,
    ) -> sqlite3.Row:
        row = cursor.execute("SELECT * FROM outbox WHERE effect_id = ?", (effect_id,)).fetchone()
        if (
            not row
            or row["state"] != "CLAIMED"
            or row["claim_owner"] != worker_id
            or row["claim_token"] != claim_token
        ):
            raise OutboxConflict("effect claim is missing, completed, expired, or owned elsewhere")
        if row["claim_expires_at"] is None or float(row["claim_expires_at"]) <= self.clock():
            raise OutboxConflict("effect claim expired before acknowledgement")
        return row

    def complete_effect(
        self,
        effect_id: str,
        worker_id: str,
        claim_token: str,
        result: dict[str, Any],
    ) -> dict[str, Any]:
        _require_no_inline_secret("outbox result", result)
        result_json = _canonical_json(result)
        with self._transaction() as cursor:
            row = self._require_effect_claim(cursor, effect_id, worker_id, claim_token)
            cursor.execute(
                """
                UPDATE outbox
                SET state = 'COMPLETED', result_json = ?, last_error = NULL,
                    claim_owner = NULL, claim_token = NULL, claim_expires_at = NULL,
                    updated_at = ?
                WHERE effect_id = ?
                """,
                (result_json, _timestamp(self.clock()), effect_id),
            )
            audit = self._append_audit(
                cursor,
                "outbox.completed",
                {
                    "effect_id": effect_id,
                    "worker_id": worker_id,
                    "result_digest": _sha256(result_json),
                },
                work_item_id=str(row["work_item_id"]),
            )
            completed = cursor.execute(
                "SELECT * FROM outbox WHERE effect_id = ?", (effect_id,)
            ).fetchone()
            return {
                "effect": self._effect_from_row(completed),
                "audit_sequence": audit["sequence"],
            }

    def fail_effect(
        self,
        effect_id: str,
        worker_id: str,
        claim_token: str,
        *,
        error: str,
        retry_delay_seconds: int = 0,
        permanent: bool = False,
    ) -> dict[str, Any]:
        error = _validate_bounded_text("error", error, 1000)
        _require_no_inline_secret("outbox error", error)
        if not 0 <= retry_delay_seconds <= 86400:
            raise ControlPlaneError("retry delay must be between 0 and 86400 seconds")
        with self._transaction() as cursor:
            row = self._require_effect_claim(cursor, effect_id, worker_id, claim_token)
            now_epoch = self.clock()
            state = (
                "DEAD"
                if permanent or int(row["attempts"]) >= int(row["max_attempts"])
                else "FAILED"
            )
            cursor.execute(
                """
                UPDATE outbox
                SET state = ?, available_at = ?, last_error = ?,
                    claim_owner = NULL, claim_token = NULL, claim_expires_at = NULL,
                    updated_at = ?
                WHERE effect_id = ?
                """,
                (
                    state,
                    now_epoch + retry_delay_seconds,
                    error,
                    _timestamp(now_epoch),
                    effect_id,
                ),
            )
            audit = self._append_audit(
                cursor,
                "outbox.failed" if state == "FAILED" else "outbox.dead",
                {
                    "effect_id": effect_id,
                    "worker_id": worker_id,
                    "error_digest": _sha256(error),
                    "attempts": row["attempts"],
                    "new_state": state,
                    "permanent": permanent,
                },
                work_item_id=str(row["work_item_id"]),
            )
            failed = cursor.execute(
                "SELECT * FROM outbox WHERE effect_id = ?", (effect_id,)
            ).fetchone()
            return {
                "effect": self._effect_from_row(failed),
                "audit_sequence": audit["sequence"],
            }

    def reconcile(self) -> dict[str, int]:
        with self._transaction() as cursor:
            now_epoch = self.clock()
            expired_leases = cursor.execute(
                "SELECT * FROM leases WHERE expires_at <= ? ORDER BY lease_id", (now_epoch,)
            ).fetchall()
            for row in expired_leases:
                cursor.execute("DELETE FROM leases WHERE lease_id = ?", (row["lease_id"],))
                self._append_audit(
                    cursor,
                    "lease.expired",
                    {
                        "lease_id": row["lease_id"],
                        "actor_id": row["actor_id"],
                        "revision": row["revision"],
                    },
                    work_item_id=str(row["work_item_id"]),
                )
            expired_effects = self._recover_expired_effects(cursor, now_epoch)
            return {"expired_leases": len(expired_leases), "expired_effect_claims": expired_effects}

    def verify_audit(self) -> dict[str, Any]:
        integrity = [
            str(row[0]) for row in self.connection.execute("PRAGMA quick_check").fetchall()
        ]
        if integrity != ["ok"]:
            raise AuditIntegrityError(f"SQLite quick_check failed: {integrity}")
        foreign_key_violations = self.connection.execute("PRAGMA foreign_key_check").fetchall()
        if foreign_key_violations:
            raise AuditIntegrityError(
                f"SQLite foreign key check failed: {len(foreign_key_violations)} violation(s)"
            )
        rows = self.connection.execute("SELECT * FROM audit_log ORDER BY sequence").fetchall()
        previous_hash = GENESIS_HASH
        expected_sequence = 1
        creation_counts: dict[str, int] = {}
        transition_counts: dict[str, int] = {}
        for row in rows:
            if int(row["sequence"]) != expected_sequence:
                raise AuditIntegrityError(
                    f"audit sequence gap: expected {expected_sequence}, found {row['sequence']}"
                )
            if row["previous_hash"] != previous_hash:
                raise AuditIntegrityError(f"audit previous hash mismatch at {expected_sequence}")
            payload_json = str(row["payload_json"])
            try:
                payload = loads_strict(payload_json)
            except ValueError as exc:
                raise AuditIntegrityError(
                    f"invalid audit JSON at {expected_sequence}: {exc}"
                ) from exc
            if payload.get("sequence") != expected_sequence:
                raise AuditIntegrityError(f"audit payload sequence mismatch at {expected_sequence}")
            for column, field in (
                ("event_id", "event_id"),
                ("event_kind", "event_kind"),
                ("work_item_id", "work_item_id"),
                ("created_at", "created_at"),
            ):
                if row[column] != payload.get(field):
                    raise AuditIntegrityError(
                        f"audit {field} differs from indexed value at {expected_sequence}"
                    )
            computed = _sha256(previous_hash + "\n" + payload_json)
            if computed != row["event_hash"]:
                raise AuditIntegrityError(f"audit hash mismatch at {expected_sequence}")
            if row["event_kind"] == "workflow.transition" and row["work_item_id"]:
                key = str(row["work_item_id"])
                transition_counts[key] = transition_counts.get(key, 0) + 1
            if row["event_kind"] == "work.created" and row["work_item_id"]:
                key = str(row["work_item_id"])
                creation_counts[key] = creation_counts.get(key, 0) + 1
            previous_hash = str(row["event_hash"])
            expected_sequence += 1

        for row in self.connection.execute("SELECT id, item_json, state, revision FROM work_items"):
            item = WorkItem.from_dict(loads_strict(str(row["item_json"])))
            row_id = str(row["id"])
            if item.id != row_id:
                raise AuditIntegrityError(f"work item identity mismatch: {row_id}")
            if item.state.value != row["state"]:
                raise AuditIntegrityError(f"work item state index mismatch: {item.id}")
            if item.revision != int(row["revision"]) or item.revision != len(item.audit):
                raise AuditIntegrityError(f"work item revision/audit mismatch: {item.id}")
            if creation_counts.get(item.id, 0) != 1:
                raise AuditIntegrityError(f"persistent creation audit count mismatch: {item.id}")
            if transition_counts.get(item.id, 0) != item.revision:
                raise AuditIntegrityError(f"persistent transition audit count mismatch: {item.id}")
        return {
            "valid": True,
            "events": len(rows),
            "head": previous_hash,
            "database_schema_version": DATABASE_SCHEMA_VERSION,
        }

    def status(self) -> dict[str, Any]:
        control = self.connection.execute(
            "SELECT paused, reason, changed_by, changed_at FROM control_state WHERE singleton = 1"
        ).fetchone()
        work_states = {
            str(row["state"]): int(row["count"])
            for row in self.connection.execute(
                "SELECT state, COUNT(*) AS count FROM work_items GROUP BY state ORDER BY state"
            )
        }
        outbox_states = {
            str(row["state"]): int(row["count"])
            for row in self.connection.execute(
                "SELECT state, COUNT(*) AS count FROM outbox GROUP BY state ORDER BY state"
            )
        }
        audit = self.connection.execute(
            "SELECT sequence, event_hash FROM audit_log ORDER BY sequence DESC LIMIT 1"
        ).fetchone()
        active_leases = int(
            self.connection.execute(
                "SELECT COUNT(*) FROM leases WHERE expires_at > ?", (self.clock(),)
            ).fetchone()[0]
        )
        return {
            "database_schema_version": DATABASE_SCHEMA_VERSION,
            "paused": bool(control["paused"]),
            "pause_reason": control["reason"],
            "changed_by": control["changed_by"],
            "changed_at": control["changed_at"],
            "work_items": work_states,
            "active_leases": active_leases,
            "outbox": outbox_states,
            "audit_events": int(audit["sequence"]) if audit else 0,
            "audit_head": str(audit["event_hash"]) if audit else GENESIS_HASH,
        }

    def backup(self, destination: Path) -> dict[str, Any]:
        if destination.is_symlink():
            raise ControlPlaneError("backup destination must not be a symbolic link")
        target = destination.resolve()
        if target == self.path:
            raise ControlPlaneError("backup destination must differ from the live database")
        if target.exists():
            raise ControlPlaneError("backup destination already exists")
        target.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{target.name}.", suffix=".tmp", dir=target.parent
        )
        os.close(descriptor)
        temporary = Path(temporary_name)
        try:
            backup_connection = sqlite3.connect(temporary)
            try:
                self.connection.backup(backup_connection)
            finally:
                backup_connection.close()
            with ControlPlane(temporary, create=False, clock=self.clock) as restored:
                audit = restored.verify_audit()
                status = restored.status()
            os.replace(temporary, target)
            return {
                "path": str(target),
                "sha256": _file_sha256(target),
                "audit": audit,
                "status": status,
            }
        finally:
            for candidate in (
                temporary,
                Path(str(temporary) + "-wal"),
                Path(str(temporary) + "-shm"),
            ):
                if candidate.exists():
                    candidate.unlink()

    @classmethod
    def restore(
        cls,
        backup: Path,
        destination: Path,
        *,
        clock: Callable[[], float] = time.time,
    ) -> dict[str, Any]:
        source = backup.resolve()
        target = destination.resolve()
        if backup.is_symlink() or not source.is_file():
            raise ControlPlaneError("backup must be an existing regular non-symlink file")
        if destination.is_symlink():
            raise ControlPlaneError("restore destination must not be a symbolic link")
        if target.exists():
            raise ControlPlaneError("restore destination already exists")
        target.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{target.name}.", suffix=".restore", dir=target.parent
        )
        os.close(descriptor)
        temporary = Path(temporary_name)
        try:
            shutil.copyfile(source, temporary)
            with cls(temporary, create=False, clock=clock) as restored:
                audit = restored.verify_audit()
                status = restored.status()
            os.replace(temporary, target)
            return {
                "path": str(target),
                "sha256": _file_sha256(target),
                "audit": audit,
                "status": status,
            }
        finally:
            for candidate in (
                temporary,
                Path(str(temporary) + "-wal"),
                Path(str(temporary) + "-shm"),
            ):
                if candidate.exists():
                    candidate.unlink()
