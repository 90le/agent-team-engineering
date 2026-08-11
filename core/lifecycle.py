"""Planned, recoverable lifecycle changes for Agent Team instances."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import stat
import tempfile
from collections.abc import Callable
from contextlib import contextmanager
from pathlib import Path
from typing import Any

try:
    import fcntl
except ImportError:  # pragma: no cover - exercised on non-POSIX hosts
    fcntl = None  # type: ignore[assignment]

from core.control_plane import ControlPlane
from core.installation import current_source_release_verified
from core.instance import (
    InstanceError,
    _build_lock_from_records,
    _build_seed_files,
    _canonical_json,
    _factory_metadata,
    _is_safe_relative,
    _load_json,
    _parse_version,
    instance_summary,
    validate_instance_directory,
)
from core.schema_validation import validate_schema

ROOT = Path(__file__).resolve().parents[1]
UPGRADE_PLAN_SCHEMA = ROOT / "schemas" / "instance-upgrade-plan.schema.json"
RECOVERY_MANIFEST_SCHEMA = ROOT / "schemas" / "instance-recovery-manifest.schema.json"
LIFECYCLE_JOURNAL_SCHEMA = ROOT / "schemas" / "instance-lifecycle-journal.schema.json"
LOCK_RELATIVE = ".agent-team/instance.lock.json"
INSTANCE_RELATIVE = ".agent-team/instance.json"
JOURNAL_RELATIVE = "runtime/.factory-lifecycle-journal.json"
RESERVED_ACTION_PATHS = frozenset({LOCK_RELATIVE, INSTANCE_RELATIVE, JOURNAL_RELATIVE})
SUPPORTED_UPGRADE_SOURCES = frozenset(
    {"0.2.0", "0.3.0", "0.4.0", "0.5.0", "0.5.1", "0.6.0", "0.7.0", "0.8.0"}
)
MAX_LIFECYCLE_FILE_BYTES = 10 * 1024 * 1024
MAX_RECOVERY_BYTES = 50 * 1024 * 1024


class LifecycleError(InstanceError):
    """Raised when an upgrade or recovery cannot proceed safely."""


class _SimulatedCrash(RuntimeError):
    """Test-only interruption that deliberately leaves the recovery journal."""


def _compact_json(value: Any) -> str:
    try:
        return json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError) as exc:
        raise LifecycleError(f"lifecycle value is not strict JSON: {exc}") from exc


def _sha256_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _document_id(prefix: str, value: dict[str, Any]) -> str:
    return prefix + hashlib.sha256(_compact_json(value).encode("utf-8")).hexdigest()[:32]


def _validate_document(value: dict[str, Any], schema_path: Path, label: str) -> None:
    schema = _load_json(schema_path)
    issues = validate_schema(value, schema)
    if issues:
        details = "; ".join(f"{issue.path}: {issue.message}" for issue in issues)
        raise LifecycleError(f"{label} violates schema: {details}")


def _safe_target(root: Path, relative: str, *, allow_lock: bool = False) -> Path:
    if not _is_safe_relative(relative):
        raise LifecycleError(f"unsafe lifecycle path: {relative}")
    if relative in RESERVED_ACTION_PATHS and not (allow_lock and relative == LOCK_RELATIVE):
        raise LifecycleError(f"lifecycle action targets reserved authority: {relative}")
    target = root / relative
    parent = target.parent.resolve()
    if parent != root and root not in parent.parents:
        raise LifecycleError(f"lifecycle path escapes the instance: {relative}")
    cursor = root
    for part in Path(relative).parts[:-1]:
        cursor = cursor / part
        if cursor.is_symlink():
            raise LifecycleError(f"lifecycle path traverses a symbolic link: {relative}")
    return target


def _validate_bundle_relative(relative: str) -> None:
    if not _is_safe_relative(relative):
        raise LifecycleError(f"unsafe recovery path: {relative}")
    if relative in RESERVED_ACTION_PATHS and relative != LOCK_RELATIVE:
        raise LifecycleError(f"recovery path targets reserved authority: {relative}")


def _require_instance_root(root: Path) -> Path:
    if root.is_symlink():
        raise LifecycleError("instance root must not be a symbolic link")
    instance_root = root.resolve()
    if not instance_root.is_dir():
        raise LifecycleError(f"instance root does not exist: {instance_root}")
    for relative in (INSTANCE_RELATIVE, LOCK_RELATIVE):
        authority = instance_root / relative
        if authority.is_symlink() or not authority.is_file():
            raise LifecycleError(f"instance authority is missing or unsafe: {relative}")
    return instance_root


def _read_regular(path: Path, *, label: str) -> tuple[bytes, int]:
    if path.is_symlink():
        raise LifecycleError(f"{label} must not be a symbolic link: {path}")
    try:
        metadata = path.stat()
    except FileNotFoundError as exc:
        raise LifecycleError(f"{label} does not exist: {path}") from exc
    if not stat.S_ISREG(metadata.st_mode):
        raise LifecycleError(f"{label} must be a regular file: {path}")
    if metadata.st_size > MAX_LIFECYCLE_FILE_BYTES:
        raise LifecycleError(f"{label} exceeds 10 MiB: {path}")
    return path.read_bytes(), stat.S_IMODE(metadata.st_mode)


def _state_digest(path: Path) -> str | None:
    if path.is_symlink():
        raise LifecycleError(f"lifecycle target must not be a symbolic link: {path}")
    if not path.exists():
        return None
    content, _ = _read_regular(path, label="lifecycle target")
    return _sha256_bytes(content)


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _fsync_tree_directories(root: Path) -> None:
    directories = [root, *(path for path in root.rglob("*") if path.is_dir())]
    for directory in sorted(directories, key=lambda item: len(item.parts), reverse=True):
        _fsync_directory(directory)


def _atomic_write_bytes(path: Path, content: bytes, mode: int = 0o644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, mode)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    finally:
        if temporary.exists():
            temporary.unlink()


def _atomic_write_json(path: Path, value: dict[str, Any], mode: int = 0o600) -> None:
    _atomic_write_bytes(path, _canonical_json(value).encode("utf-8"), mode)


def _write_new_json(path: Path, value: dict[str, Any]) -> None:
    destination = path.resolve()
    if destination.exists() or path.is_symlink():
        raise LifecycleError(f"output already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o644)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(_canonical_json(value))
            handle.flush()
            os.fsync(handle.fileno())
        if destination.exists():
            raise LifecycleError(f"output appeared during publication: {destination}")
        os.replace(temporary, destination)
        _fsync_directory(destination.parent)
    finally:
        if temporary.exists():
            temporary.unlink()


def _instance_authority(root: Path) -> tuple[Path, dict[str, Any], dict[str, Any], bytes]:
    if root.is_symlink():
        raise LifecycleError("instance root must not be a symbolic link")
    instance_root = root.resolve()
    findings = validate_instance_directory(instance_root)
    errors = [finding for finding in findings if finding.severity == "ERROR"]
    if errors:
        details = "; ".join(f"{finding.path}: {finding.message}" for finding in errors)
        raise LifecycleError(f"instance is not safe to upgrade: {details}")
    document = _load_json(instance_root / INSTANCE_RELATIVE)
    lock_path = instance_root / LOCK_RELATIVE
    lock = _load_json(lock_path)
    lock_bytes, _ = _read_regular(lock_path, label="instance lock")
    return instance_root, document, lock, lock_bytes


def _unique_lock_records(lock: dict[str, Any]) -> dict[str, dict[str, str]]:
    records: dict[str, dict[str, str]] = {}
    for record in lock["files"]:
        relative = str(record["path"])
        if relative in records:
            raise LifecycleError(f"instance lock contains duplicate path: {relative}")
        if not _is_safe_relative(relative) or relative in RESERVED_ACTION_PATHS:
            raise LifecycleError(f"instance lock contains unsafe managed path: {relative}")
        records[relative] = {
            "path": relative,
            "ownership": str(record["ownership"]),
            "sha256": str(record["sha256"]),
        }
    return records


def _target_upgrade(
    instance_root: Path,
    document: dict[str, Any],
    source_lock: dict[str, Any],
) -> tuple[dict[str, bytes], list[dict[str, Any]], list[str], dict[str, Any]]:
    old_records = _unique_lock_records(source_lock)
    target_files = _build_seed_files(document)
    target_contents: dict[str, bytes] = {}
    target_records: list[dict[str, str]] = []
    actions: list[dict[str, Any]] = []
    preserved_seeded: list[str] = []

    for relative, (content, ownership) in sorted(target_files.items()):
        if relative in RESERVED_ACTION_PATHS or not _is_safe_relative(relative):
            raise LifecycleError(f"Factory template targets unsafe path: {relative}")
        encoded = content.encode("utf-8")
        after_digest = _sha256_bytes(encoded)
        target = _safe_target(instance_root, relative)
        old = old_records.pop(relative, None)
        if old is not None and old["ownership"] != ownership:
            raise LifecycleError(f"file ownership transition requires an explicit migration: {relative}")

        if ownership == "seeded" and old is not None:
            target_records.append(old)
            preserved_seeded.append(relative)
            continue

        before_digest = _state_digest(target)
        if old is None and before_digest is not None:
            raise LifecycleError(f"new Factory file collides with an unowned path: {relative}")
        if old is not None and before_digest != old["sha256"]:
            raise LifecycleError(f"locked file changed after validation: {relative}")

        target_records.append(
            {"path": relative, "ownership": ownership, "sha256": after_digest}
        )
        target_contents[relative] = encoded
        if before_digest != after_digest:
            actions.append(
                {
                    "path": relative,
                    "ownership": ownership,
                    "action": "create" if before_digest is None else "replace",
                    "before_sha256": before_digest,
                    "after_sha256": after_digest,
                }
            )

    for relative, old in sorted(old_records.items()):
        if old["ownership"] == "seeded":
            target_records.append(old)
            preserved_seeded.append(relative)
            continue
        target = _safe_target(instance_root, relative)
        before_digest = _state_digest(target)
        if before_digest != old["sha256"]:
            raise LifecycleError(f"retired managed file changed after validation: {relative}")
        actions.append(
            {
                "path": relative,
                "ownership": "managed",
                "action": "remove",
                "before_sha256": before_digest,
                "after_sha256": None,
            }
        )

    target_lock = _build_lock_from_records(document, target_records)
    return target_contents, actions, sorted(preserved_seeded), target_lock


def plan_instance_upgrade(root: Path) -> dict[str, Any]:
    instance_root, document, source_lock, source_lock_bytes = _instance_authority(root)
    source_version = str(source_lock["factory"]["version"])
    target_version = str(_factory_metadata()["version"])
    if source_version == target_version:
        raise LifecycleError(f"instance is already at Factory {target_version}")
    try:
        if _parse_version(source_version) > _parse_version(target_version):
            raise LifecycleError("instance was created by a newer Factory")
    except ValueError as exc:
        raise LifecycleError("Factory version is not semantic") from exc
    if source_version not in SUPPORTED_UPGRADE_SOURCES:
        raise LifecycleError(
            f"no explicit migration path from {source_version} to {target_version}"
        )

    _, actions, preserved_seeded, target_lock = _target_upgrade(
        instance_root, document, source_lock
    )
    target_lock_bytes = _canonical_json(target_lock).encode("utf-8")
    body: dict[str, Any] = {
        "schema_version": "1.0.0",
        "instance_id": document["instance_id"],
        "instance_root": str(instance_root),
        "source": {
            "factory_version": source_version,
            "lock_digest": _sha256_bytes(source_lock_bytes),
            "instance_digest": source_lock["instance_digest"],
            "contract_digest": source_lock["factory"]["contract_digest"],
        },
        "target": {
            "factory_version": target_version,
            "source_revision": target_lock["factory"]["source_revision"],
            "source_dirty": target_lock["factory"]["source_dirty"],
            "contract_digest": target_lock["factory"]["contract_digest"],
            "lock_digest": _sha256_bytes(target_lock_bytes),
        },
        "actions": actions,
        "preserved_seeded_files": preserved_seeded,
        "runtime_must_be_quiescent": True,
    }
    plan = {**body, "plan_id": _document_id("upgrade-", body)}
    _validate_document(plan, UPGRADE_PLAN_SCHEMA, "instance upgrade plan")
    return plan


def write_instance_upgrade_plan(root: Path, output: Path) -> dict[str, Any]:
    if output.is_symlink():
        raise LifecycleError("upgrade plan output must not be a symbolic link")
    instance_root = root.resolve()
    destination = output.resolve()
    if destination == instance_root or instance_root in destination.parents:
        raise LifecycleError("upgrade plan must be written outside the instance")
    plan = plan_instance_upgrade(instance_root)
    _write_new_json(destination, plan)
    return plan


def _runtime_quiescence(instance_root: Path, document: dict[str, Any]) -> dict[str, Any]:
    state_path = _safe_target(instance_root, str(document["runtime"]["state_location"]))
    if not state_path.exists():
        return {"state": "ABSENT", "audit_head": None}
    if state_path.is_symlink() or not state_path.is_file():
        raise LifecycleError("runtime state must be a regular non-symlink file")
    try:
        with ControlPlane(state_path, create=False) as control:
            audit = control.verify_audit()
            status = control.status()
    except (OSError, RuntimeError, sqlite3.Error) as exc:
        raise LifecycleError(f"runtime state cannot be verified: {exc}") from exc
    if not status["paused"]:
        raise LifecycleError("runtime must be paused before lifecycle mutation")
    if int(status["active_leases"]) != 0:
        raise LifecycleError("runtime still has active task leases")
    outstanding = {
        state: count
        for state, count in status["outbox"].items()
        if state in {"PENDING", "FAILED", "CLAIMED"} and int(count) > 0
    }
    if outstanding:
        raise LifecycleError(f"runtime still has outstanding external effects: {outstanding}")
    return {"state": "QUIESCENT", "audit_head": audit["head"]}


def _bundle_file_path(bundle: Path, relative: str) -> Path:
    target = bundle / "files" / relative
    parent = target.parent.resolve()
    files_root = (bundle / "files").resolve()
    if parent != files_root and files_root not in parent.parents:
        raise LifecycleError(f"recovery path escapes bundle: {relative}")
    return target


def _create_recovery_bundle(
    instance_root: Path,
    output: Path,
    *,
    instance_id: str,
    plan_id: str,
    captured_factory_version: str,
    expected_factory_version: str,
    captured_lock_digest: str,
    expected_lock_digest: str,
    changes: list[dict[str, Any]],
) -> dict[str, Any]:
    destination = output.resolve()
    if destination == instance_root or instance_root in destination.parents:
        raise LifecycleError("recovery bundle must be outside the instance")
    if destination.exists() or output.is_symlink():
        raise LifecycleError(f"recovery output already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(
        tempfile.mkdtemp(prefix=f".{destination.name}.recovery-", dir=destination.parent)
    )
    os.chmod(stage, 0o700)
    try:
        records: list[dict[str, Any]] = []
        total_bytes = 0
        seen: set[str] = set()
        for change in changes:
            relative = str(change["path"])
            if relative in seen:
                raise LifecycleError(f"recovery change path is duplicated: {relative}")
            seen.add(relative)
            target = _safe_target(
                instance_root, relative, allow_lock=relative == LOCK_RELATIVE
            )
            before = _state_digest(target)
            expected_before = change["before_sha256"]
            if before != expected_before:
                raise LifecycleError(f"source changed before recovery capture: {relative}")
            if before is None:
                record = {
                    "path": relative,
                    "existed": False,
                    "sha256": None,
                    "mode": None,
                    "expected_after_sha256": change["after_sha256"],
                }
            else:
                content, mode = _read_regular(target, label="recovery source")
                total_bytes += len(content)
                if total_bytes > MAX_RECOVERY_BYTES:
                    raise LifecycleError("recovery bundle exceeds 50 MiB")
                backup = _bundle_file_path(stage, relative)
                _atomic_write_bytes(backup, content, 0o600)
                record = {
                    "path": relative,
                    "existed": True,
                    "sha256": before,
                    "mode": mode,
                    "expected_after_sha256": change["after_sha256"],
                }
            records.append(record)
        body: dict[str, Any] = {
            "schema_version": "1.0.0",
            "instance_id": instance_id,
            "plan_id": plan_id,
            "captured_factory_version": captured_factory_version,
            "expected_factory_version": expected_factory_version,
            "captured_lock_digest": captured_lock_digest,
            "expected_lock_digest": expected_lock_digest,
            "files": sorted(records, key=lambda record: record["path"]),
        }
        manifest = {**body, "bundle_id": _document_id("recovery-", body)}
        _validate_document(manifest, RECOVERY_MANIFEST_SCHEMA, "recovery manifest")
        _atomic_write_json(stage / "manifest.json", manifest)
        _fsync_tree_directories(stage)
        if destination.exists():
            raise LifecycleError(f"recovery output appeared during publication: {destination}")
        os.replace(stage, destination)
        _fsync_directory(destination.parent)
    except Exception:
        if stage.exists():
            shutil.rmtree(stage)
        raise
    inspect_recovery_bundle(destination)
    return manifest


def inspect_recovery_bundle(path: Path) -> dict[str, Any]:
    if path.is_symlink():
        raise LifecycleError("recovery bundle must not be a symbolic link")
    bundle = path.resolve()
    if not bundle.is_dir():
        raise LifecycleError(f"recovery bundle does not exist: {bundle}")
    if stat.S_IMODE(bundle.stat().st_mode) != 0o700:
        raise LifecycleError("recovery bundle directory permissions must be 0700")
    manifest_path = bundle / "manifest.json"
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise LifecycleError("recovery manifest must be a regular non-symlink file")
    if stat.S_IMODE(manifest_path.stat().st_mode) != 0o600:
        raise LifecycleError("recovery manifest permissions must be 0600")
    manifest = _load_json(manifest_path)
    _validate_document(manifest, RECOVERY_MANIFEST_SCHEMA, "recovery manifest")
    seen: set[str] = set()
    expected_files = {"manifest.json"}
    total_bytes = 0
    lock_records = 0
    for record in manifest["files"]:
        relative = str(record["path"])
        if relative in seen:
            raise LifecycleError(f"recovery manifest duplicates path: {relative}")
        seen.add(relative)
        _validate_bundle_relative(relative)
        if relative == LOCK_RELATIVE:
            lock_records += 1
        backup = _bundle_file_path(bundle, relative)
        backup_relative = backup.relative_to(bundle).as_posix()
        if record["existed"]:
            content, mode = _read_regular(backup, label="recovery file")
            total_bytes += len(content)
            if _sha256_bytes(content) != record["sha256"]:
                raise LifecycleError(f"recovery file digest differs: {relative}")
            if mode != 0o600:
                raise LifecycleError(f"recovery file permissions are not owner-only: {relative}")
            expected_files.add(backup_relative)
        elif backup.exists() or record["sha256"] is not None or record["mode"] is not None:
            raise LifecycleError(f"nonexistent recovery source has backup material: {relative}")
    if total_bytes > MAX_RECOVERY_BYTES:
        raise LifecycleError("recovery bundle exceeds 50 MiB")
    if lock_records != 1:
        raise LifecycleError("recovery bundle must contain exactly one instance lock")
    actual_files = {
        item.relative_to(bundle).as_posix()
        for item in bundle.rglob("*")
        if item.is_file() or item.is_symlink()
    }
    if actual_files != expected_files:
        raise LifecycleError("recovery bundle contains undeclared files")
    return manifest


def _load_plan(path: Path) -> dict[str, Any]:
    if path.is_symlink():
        raise LifecycleError("upgrade plan must not be a symbolic link")
    plan = _load_json(path.resolve())
    _validate_document(plan, UPGRADE_PLAN_SCHEMA, "instance upgrade plan")
    body = {key: value for key, value in plan.items() if key != "plan_id"}
    if plan["plan_id"] != _document_id("upgrade-", body):
        raise LifecycleError("upgrade plan identity does not match its content")
    return plan


def _prepare_stage(
    instance_root: Path,
    target_contents: dict[str, bytes],
    target_lock: dict[str, Any],
) -> Path:
    stage = Path(
        tempfile.mkdtemp(prefix=f".{instance_root.name}.upgrade-", dir=instance_root.parent)
    )
    os.chmod(stage, 0o700)
    try:
        for relative, content in target_contents.items():
            target = stage / "files" / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
            os.chmod(target, 0o600)
        _atomic_write_json(stage / "target-lock.json", target_lock)
    except Exception:
        shutil.rmtree(stage)
        raise
    return stage


def _journal_path(instance_root: Path) -> Path:
    return instance_root / JOURNAL_RELATIVE


def _write_journal(instance_root: Path, journal: dict[str, Any]) -> None:
    _validate_document(journal, LIFECYCLE_JOURNAL_SCHEMA, "lifecycle journal")
    _atomic_write_json(_journal_path(instance_root), journal)


def _create_journal(instance_root: Path, journal: dict[str, Any]) -> None:
    _validate_document(journal, LIFECYCLE_JOURNAL_SCHEMA, "lifecycle journal")
    target = _journal_path(instance_root)
    target.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(target, flags, 0o600)
    except FileExistsError as exc:
        raise LifecycleError("a lifecycle journal already exists; recover first") from exc
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(_canonical_json(journal))
            handle.flush()
            os.fsync(handle.fileno())
        _fsync_directory(target.parent)
    except Exception:
        if target.exists() and not target.is_symlink():
            target.unlink()
        raise


def _load_journal(instance_root: Path) -> dict[str, Any]:
    journal_path = _journal_path(instance_root)
    if journal_path.is_symlink():
        raise LifecycleError("lifecycle journal must not be a symbolic link")
    if not journal_path.is_file():
        raise LifecycleError("lifecycle journal must be a regular file")
    if stat.S_IMODE(journal_path.stat().st_mode) != 0o600:
        raise LifecycleError("lifecycle journal permissions must be 0600")
    journal = _load_json(journal_path)
    _validate_document(journal, LIFECYCLE_JOURNAL_SCHEMA, "lifecycle journal")
    operation = journal["operation"]
    plan_id = str(journal["plan_id"])
    stage_path = journal["stage_path"]
    if operation == "UPGRADE" and (
        not plan_id.startswith("upgrade-") or not isinstance(stage_path, str)
    ):
        raise LifecycleError("upgrade journal operation fields are inconsistent")
    if operation == "ROLLBACK" and (
        not plan_id.startswith("rollback-") or stage_path is not None
    ):
        raise LifecycleError("rollback journal operation fields are inconsistent")
    return journal


def _remove_journal(instance_root: Path) -> None:
    journal = _journal_path(instance_root)
    if journal.exists():
        if journal.is_symlink() or not journal.is_file():
            raise LifecycleError("upgrade journal is not a regular file")
        journal.unlink()
        _fsync_directory(journal.parent)


def _cleanup_stage(instance_root: Path, stage: Path) -> None:
    resolved = stage.resolve()
    if (
        resolved.parent != instance_root.parent
        or not resolved.name.startswith(f".{instance_root.name}.upgrade-")
    ):
        raise LifecycleError("refusing to clean an untrusted lifecycle stage")
    if resolved.exists():
        shutil.rmtree(resolved)


@contextmanager
def _lifecycle_lock(instance_root: Path):
    if fcntl is None:
        raise LifecycleError("lifecycle locking requires POSIX fcntl support")
    guard = _safe_target(instance_root, "runtime/.factory-lifecycle.guard")
    guard.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(guard, flags, 0o600)
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise LifecycleError("lifecycle guard must be a regular file")
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise LifecycleError("another lifecycle operation is already running") from exc
        yield
    finally:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)


def _restore_bundle(
    instance_root: Path,
    bundle_path: Path,
    *,
    allow_interrupted: bool,
    progress: Callable[[int], None] | None = None,
) -> dict[str, Any]:
    manifest = inspect_recovery_bundle(bundle_path)
    document = _load_json(instance_root / INSTANCE_RELATIVE)
    if document["instance_id"] != manifest["instance_id"]:
        raise LifecycleError("recovery bundle belongs to another instance")
    lock_path = _safe_target(instance_root, LOCK_RELATIVE, allow_lock=True)
    current_lock_digest = _state_digest(lock_path)
    allowed_locks = {manifest["expected_lock_digest"]}
    if allow_interrupted:
        allowed_locks.add(manifest["captured_lock_digest"])
    if current_lock_digest not in allowed_locks:
        raise LifecycleError("current instance lock does not match the recovery transition")

    lock_record: dict[str, Any] | None = None
    for record in manifest["files"]:
        relative = str(record["path"])
        if relative == LOCK_RELATIVE:
            lock_record = record
            continue
        target = _safe_target(instance_root, relative)
        current = _state_digest(target)
        allowed_states = {record["expected_after_sha256"]}
        if allow_interrupted:
            allowed_states.add(record["sha256"] if record["existed"] else None)
        if current not in allowed_states:
            raise LifecycleError(f"refusing to overwrite post-transition drift: {relative}")

    actions_completed = 0
    for record in manifest["files"]:
        relative = str(record["path"])
        if relative == LOCK_RELATIVE:
            continue
        target = _safe_target(instance_root, relative)
        if record["existed"]:
            content, _ = _read_regular(
                _bundle_file_path(bundle_path.resolve(), relative), label="recovery file"
            )
            _atomic_write_bytes(target, content, int(record["mode"]))
        elif target.exists():
            if target.is_symlink() or not target.is_file():
                raise LifecycleError(f"recovery removal target is unsafe: {relative}")
            target.unlink()
            _fsync_directory(target.parent)
        actions_completed += 1
        if progress is not None:
            progress(actions_completed)

    if lock_record is None or not lock_record["existed"]:
        raise LifecycleError("recovery bundle does not contain a captured lock")
    lock_content, _ = _read_regular(
        _bundle_file_path(bundle_path.resolve(), LOCK_RELATIVE), label="recovery lock"
    )
    if _sha256_bytes(lock_content) != manifest["captured_lock_digest"]:
        raise LifecycleError("captured recovery lock digest differs from manifest")
    _atomic_write_bytes(lock_path, lock_content, int(lock_record["mode"]))
    findings = validate_instance_directory(instance_root)
    errors = [finding for finding in findings if finding.severity == "ERROR"]
    if errors:
        details = "; ".join(f"{finding.path}: {finding.message}" for finding in errors)
        raise LifecycleError(f"restored instance failed validation: {details}")
    return manifest


def apply_instance_upgrade(
    root: Path,
    plan_path: Path,
    recovery_output: Path,
    *,
    _allow_dirty_factory: bool = False,
    _simulate_crash_after_actions: int | None = None,
    _fail_after_actions: int | None = None,
) -> dict[str, Any]:
    instance_root = _require_instance_root(root)
    _instance_authority(instance_root)
    with _lifecycle_lock(instance_root):
        return _apply_instance_upgrade_locked(
            instance_root,
            plan_path,
            recovery_output,
            _allow_dirty_factory=_allow_dirty_factory,
            _simulate_crash_after_actions=_simulate_crash_after_actions,
            _fail_after_actions=_fail_after_actions,
        )


def _apply_instance_upgrade_locked(
    root: Path,
    plan_path: Path,
    recovery_output: Path,
    *,
    _allow_dirty_factory: bool = False,
    _simulate_crash_after_actions: int | None = None,
    _fail_after_actions: int | None = None,
) -> dict[str, Any]:
    instance_root, document, source_lock, source_lock_bytes = _instance_authority(root)
    if _journal_path(instance_root).exists() or _journal_path(instance_root).is_symlink():
        raise LifecycleError("an interrupted lifecycle journal already exists; recover first")
    supplied_plan = _load_plan(plan_path)
    current_plan = plan_instance_upgrade(instance_root)
    if supplied_plan != current_plan:
        raise LifecycleError("upgrade plan is stale or belongs to another Factory/instance")
    if current_plan["instance_root"] != str(instance_root):
        raise LifecycleError("upgrade plan is bound to another instance path")
    if current_plan["target"]["source_dirty"] and not _allow_dirty_factory:
        raise LifecycleError("refusing to upgrade from a dirty Factory source")
    if not _allow_dirty_factory and not current_source_release_verified():
        raise LifecycleError("refusing to upgrade from an unverified Factory release")
    runtime = _runtime_quiescence(instance_root, document)
    target_contents, actions, _, target_lock = _target_upgrade(
        instance_root, document, source_lock
    )
    target_lock_bytes = _canonical_json(target_lock).encode("utf-8")
    if _sha256_bytes(source_lock_bytes) != current_plan["source"]["lock_digest"]:
        raise LifecycleError("instance lock changed after planning")
    if _sha256_bytes(target_lock_bytes) != current_plan["target"]["lock_digest"]:
        raise LifecycleError("target lock changed after planning")

    stage = _prepare_stage(instance_root, target_contents, target_lock)
    recovery_changes = list(actions) + [
        {
            "path": LOCK_RELATIVE,
            "before_sha256": current_plan["source"]["lock_digest"],
            "after_sha256": current_plan["target"]["lock_digest"],
        }
    ]
    try:
        recovery = _create_recovery_bundle(
            instance_root,
            recovery_output,
            instance_id=str(document["instance_id"]),
            plan_id=str(current_plan["plan_id"]),
            captured_factory_version=str(current_plan["source"]["factory_version"]),
            expected_factory_version=str(current_plan["target"]["factory_version"]),
            captured_lock_digest=str(current_plan["source"]["lock_digest"]),
            expected_lock_digest=str(current_plan["target"]["lock_digest"]),
            changes=recovery_changes,
        )
    except Exception:
        _cleanup_stage(instance_root, stage)
        raise
    journal = {
        "schema_version": "1.0.0",
        "operation": "UPGRADE",
        "plan_id": current_plan["plan_id"],
        "instance_id": document["instance_id"],
        "recovery_path": str(recovery_output.resolve()),
        "stage_path": str(stage),
        "source_lock_digest": current_plan["source"]["lock_digest"],
        "target_lock_digest": current_plan["target"]["lock_digest"],
        "phase": "PREPARED",
        "actions_completed": 0,
    }
    try:
        _create_journal(instance_root, journal)
    except Exception:
        _cleanup_stage(instance_root, stage)
        raise
    try:
        journal["phase"] = "APPLYING"
        _write_journal(instance_root, journal)
        for index, action in enumerate(actions, start=1):
            relative = str(action["path"])
            target = _safe_target(instance_root, relative)
            if _state_digest(target) != action["before_sha256"]:
                raise LifecycleError(f"upgrade source changed during apply: {relative}")
            if action["action"] in {"create", "replace"}:
                staged = stage / "files" / relative
                content, _ = _read_regular(staged, label="staged upgrade file")
                if _sha256_bytes(content) != action["after_sha256"]:
                    raise LifecycleError(f"staged upgrade digest differs: {relative}")
                _atomic_write_bytes(target, content)
            else:
                if target.is_symlink() or not target.is_file():
                    raise LifecycleError(f"upgrade removal target is unsafe: {relative}")
                target.unlink()
                _fsync_directory(target.parent)
            journal["actions_completed"] = index
            _write_journal(instance_root, journal)
            if _simulate_crash_after_actions == index:
                raise _SimulatedCrash("simulated process loss")
            if _fail_after_actions == index:
                raise LifecycleError("injected upgrade failure")

        staged_lock, _ = _read_regular(stage / "target-lock.json", label="staged target lock")
        if _sha256_bytes(staged_lock) != current_plan["target"]["lock_digest"]:
            raise LifecycleError("staged target lock digest differs")
        _atomic_write_bytes(instance_root / LOCK_RELATIVE, staged_lock)
        journal["phase"] = "COMMITTED"
        _write_journal(instance_root, journal)
        findings = validate_instance_directory(instance_root)
        errors = [finding for finding in findings if finding.severity == "ERROR"]
        if errors:
            details = "; ".join(f"{finding.path}: {finding.message}" for finding in errors)
            raise LifecycleError(f"upgraded instance failed validation: {details}")
        journal["phase"] = "VERIFIED"
        _write_journal(instance_root, journal)
    except _SimulatedCrash:
        raise
    except Exception as exc:
        try:
            _restore_bundle(instance_root, recovery_output.resolve(), allow_interrupted=True)
            _remove_journal(instance_root)
            _cleanup_stage(instance_root, stage)
        except Exception as rollback_exc:
            raise LifecycleError(
                f"upgrade failed and automatic rollback also failed; use lifecycle recover: {rollback_exc}"
            ) from exc
        raise LifecycleError(f"upgrade failed and was rolled back: {exc}") from exc

    _remove_journal(instance_root)
    _cleanup_stage(instance_root, stage)
    return {
        "status": "UPGRADED",
        "plan_id": current_plan["plan_id"],
        "recovery_bundle": str(recovery_output.resolve()),
        "recovery_bundle_id": recovery["bundle_id"],
        "runtime": runtime,
        "instance": instance_summary(instance_root),
    }


def _rollback_plan_id(manifest: dict[str, Any]) -> str:
    value = {
        "bundle_id": manifest["bundle_id"],
        "captured_lock_digest": manifest["captured_lock_digest"],
        "expected_lock_digest": manifest["expected_lock_digest"],
    }
    return _document_id("rollback-", value)


def rollback_instance(
    root: Path,
    recovery_path: Path,
    rescue_output: Path,
    *,
    _simulate_crash_after_actions: int | None = None,
    _fail_after_actions: int | None = None,
) -> dict[str, Any]:
    instance_root = _require_instance_root(root)
    _instance_authority(instance_root)
    with _lifecycle_lock(instance_root):
        return _rollback_instance_locked(
            instance_root,
            recovery_path,
            rescue_output,
            _simulate_crash_after_actions=_simulate_crash_after_actions,
            _fail_after_actions=_fail_after_actions,
        )


def _rollback_instance_locked(
    root: Path,
    recovery_path: Path,
    rescue_output: Path,
    *,
    _simulate_crash_after_actions: int | None = None,
    _fail_after_actions: int | None = None,
) -> dict[str, Any]:
    instance_root, document, _, current_lock_bytes = _instance_authority(root)
    if _journal_path(instance_root).exists() or _journal_path(instance_root).is_symlink():
        raise LifecycleError("an interrupted lifecycle journal exists; use lifecycle recover")
    runtime = _runtime_quiescence(instance_root, document)
    recovery = inspect_recovery_bundle(recovery_path)
    current_lock_digest = _sha256_bytes(current_lock_bytes)
    if current_lock_digest != recovery["expected_lock_digest"]:
        raise LifecycleError("current instance is not the expected rollback source")

    rescue_changes: list[dict[str, Any]] = []
    for record in recovery["files"]:
        relative = str(record["path"])
        target = _safe_target(
            instance_root, relative, allow_lock=relative == LOCK_RELATIVE
        )
        current = _state_digest(target)
        if current != record["expected_after_sha256"]:
            raise LifecycleError(f"current lifecycle file drifted before rollback: {relative}")
        rescue_changes.append(
            {
                "path": relative,
                "before_sha256": current,
                "after_sha256": record["sha256"] if record["existed"] else None,
            }
        )
    rescue_plan_id = _rollback_plan_id(recovery)
    rescue = _create_recovery_bundle(
        instance_root,
        rescue_output,
        instance_id=str(document["instance_id"]),
        plan_id=rescue_plan_id,
        captured_factory_version=str(recovery["expected_factory_version"]),
        expected_factory_version=str(recovery["captured_factory_version"]),
        captured_lock_digest=current_lock_digest,
        expected_lock_digest=str(recovery["captured_lock_digest"]),
        changes=rescue_changes,
    )
    journal = {
        "schema_version": "1.0.0",
        "operation": "ROLLBACK",
        "plan_id": rescue_plan_id,
        "instance_id": document["instance_id"],
        "recovery_path": str(rescue_output.resolve()),
        "stage_path": None,
        "source_lock_digest": current_lock_digest,
        "target_lock_digest": recovery["captured_lock_digest"],
        "phase": "PREPARED",
        "actions_completed": 0,
    }
    _create_journal(instance_root, journal)

    def progress(actions_completed: int) -> None:
        journal["actions_completed"] = actions_completed
        _write_journal(instance_root, journal)
        if _simulate_crash_after_actions == actions_completed:
            raise _SimulatedCrash("simulated process loss")
        if _fail_after_actions == actions_completed:
            raise LifecycleError("injected rollback failure")

    try:
        journal["phase"] = "APPLYING"
        _write_journal(instance_root, journal)
        _restore_bundle(
            instance_root,
            recovery_path.resolve(),
            allow_interrupted=False,
            progress=progress,
        )
        journal["phase"] = "COMMITTED"
        _write_journal(instance_root, journal)
        journal["phase"] = "VERIFIED"
        _write_journal(instance_root, journal)
    except _SimulatedCrash:
        raise
    except Exception as exc:
        try:
            _restore_bundle(instance_root, rescue_output.resolve(), allow_interrupted=True)
            _remove_journal(instance_root)
        except Exception as rescue_exc:
            raise LifecycleError(
                f"rollback failed and rescue restore also failed: {rescue_exc}"
            ) from exc
        raise LifecycleError(f"rollback failed and current release was rescued: {exc}") from exc
    _remove_journal(instance_root)
    return {
        "status": "ROLLED_BACK",
        "recovery_bundle": str(recovery_path.resolve()),
        "rescue_bundle": str(rescue_output.resolve()),
        "rescue_bundle_id": rescue["bundle_id"],
        "runtime": runtime,
        "instance": instance_summary(instance_root),
    }


def recover_interrupted_lifecycle(root: Path) -> dict[str, Any]:
    instance_root = _require_instance_root(root)
    with _lifecycle_lock(instance_root):
        return _recover_interrupted_lifecycle_locked(instance_root)


def _recover_interrupted_lifecycle_locked(root: Path) -> dict[str, Any]:
    instance_root = root.resolve()
    journal = _load_journal(instance_root)
    document = _load_json(instance_root / INSTANCE_RELATIVE)
    if journal["instance_id"] != document["instance_id"]:
        raise LifecycleError("lifecycle journal belongs to another instance")
    runtime = _runtime_quiescence(instance_root, document)
    recovery_path = Path(str(journal["recovery_path"]))
    recovery = inspect_recovery_bundle(recovery_path)
    if (
        recovery["plan_id"] != journal["plan_id"]
        or recovery["captured_lock_digest"] != journal["source_lock_digest"]
        or recovery["expected_lock_digest"] != journal["target_lock_digest"]
    ):
        raise LifecycleError("lifecycle journal and recovery bundle do not match")
    _restore_bundle(instance_root, recovery_path, allow_interrupted=True)
    operation = str(journal["operation"])
    if operation == "UPGRADE":
        stage = Path(str(journal["stage_path"]))
        _cleanup_stage(instance_root, stage)
    _remove_journal(instance_root)
    return {
        "status": (
            "RECOVERED_TO_SOURCE"
            if operation == "UPGRADE"
            else "RECOVERED_TO_PRE_ROLLBACK"
        ),
        "operation": operation,
        "plan_id": journal["plan_id"],
        "recovery_bundle": str(recovery_path),
        "runtime": runtime,
        "instance": instance_summary(instance_root),
    }
