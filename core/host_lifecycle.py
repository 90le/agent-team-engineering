"""Plan and apply non-overwriting, reversible host-native team file projections."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import tempfile
import unicodedata
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any

try:
    import fcntl
except ImportError:  # pragma: no cover - exercised on non-POSIX hosts
    fcntl = None  # type: ignore[assignment]

from core.context_team import ContextTeamError, DESIGN_RELATIVE, LOCK_RELATIVE, inspect_context_team
from core.json_support import loads_strict
from core.schema_validation import validate_schema
from core.security import find_inline_secret

ROOT = Path(__file__).resolve().parents[1]
PLAN_SCHEMA = ROOT / "schemas" / "host-install-plan.schema.json"
LOCK_SCHEMA = ROOT / "schemas" / "host-install-lock.schema.json"
LEGACY_LOCK_SCHEMA = ROOT / "schemas" / "host-install-lock-legacy-v1.schema.json"
TOMBSTONE_SCHEMA = ROOT / "schemas" / "host-uninstall-tombstone.schema.json"
INSTALL_LOCK_RELATIVE = ".agent-team/host-install.lock.json"
OPERATION_GUARD_RELATIVE = ".agent-team/.host-lifecycle.guard"
UNINSTALL_TOMBSTONE_RELATIVE = ".agent-team/host-uninstall.tombstone.json"
METADATA_STAGE_RELATIVE = ".agent-team/.host-lifecycle.json.stage"
APPLY_INTENT_PREFIX = ".agent-team/.host-apply.intent-"
RESERVED_DESTINATIONS = frozenset(
    {
        INSTALL_LOCK_RELATIVE,
        OPERATION_GUARD_RELATIVE,
        UNINSTALL_TOMBSTONE_RELATIVE,
        METADATA_STAGE_RELATIVE,
    }
)
CONFIRMATION_STATEMENT = "I approve this exact host installation proposal."
SHARED_CONTEXT = (
    "GETTING-STARTED.md",
    "AI-START.md",
    "TEAM.md",
    "CONSTITUTION.md",
    "CONTEXT-MAP.md",
    "PROJECT-CONTEXT.md",
    "ARCHITECTURE.md",
    "ROLES",
    "WORKFLOWS",
    "SKILLS",
    "DECISIONS",
    "KNOWLEDGE",
    "WORK",
)
RootHandle = Path | int


class HostLifecycleError(ValueError):
    """Raised when a host installation lifecycle operation is unsafe or invalid."""


def _guard_content(destination: Path) -> bytes:
    del destination
    return b""


def _lifecycle_contract(destination: Path | None = None) -> dict[str, Any]:
    contract = {
        "operation_guard": OPERATION_GUARD_RELATIVE,
        "operation_guard_format": "empty-regular-file-v1",
        "unbound_empty_guard_reuse": True,
        "install_record": INSTALL_LOCK_RELATIVE,
        "uninstall_tombstone": UNINSTALL_TOMBSTONE_RELATIVE,
        "metadata_recovery_stage": METADATA_STAGE_RELATIVE,
        "metadata_recovery_stage_retained": False,
        "metadata_recovery_intent_prefix": ".agent-team/.host-metadata.intent-",
        "metadata_recovery_intent_retained": False,
        "initial_apply_intent_prefix": APPLY_INTENT_PREFIX,
        "initial_apply_intent_format": "plan-bound-random-empty-regular-file-v1",
        "initial_apply_intent_retained": False,
        "locking": "posix-fcntl-exclusive-nonblocking",
        "retained_files_after_uninstall": [
            OPERATION_GUARD_RELATIVE,
            UNINSTALL_TOMBSTONE_RELATIVE,
        ],
        "directories_removed": False,
    }
    if destination is not None:
        contract["operation_guard_content_sha256"] = _sha256_bytes(
            _guard_content(destination)
        )
    return contract


def _proposal_lifecycle_contract(
    *,
    destination: Path,
    prior_guard: dict[str, Any] | None,
    prior_tombstone: dict[str, Any] | None,
    metadata_intent: str | None = None,
) -> dict[str, Any]:
    return {
        **_lifecycle_contract(destination),
        "expected_prior_metadata_recovery_stage": None,
        "metadata_recovery_intent": metadata_intent,
        "expected_prior_guard": prior_guard,
        "expected_prior_uninstall_tombstone": prior_tombstone,
        "remove_prior_uninstall_tombstone": prior_tombstone is not None,
    }


def _canonical(value: Any) -> str:
    try:
        return json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ) + "\n"
    except (TypeError, ValueError) as exc:
        raise HostLifecycleError(f"host lifecycle value is not strict JSON: {exc}") from exc


def _compact(value: Any) -> str:
    try:
        return json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError) as exc:
        raise HostLifecycleError(f"host lifecycle value is not strict JSON: {exc}") from exc


def _sha256_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _digest(value: Any) -> str:
    return _sha256_bytes(_compact(value).encode("utf-8"))


def _nonblocking_read_flags() -> int:
    """Open an existing entry without following links or blocking on a FIFO."""

    return (
        os.O_RDONLY
        | getattr(os, "O_NONBLOCK", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0)
    )


def _load_object(path: Path, label: str) -> dict[str, Any]:
    if path.is_symlink():
        raise HostLifecycleError(f"{label} must not be a symbolic link: {path}")
    try:
        descriptor = os.open(path, _nonblocking_read_flags())
    except OSError as exc:
        raise HostLifecycleError(f"cannot read {label} {path}: {exc}") from exc
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise HostLifecycleError(f"{label} must be a regular file: {path}")
        content = _read_descriptor_bytes(descriptor)
    except HostLifecycleError:
        raise
    except OSError as exc:
        raise HostLifecycleError(f"cannot read {label} {path}: {exc}") from exc
    finally:
        os.close(descriptor)
    try:
        value = loads_strict(content.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise HostLifecycleError(f"cannot read {label} {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise HostLifecycleError(f"{label} root must be an object: {path}")
    return value


def _load_schema(path: Path) -> dict[str, Any]:
    value = loads_strict(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise HostLifecycleError(f"schema root must be an object: {path}")
    return value


def _safe_relative(value: str) -> bool:
    path = Path(value)
    return (
        bool(value)
        and value != "."
        and bool(path.parts)
        and _display_safe_path(value)
        and not path.is_absolute()
        and ".." not in path.parts
        and value == path.as_posix()
    )


def _display_safe_path(value: str) -> bool:
    """Reject path text that can forge the human-readable approval preview."""

    if not value or "`" in value:
        return False
    return all(
        unicodedata.category(character)[0] != "C"
        and unicodedata.category(character) not in {"Zl", "Zp"}
        for character in value
    )


def _unalias_path(path: Path, *, label: str, must_exist: bool) -> Path:
    """Return an absolute path only when no existing component is a symlink."""

    target = Path(os.path.abspath(os.fspath(path)))
    if path.is_symlink():
        raise HostLifecycleError(f"{label} must not be a symbolic link")
    try:
        resolved = target.resolve(strict=must_exist)
    except (OSError, RuntimeError) as exc:
        raise HostLifecycleError(f"cannot resolve {label} {target}: {exc}") from exc
    if resolved != target:
        raise HostLifecycleError(f"{label} must not traverse a symbolic link")
    return target


def _expected_confirmation_scope(proposal: dict[str, Any]) -> str:
    return (
        "replace-exact-prior-tombstone-and-manage-declared-host-lifecycle-and-scratch-files"
        if proposal["lifecycle"]["remove_prior_uninstall_tombstone"]
        else "manage-declared-host-lifecycle-and-scratch-files"
    )


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


@contextmanager
def _parent_directory_fd(root: RootHandle, relative: str, *, create: bool):
    """Open a relative path's parent without following directory symlinks."""

    if not _safe_relative(relative):
        raise HostLifecycleError(f"unsafe relative host lifecycle path: {relative}")
    components = Path(relative).parts
    flags = (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0)
    )
    try:
        current = os.dup(root) if isinstance(root, int) else os.open(root, flags)
    except OSError as exc:
        raise HostLifecycleError(f"cannot open host lifecycle root {root}: {exc}") from exc
    try:
        for component in components[:-1]:
            if create:
                try:
                    os.mkdir(component, 0o755, dir_fd=current)
                    os.fsync(current)
                except FileExistsError:
                    pass
            try:
                following = os.open(component, flags, dir_fd=current)
            except FileNotFoundError:
                raise
            except OSError as exc:
                raise HostLifecycleError(
                    f"host lifecycle path has an unsafe directory component: {relative}: {exc}"
                ) from exc
            os.close(current)
            current = following
        yield current, components[-1]
    finally:
        os.close(current)


def _read_descriptor_bytes(descriptor: int) -> bytes:
    chunks: list[bytes] = []
    while True:
        chunk = os.read(descriptor, 1024 * 1024)
        if not chunk:
            return b"".join(chunks)
        chunks.append(chunk)


def _read_regular_relative(
    root: RootHandle,
    relative: str,
    *,
    label: str,
) -> tuple[bytes, os.stat_result]:
    """Read one regular file through no-follow directory descriptors."""

    try:
        with _parent_directory_fd(root, relative, create=False) as (parent, name):
            descriptor = os.open(name, _nonblocking_read_flags(), dir_fd=parent)
            try:
                metadata = os.fstat(descriptor)
                if not stat.S_ISREG(metadata.st_mode):
                    raise HostLifecycleError(f"{label} is not a regular file: {relative}")
                content = _read_descriptor_bytes(descriptor)
            finally:
                os.close(descriptor)
    except HostLifecycleError:
        raise
    except OSError as exc:
        raise HostLifecycleError(f"cannot read {label} {relative}: {exc}") from exc
    return content, metadata


def _relative_stat(root: RootHandle, relative: str) -> os.stat_result | None:
    try:
        with _parent_directory_fd(root, relative, create=False) as (parent, name):
            try:
                return os.stat(name, dir_fd=parent, follow_symlinks=False)
            except FileNotFoundError:
                return None
    except FileNotFoundError:
        return None
    except HostLifecycleError:
        raise
    except OSError as exc:
        raise HostLifecycleError(
            f"cannot inspect host lifecycle path {relative}: {exc}"
        ) from exc


def _relative_present(root: RootHandle, relative: str) -> bool:
    return _relative_stat(root, relative) is not None


def _load_relative_object(
    root: RootHandle,
    relative: str,
    label: str,
) -> tuple[dict[str, Any], bytes, os.stat_result]:
    content, metadata = _read_regular_relative(root, relative, label=label)
    try:
        value = loads_strict(content.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise HostLifecycleError(f"cannot parse {label} {relative}: {exc}") from exc
    if not isinstance(value, dict):
        raise HostLifecycleError(f"{label} root must be an object: {relative}")
    return value, content, metadata


def _read_bound_relative(
    root: RootHandle,
    relative: str,
    expected_digest: str,
    *,
    label: str,
) -> tuple[bytes, os.stat_result]:
    """Read one regular file and bind its exact bytes to an expected digest."""

    content, metadata = _read_regular_relative(root, relative, label=label)
    if _sha256_bytes(content) != expected_digest:
        raise HostLifecycleError(f"{label} changed: {relative}")
    return content, metadata


def _file_binding(content: bytes, metadata: os.stat_result) -> dict[str, Any]:
    return {
        "sha256": _sha256_bytes(content),
        "size": len(content),
        "device": metadata.st_dev,
        "inode": metadata.st_ino,
    }


def _metadata_matches_binding(
    metadata: os.stat_result,
    binding: dict[str, Any],
) -> bool:
    """Match only the inode identity; content is checked before owned unlink."""

    return (metadata.st_dev, metadata.st_ino) == (
        binding["device"],
        binding["inode"],
    )


def _directory_binding(path: Path) -> dict[str, int]:
    flags = (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0)
    )
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise HostLifecycleError(f"cannot bind host lifecycle root {path}: {exc}") from exc
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISDIR(metadata.st_mode):
            raise HostLifecycleError(f"host lifecycle root is not a directory: {path}")
        return {"device": metadata.st_dev, "inode": metadata.st_ino}
    finally:
        os.close(descriptor)


def _assert_directory_binding(path: Path, expected: dict[str, int]) -> None:
    if _directory_binding(path) != expected:
        raise HostLifecycleError(
            "host lifecycle destination directory changed during the operation"
        )


def _guard_binding(
    destination: Path,
    root: RootHandle | None = None,
) -> dict[str, Any] | None:
    storage_root: RootHandle = destination if root is None else root
    if not _relative_present(storage_root, OPERATION_GUARD_RELATIVE):
        return None
    content, metadata = _read_regular_relative(
        storage_root,
        OPERATION_GUARD_RELATIVE,
        label="host lifecycle guard",
    )
    if content != _guard_content(destination):
        raise HostLifecycleError("host lifecycle guard content is invalid")
    return _file_binding(content, metadata)


@contextmanager
def _operation_lock(destination: Path, *, create: bool):
    """Serialize cooperating host lifecycle processes with a persistent kernel guard."""

    if fcntl is None:
        raise HostLifecycleError("host lifecycle locking requires POSIX fcntl support")
    root_flags = (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0)
    )
    try:
        root_descriptor = os.open(destination, root_flags)
    except OSError as exc:
        raise HostLifecycleError(
            f"cannot open host lifecycle destination {destination}: {exc}"
        ) from exc
    root_metadata = os.fstat(root_descriptor)
    root_binding = {"device": root_metadata.st_dev, "inode": root_metadata.st_ino}
    try:
        with _parent_directory_fd(
            root_descriptor, OPERATION_GUARD_RELATIVE, create=create
        ) as (parent, name):
            flags = (
                os.O_RDWR
                | getattr(os, "O_NONBLOCK", 0)
                | getattr(os, "O_NOFOLLOW", 0)
                | getattr(os, "O_CLOEXEC", 0)
            )
            created = False
            descriptor: int | None = None
            try:
                if create:
                    try:
                        descriptor = os.open(
                            name,
                            flags | os.O_CREAT | os.O_EXCL,
                            0o600,
                            dir_fd=parent,
                        )
                        created = True
                        os.fsync(descriptor)
                        os.fsync(parent)
                    except FileExistsError:
                        descriptor = os.open(name, flags, 0o600, dir_fd=parent)
                else:
                    descriptor = os.open(name, flags, 0o600, dir_fd=parent)
            except OSError as exc:
                if descriptor is not None:
                    os.close(descriptor)
                raise HostLifecycleError(f"cannot acquire host lifecycle guard: {exc}") from exc
            if descriptor is None:  # defensive: every successful branch opens the guard
                raise HostLifecycleError("cannot acquire host lifecycle guard")
            try:
                metadata = os.fstat(descriptor)
                if not stat.S_ISREG(metadata.st_mode):
                    raise HostLifecycleError("host lifecycle guard must be a regular file")
                expected_content = _guard_content(destination)
                try:
                    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError as exc:
                    raise HostLifecycleError(
                        "another host lifecycle operation is already running"
                    ) from exc
                os.lseek(descriptor, 0, os.SEEK_SET)
                content = _read_descriptor_bytes(descriptor)
                if content != expected_content:
                    raise HostLifecycleError("host lifecycle guard content is invalid")
                _assert_directory_binding(destination, root_binding)
                yield {
                    "created": created,
                    "guard_binding": _file_binding(content, metadata),
                    "root_binding": root_binding,
                    "root_fd": root_descriptor,
                }
            finally:
                try:
                    fcntl.flock(descriptor, fcntl.LOCK_UN)
                finally:
                    os.close(descriptor)
    finally:
        os.close(root_descriptor)


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o644)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(_canonical(value))
            handle.flush()
            os.fsync(handle.fileno())
        if path.is_symlink():
            raise HostLifecycleError(f"refusing symbolic-link JSON target: {path}")
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    except Exception:
        if temporary.exists():
            temporary.unlink()
        raise


def _atomic_json_relative(
    root: RootHandle,
    relative: str,
    value: dict[str, Any],
    *,
    expected_current_digest: str | None,
    intent_relative: str,
    allow_existing_intent: bool,
) -> None:
    """Publish JSON through a plan-bound hard-link intent and one bound root."""

    content = _canonical(value).encode("utf-8")
    desired_digest = _sha256_bytes(content)
    with _parent_directory_fd(root, relative, create=True) as (parent, name):
        stage_path = Path(METADATA_STAGE_RELATIVE)
        if Path(relative).parent != stage_path.parent:
            raise HostLifecycleError(
                "host lifecycle JSON target must share the declared recovery-stage directory"
            )
        stage_name = stage_path.name
        intent_path = Path(intent_relative)
        if (
            intent_path.parent != stage_path.parent
            or not intent_relative.startswith(".agent-team/.host-metadata.intent-")
        ):
            raise HostLifecycleError(
                "host lifecycle JSON intent differs from the exact plan"
            )
        intent_name = intent_path.name

        def read_name(candidate: str, label: str) -> tuple[bytes, os.stat_result] | None:
            try:
                descriptor = os.open(
                    candidate,
                    _nonblocking_read_flags(),
                    dir_fd=parent,
                )
            except FileNotFoundError:
                return None
            except OSError as exc:
                raise HostLifecycleError(f"cannot open {label}: {exc}") from exc
            try:
                metadata = os.fstat(descriptor)
                if not stat.S_ISREG(metadata.st_mode):
                    raise HostLifecycleError(f"{label} must be a regular file")
                return _read_descriptor_bytes(descriptor), metadata
            finally:
                os.close(descriptor)

        current = read_name(name, f"host lifecycle JSON {relative}")
        stage = read_name(stage_name, f"host lifecycle JSON recovery stage for {relative}")
        intent = read_name(intent_name, f"host lifecycle JSON intent for {relative}")
        intent_preexisting = intent is not None
        if not allow_existing_intent and (intent is not None or stage is not None):
            raise HostLifecycleError(
                f"host lifecycle JSON scratch appeared after planning: {relative}"
            )
        if current is not None and _sha256_bytes(current[0]) == desired_digest:
            if stage is not None:
                raise HostLifecycleError(
                    f"host lifecycle JSON recovery stage is not operation-bound: {relative}"
                )
            if intent is not None:
                if (intent[1].st_dev, intent[1].st_ino) != (
                    current[1].st_dev,
                    current[1].st_ino,
                ):
                    raise HostLifecycleError(
                        f"host lifecycle JSON intent is not bound to the published target: {relative}"
                    )
                intent_now = os.stat(intent_name, dir_fd=parent, follow_symlinks=False)
                if (intent_now.st_dev, intent_now.st_ino) != (
                    intent[1].st_dev,
                    intent[1].st_ino,
                ):
                    raise HostLifecycleError(
                        f"host lifecycle JSON intent changed: {relative}"
                    )
                os.unlink(intent_name, dir_fd=parent)
                os.fsync(parent)
            return
        if expected_current_digest is None:
            if current is not None:
                raise HostLifecycleError(
                    f"host lifecycle JSON target already exists: {relative}"
                )
        elif current is None or _sha256_bytes(current[0]) != expected_current_digest:
            raise HostLifecycleError(
                f"host lifecycle JSON target changed before transition: {relative}"
            )

        # A crash after rename but before intent cleanup leaves the prior JSON
        # target and intent as two names for the same recorded inode.  Consume
        # only that exact relationship, then start the next transition with a
        # fresh empty intent.  A separately created intent is preserved.
        if (
            current is not None
            and stage is None
            and intent is not None
            and expected_current_digest is not None
            and _sha256_bytes(current[0]) == expected_current_digest
        ):
            if (intent[1].st_dev, intent[1].st_ino) != (
                current[1].st_dev,
                current[1].st_ino,
            ):
                raise HostLifecycleError(
                    f"host lifecycle JSON intent is not bound to the prior target: {relative}"
                )
            current_intent = os.stat(
                intent_name,
                dir_fd=parent,
                follow_symlinks=False,
            )
            if (current_intent.st_dev, current_intent.st_ino) != (
                intent[1].st_dev,
                intent[1].st_ino,
            ):
                raise HostLifecycleError(
                    f"host lifecycle JSON intent changed: {relative}"
                )
            os.unlink(intent_name, dir_fd=parent)
            os.fsync(parent)
            intent = None
            intent_preexisting = False

        if intent is None:
            if stage is not None:
                raise HostLifecycleError(
                    f"host lifecycle JSON recovery stage lacks its plan-bound intent: {relative}"
                )
            descriptor = os.open(
                intent_name,
                os.O_RDWR
                | os.O_CREAT
                | os.O_EXCL
                | getattr(os, "O_NOFOLLOW", 0)
                | getattr(os, "O_CLOEXEC", 0),
                0o644,
                dir_fd=parent,
            )
            try:
                os.fsync(descriptor)
                intent_metadata = os.fstat(descriptor)
            finally:
                os.close(descriptor)
            os.fsync(parent)
            intent = (b"", intent_metadata)
        elif stage is None and intent_preexisting:
            raise HostLifecycleError(
                f"host lifecycle JSON intent lacks its bound recovery stage: {relative}"
            )
        if stage is None:
            os.link(
                intent_name,
                stage_name,
                src_dir_fd=parent,
                dst_dir_fd=parent,
                follow_symlinks=False,
            )
            os.fsync(parent)
            stage = read_name(stage_name, f"host lifecycle JSON recovery stage for {relative}")
        if stage is None or intent is None or (stage[1].st_dev, stage[1].st_ino) != (
            intent[1].st_dev,
            intent[1].st_ino,
        ):
            raise HostLifecycleError(
                f"host lifecycle JSON recovery stage is not bound to its intent: {relative}"
            )
        descriptor = os.open(
            stage_name,
            os.O_WRONLY
            | os.O_TRUNC
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0),
            dir_fd=parent,
        )
        try:
            rewritten = os.fstat(descriptor)
            if (rewritten.st_dev, rewritten.st_ino) != (
                intent[1].st_dev,
                intent[1].st_ino,
            ):
                raise HostLifecycleError(
                    f"host lifecycle JSON recovery stage identity changed: {relative}"
                )
            offset = 0
            while offset < len(content):
                written = os.write(descriptor, content[offset:])
                if written <= 0:
                    raise HostLifecycleError(
                        f"host lifecycle JSON recovery stage made no write progress: {relative}"
                    )
                offset += written
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        os.replace(
            stage_name,
            name,
            src_dir_fd=parent,
            dst_dir_fd=parent,
        )
        os.fsync(parent)
        published = read_name(name, f"host lifecycle JSON {relative}")
        owner = read_name(intent_name, f"host lifecycle JSON intent for {relative}")
        if (
            published is None
            or owner is None
            or _sha256_bytes(published[0]) != desired_digest
            or (published[1].st_dev, published[1].st_ino)
            != (owner[1].st_dev, owner[1].st_ino)
        ):
            raise HostLifecycleError(
                f"host lifecycle JSON publication lost its intent binding: {relative}"
            )
        os.unlink(intent_name, dir_fd=parent)
        os.fsync(parent)


def _existing_apply_intents(root: RootHandle) -> list[str]:
    try:
        with _parent_directory_fd(root, INSTALL_LOCK_RELATIVE, create=False) as (parent, _):
            names = os.listdir(parent)
    except FileNotFoundError:
        return []
    prefix = Path(APPLY_INTENT_PREFIX).name
    return sorted(
        (Path(".agent-team") / name).as_posix()
        for name in names
        if name.startswith(prefix)
    )


def _ensure_apply_intent(
    root: RootHandle,
    relative: str,
    *,
    may_resume: bool,
) -> dict[str, Any]:
    """Create or finish exact initial-apply authority without deleting a collision."""

    with _parent_directory_fd(root, relative, create=True) as (parent, name):
        flags = (
            os.O_RDWR
            | getattr(os, "O_NONBLOCK", 0)
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0)
        )
        created = False
        try:
            descriptor = os.open(
                name,
                flags | os.O_CREAT | os.O_EXCL,
                0o600,
                dir_fd=parent,
            )
            created = True
        except FileExistsError:
            if not may_resume:
                raise HostLifecycleError(
                    "host apply intent changed after planning; create and confirm a new plan"
                )
            try:
                descriptor = os.open(name, flags, dir_fd=parent)
            except OSError as exc:
                raise HostLifecycleError(f"cannot open host apply intent: {exc}") from exc
        except OSError as exc:
            raise HostLifecycleError(f"cannot create host apply intent: {exc}") from exc
        try:
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode):
                raise HostLifecycleError("host apply intent must be a regular file")
            os.lseek(descriptor, 0, os.SEEK_SET)
            content = _read_descriptor_bytes(descriptor)
            if content:
                raise HostLifecycleError("host apply intent must be empty")
            if created:
                os.fsync(descriptor)
            os.lseek(descriptor, 0, os.SEEK_SET)
            metadata = os.fstat(descriptor)
        finally:
            os.close(descriptor)
        os.fsync(parent)
        return _file_binding(content, metadata)


def _host_descriptor(host_id: str) -> dict[str, Any]:
    try:
        from core.host_catalog import load_host_descriptor
    except ImportError as exc:
        raise HostLifecycleError("host catalog is unavailable") from exc
    try:
        descriptor = load_host_descriptor(host_id)
    except (KeyError, RuntimeError, ValueError) as exc:
        raise HostLifecycleError(str(exc)) from exc
    return descriptor


def _stage_relative(path: str, digest: str) -> str:
    target = Path(path)
    identity = hashlib.sha256(f"{path}\0{digest}".encode("utf-8")).hexdigest()[:24]
    return (target.parent / f".{target.name}.host-stage-{identity}").as_posix()


def _source_records(team_root: Path, host_id: str) -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    platform_root = team_root / "platforms" / host_id
    if not platform_root.is_dir() or platform_root.is_symlink():
        raise HostLifecycleError(f"compiled host projection is missing: {host_id}")

    def add_tree(source_root: Path, destination_prefix: Path) -> None:
        for source in sorted(source_root.rglob("*")):
            if source.is_symlink():
                raise HostLifecycleError(f"host installation refuses symbolic links: {source}")
            if not source.is_file():
                continue
            relative = (destination_prefix / source.relative_to(source_root)).as_posix()
            records.append(
                {
                    "source": source.relative_to(team_root).as_posix(),
                    "path": relative,
                    "sha256": _sha256_bytes(source.read_bytes()),
                    "management": "factory-created",
                }
            )

    add_tree(platform_root, Path())
    for name in SHARED_CONTEXT:
        source = team_root / name
        destination = Path(".agent-team/context") / name
        if source.is_dir():
            add_tree(source, destination)
        elif source.is_file() and not source.is_symlink():
            records.append(
                {
                    "source": source.relative_to(team_root).as_posix(),
                    "path": destination.as_posix(),
                    "sha256": _sha256_bytes(source.read_bytes()),
                    "management": "factory-created",
                }
            )
        else:
            raise HostLifecycleError(f"required shared context is missing or unsafe: {name}")
    design_source = team_root / DESIGN_RELATIVE
    records.append(
        {
            "source": DESIGN_RELATIVE,
            "path": ".agent-team/context/team-design.json",
            "sha256": _sha256_bytes(design_source.read_bytes()),
            "management": "factory-created",
        }
    )
    for record in records:
        record["stage_path"] = _stage_relative(record["path"], record["sha256"])
        target = Path(record["path"])
        record["intent_path"] = (
            target.parent / f".{target.name}.host-intent-{uuid.uuid4().hex}"
        ).as_posix()
    paths = [record["path"] for record in records]
    if len(paths) != len(set(paths)):
        raise HostLifecycleError("compiled host projection contains duplicate destination paths")
    return sorted(records, key=lambda item: item["path"])


def build_install_plan(team: Path, host_id: str, destination: Path) -> dict[str, Any]:
    team_root = team.resolve()
    if not _display_safe_path(str(team_root)):
        raise HostLifecycleError("authoritative team path is unsafe to display for approval")
    summary = inspect_context_team(team_root)
    design = _load_object(team_root / DESIGN_RELATIVE, "team design")
    if host_id not in design["platform_targets"]:
        raise HostLifecycleError(f"team was not compiled for host {host_id}")
    descriptor = _host_descriptor(host_id)
    target = destination.resolve()
    if not _display_safe_path(str(target)):
        raise HostLifecycleError("host destination path is unsafe to display for approval")
    if destination.is_symlink() or target == Path(target.anchor):
        raise HostLifecycleError("host destination must be a non-root, non-symbolic-link path")
    if target == team_root or team_root in target.parents:
        raise HostLifecycleError("host destination must be outside the authoritative team")
    if target == ROOT or ROOT in target.parents:
        raise HostLifecycleError("host destination must be outside the Factory repository")
    if target.exists() and not target.is_dir():
        raise HostLifecycleError("host destination must be a directory or an absent path")
    if target.is_dir() and _relative_present(target, METADATA_STAGE_RELATIVE):
        raise HostLifecycleError(
            "host destination contains the reserved metadata recovery stage; "
            "reconcile it before creating a plan"
        )
    if target.is_dir() and _existing_apply_intents(target):
        raise HostLifecycleError(
            "host destination contains the reserved initial apply intent; "
            "reconcile it before creating a plan"
        )
    if target.is_dir():
        try:
            with _parent_directory_fd(target, INSTALL_LOCK_RELATIVE, create=False) as (
                parent,
                _,
            ):
                if any(name.startswith(".host-metadata.intent-") for name in os.listdir(parent)):
                    raise HostLifecycleError(
                        "host destination contains a reserved metadata intent; reconcile it before creating a plan"
                    )
        except FileNotFoundError:
            pass
    prior_guard = _guard_binding(target) if target.is_dir() else None
    prior_tombstone = _tombstone_binding(target) if target.is_dir() else None
    lock_path = team_root / LOCK_RELATIVE
    proposal = {
        "team": {
            "root": str(team_root),
            "team_id": summary["team_id"],
            "design_digest": _sha256_bytes((team_root / DESIGN_RELATIVE).read_bytes()),
            "lock_digest": _sha256_bytes(lock_path.read_bytes()),
        },
        "host": {
            "id": host_id,
            "support_tier": descriptor["support_tier"],
            "descriptor_version": descriptor["schema_version"],
            "descriptor_digest": _digest(descriptor),
            "external_apply": False,
        },
        "lifecycle": _proposal_lifecycle_contract(
            destination=target,
            prior_guard=prior_guard,
            prior_tombstone=prior_tombstone,
        ),
        "destination": str(target),
        "files": _source_records(team_root, host_id),
        "effects": {
            "filesystem_writes": True,
            "filesystem_deletes": True,
            "persistent_filesystem_deletes": prior_tombstone is not None,
            "external_writes": False,
            "bindings_created": False,
            "tasks_started": False,
            "credentials_read": False,
        },
        "limitations": [
            "Apply creates only previously absent projected files plus the lifecycle metadata paths displayed in this proposal.",
            "The metadata recovery stage and initial apply intent must be absent at planning; only an exact digest-bound in-progress lifecycle may rebuild or remove its own crash residue.",
            "Uninstall retains the empty operation guard and digest-bound tombstone so concurrent operations and replay remain fail-closed.",
            "Uninstall removes no directories because the file-only ownership record cannot prove who created an empty parent directory.",
            "The kernel lock serializes cooperating local Factory processes; hostile privileged filesystem mutation is outside this boundary.",
            "Apply does not edit live host configuration, authenticate, bind channels, start tasks, or call external APIs.",
            "Host object import or runtime activation remains a separate host-specific, explicitly authorized operation.",
        ],
    }
    proposal["lifecycle"]["initial_apply_intent"] = (
        APPLY_INTENT_PREFIX + uuid.uuid4().hex
    )
    metadata_identity = hashlib.sha256(
        (_canonical(proposal) + "\0metadata-intent").encode("utf-8")
    ).hexdigest()[:32]
    proposal["lifecycle"]["metadata_recovery_intent"] = (
        ".agent-team/.host-metadata.intent-" + metadata_identity
    )
    plan = {
        "schema_version": "1.1.0",
        "state": "DRAFT",
        "proposal": proposal,
        "proposal_digest": _digest(proposal),
        "confirmation": None,
    }
    validate_install_plan(plan)
    return plan


def _validate_proposal_semantics(proposal: dict[str, Any]) -> None:
    destination = Path(proposal["destination"])
    if (
        not _display_safe_path(proposal["destination"])
        or not _display_safe_path(proposal["team"]["root"])
        or not destination.is_absolute()
        or destination == Path(destination.anchor)
    ):
        raise HostLifecycleError("host installation destination must be an absolute non-root path")
    lifecycle = proposal["lifecycle"]
    expected_lifecycle = _proposal_lifecycle_contract(
        destination=destination,
        prior_guard=lifecycle["expected_prior_guard"],
        prior_tombstone=lifecycle["expected_prior_uninstall_tombstone"],
        metadata_intent=lifecycle.get("metadata_recovery_intent"),
    )
    expected_lifecycle["initial_apply_intent"] = lifecycle.get("initial_apply_intent")
    if (
        lifecycle != expected_lifecycle
        or not isinstance(lifecycle.get("metadata_recovery_intent"), str)
        or not lifecycle["metadata_recovery_intent"].startswith(
            ".agent-team/.host-metadata.intent-"
        )
        or len(lifecycle["metadata_recovery_intent"])
        != len(".agent-team/.host-metadata.intent-") + 32
        or any(
            character not in "0123456789abcdef"
            for character in lifecycle["metadata_recovery_intent"][
                len(".agent-team/.host-metadata.intent-") :
            ]
        )
        or not isinstance(lifecycle.get("initial_apply_intent"), str)
        or not lifecycle["initial_apply_intent"].startswith(APPLY_INTENT_PREFIX)
        or len(lifecycle["initial_apply_intent"]) != len(APPLY_INTENT_PREFIX) + 32
        or any(
            character not in "0123456789abcdef"
            for character in lifecycle["initial_apply_intent"][len(APPLY_INTENT_PREFIX) :]
        )
    ):
        raise HostLifecycleError("host lifecycle metadata contract differs from this Factory")
    if not proposal["effects"]["filesystem_deletes"]:
        raise HostLifecycleError("host lifecycle must disclose transient scratch deletion")
    if proposal["effects"]["persistent_filesystem_deletes"] != lifecycle[
        "remove_prior_uninstall_tombstone"
    ]:
        raise HostLifecycleError("host lifecycle delete effect differs from its baseline")
    seen: set[str] = set()
    stages: set[str] = set()
    for record in proposal["files"]:
        relative = record["path"]
        source = record["source"]
        stage_path = record["stage_path"]
        intent_path = record["intent_path"]
        if (
            not _safe_relative(relative)
            or not _safe_relative(source)
            or not _safe_relative(stage_path)
            or not _safe_relative(intent_path)
        ):
            raise HostLifecycleError("host installation file paths must be safe relative paths")
        if relative in RESERVED_DESTINATIONS or relative in seen:
            raise HostLifecycleError("host installation file path is reserved or duplicated")
        if (
            stage_path in RESERVED_DESTINATIONS
            or stage_path in seen
            or stage_path in stages
            or stage_path != _stage_relative(relative, record["sha256"])
            or relative.startswith(APPLY_INTENT_PREFIX)
            or stage_path.startswith(APPLY_INTENT_PREFIX)
            or relative == lifecycle["metadata_recovery_intent"]
            or stage_path == lifecycle["metadata_recovery_intent"]
            or intent_path in RESERVED_DESTINATIONS
            or intent_path in seen
            or intent_path in stages
            or Path(intent_path).parent != Path(relative).parent
            or not Path(intent_path).name.startswith(
                f".{Path(relative).name}.host-intent-"
            )
            or len(Path(intent_path).name)
            != len(f".{Path(relative).name}.host-intent-") + 32
            or any(
                character not in "0123456789abcdef"
                for character in Path(intent_path).name[
                    len(f".{Path(relative).name}.host-intent-") :
                ]
            )
        ):
            raise HostLifecycleError("host installation stage path is reserved or inconsistent")
        seen.add(relative)
        stages.add(stage_path)
        stages.add(intent_path)
        if (
            find_inline_secret(relative)
            or find_inline_secret(source)
            or find_inline_secret(stage_path)
            or find_inline_secret(intent_path)
        ):
            raise HostLifecycleError("host installation plan contains a credential-like path")
    if seen & stages:
        raise HostLifecycleError("host installation stage path collides with a managed file")


def validate_install_plan(plan: dict[str, Any]) -> None:
    findings = validate_schema(plan, _load_schema(PLAN_SCHEMA))
    if findings:
        raise HostLifecycleError(
            "invalid host installation plan: "
            + "; ".join(f"{item.path}: {item.message}" for item in findings)
        )
    if plan["proposal_digest"] != _digest(plan["proposal"]):
        raise HostLifecycleError("host installation proposal digest differs from its content")
    planned_host = plan["proposal"]["host"]
    current_descriptor = _host_descriptor(planned_host["id"])
    if (
        planned_host["support_tier"] != current_descriptor["support_tier"]
        or planned_host["descriptor_version"] != current_descriptor["schema_version"]
        or planned_host["descriptor_digest"] != _digest(current_descriptor)
    ):
        raise HostLifecycleError(
            "host capability descriptor changed after planning; create and confirm a new plan"
        )
    if plan["state"] == "DRAFT" and plan["confirmation"] is not None:
        raise HostLifecycleError("draft host installation plan must not contain confirmation")
    if plan["state"] == "CONFIRMED":
        confirmation = plan["confirmation"]
        if confirmation is None or confirmation["proposal_digest"] != plan["proposal_digest"]:
            raise HostLifecycleError("host installation confirmation is not bound to this proposal")
        actor = confirmation["approved_by"]
        if actor != actor.strip() or not _display_safe_path(actor):
            raise HostLifecycleError(
                "host installation confirmation approved_by must be trimmed display-safe text"
            )
        if confirmation["scope"] != _expected_confirmation_scope(plan["proposal"]):
            raise HostLifecycleError(
                "host installation confirmation scope differs from the exact proposal effects"
            )
    _validate_proposal_semantics(plan["proposal"])
    if find_inline_secret(_canonical(plan)):
        raise HostLifecycleError("host installation plan contains a credential-like value")


def write_install_plan(plan: dict[str, Any], path: Path) -> None:
    validate_install_plan(plan)
    target = _unalias_path(
        path,
        label="host installation plan output",
        must_exist=False,
    )
    if not _display_safe_path(str(target)):
        raise HostLifecycleError("host installation plan path is unsafe to display for approval")
    if path.is_symlink() or target.exists():
        raise HostLifecycleError("host installation plan output already exists")
    _atomic_json(target, plan)


def load_install_plan(path: Path) -> dict[str, Any]:
    target = _unalias_path(path, label="host installation plan", must_exist=True)
    if not _display_safe_path(str(target)):
        raise HostLifecycleError("host installation plan path is unsafe to display for approval")
    plan = _load_object(target, "host installation plan")
    if plan.get("schema_version") == "1.0.0":
        raise HostLifecycleError(
            "v0.9 host plan approvals are not compatible with the v1 lifecycle; "
            "run host plan, preview, and confirm again"
        )
    validate_install_plan(plan)
    return plan


def preview_install_plan(plan: dict[str, Any]) -> str:
    validate_install_plan(plan)
    proposal = plan["proposal"]
    lines = [
        "# Host-native team installation proposal",
        "",
        f"Plan schema: `{plan['schema_version']}`",
        f"State: `{plan['state']}`",
        f"Exact proposal digest: `{plan['proposal_digest']}`",
        f"Team: `{proposal['team']['team_id']}`",
        f"Team design digest: `{proposal['team']['design_digest']}`",
        f"Team lock digest: `{proposal['team']['lock_digest']}`",
        f"Host: `{proposal['host']['id']}` (`{proposal['host']['support_tier']}`)",
        f"Host descriptor schema: `{proposal['host']['descriptor_version']}`",
        f"Host descriptor digest: `{proposal['host']['descriptor_digest']}`",
        f"Destination: `{proposal['destination']}`",
        f"Projected files created on apply: `{len(proposal['files'])}`",
        "",
        "## Exact managed files",
        "",
    ]
    lines.extend(
        f"- `{record['path']}` ← `{record['source']}` ({record['sha256']}; recovery stage `{record['stage_path']}`; owner intent `{record['intent_path']}`)"
        for record in proposal["files"]
    )
    lifecycle = proposal["lifecycle"]
    lines.extend(
        [
            "",
            "## Lifecycle metadata",
            "",
            f"- Operation guard: `{lifecycle['operation_guard']}`",
            f"- Operation guard format: `{lifecycle['operation_guard_format']}`",
            f"- Operation guard content digest: `{lifecycle['operation_guard_content_sha256']}`",
            f"- Install record: `{lifecycle['install_record']}`",
            f"- Uninstall tombstone: `{lifecycle['uninstall_tombstone']}`",
        f"- Transient metadata recovery stage: `{lifecycle['metadata_recovery_stage']}` (retained: `false`)",
            f"- Exact metadata recovery intent: `{lifecycle['metadata_recovery_intent']}` (retained: `false`)",
            "- Expected prior metadata recovery stage: `absent`",
            f"- Initial apply intent prefix: `{lifecycle['initial_apply_intent_prefix']}` (retained: `false`)",
            f"- Initial apply intent format: `{lifecycle['initial_apply_intent_format']}`",
            f"- Exact initial apply intent: `{lifecycle['initial_apply_intent']}` (expected prior state: `absent`)",
            f"- Locking: `{lifecycle['locking']}`",
            "- Apply phase: create or reuse the exact guard; create and transition the install record; do not create a new tombstone.",
            "- Uninstall phase: remove unchanged projected files and the install record; create the digest-bound tombstone.",
            "- Retained files after uninstall: "
            + ", ".join(
                f"`{path}`" for path in lifecycle["retained_files_after_uninstall"]
            ),
            f"- Directories removed by uninstall: `{str(lifecycle['directories_removed']).lower()}`",
            "- Expected prior guard: `"
            + (
                lifecycle["expected_prior_guard"]["sha256"]
                if lifecycle["expected_prior_guard"] is not None
                else "absent"
            )
            + "`",
            "- Expected prior uninstall tombstone: `"
            + (
                lifecycle["expected_prior_uninstall_tombstone"]["sha256"]
                if lifecycle["expected_prior_uninstall_tombstone"] is not None
                else "absent"
            )
            + "`",
            "- Remove exact prior uninstall tombstone on apply: `"
            + str(lifecycle["remove_prior_uninstall_tombstone"]).lower()
            + "`",
        ]
    )
    lines.extend(
        [
            "",
            "## Effects",
            "",
            f"- Filesystem writes: `{str(proposal['effects']['filesystem_writes']).lower()}`",
            f"- Filesystem deletes: `{str(proposal['effects']['filesystem_deletes']).lower()}`",
            f"- Persistent filesystem deletes: `{str(proposal['effects']['persistent_filesystem_deletes']).lower()}`",
            f"- External writes: `{str(proposal['effects']['external_writes']).lower()}`",
            f"- Credentials read: `{str(proposal['effects']['credentials_read']).lower()}`",
            f"- Bindings created: `{str(proposal['effects']['bindings_created']).lower()}`",
            f"- Tasks started: `{str(proposal['effects']['tasks_started']).lower()}`",
            "",
            "## Limitations",
            "",
        ]
    )
    lines.extend(f"- {limitation}" for limitation in proposal["limitations"])
    lines.extend(
        [
            "",
            "No live host configuration, credentials, bindings, tasks, or external APIs are used by apply.",
            "Projected files are never overwritten. A first apply refuses a pre-existing metadata stage; an exact in-progress lifecycle may recover only its own declared scratch. Apply may additionally delete only the exact prior tombstone shown above.",
            "Confirm this exact digest before applying.",
            "",
        ]
    )
    return "\n".join(lines) + "\n"


def confirm_install_plan(path: Path, *, digest: str, approved_by: str) -> dict[str, Any]:
    target = _unalias_path(path, label="host installation plan", must_exist=True)
    plan = load_install_plan(target)
    if plan["state"] != "DRAFT":
        raise HostLifecycleError("host installation plan is already confirmed")
    if digest != plan["proposal_digest"]:
        raise HostLifecycleError("confirmation digest does not match the exact host proposal")
    actor = approved_by.strip()
    if not actor or len(actor) > 160:
        raise HostLifecycleError("approved-by must be a non-empty display name up to 160 characters")
    plan["state"] = "CONFIRMED"
    plan["confirmation"] = {
        "proposal_digest": digest,
        "approved_by": actor,
        "scope": _expected_confirmation_scope(plan["proposal"]),
        "statement": CONFIRMATION_STATEMENT,
    }
    validate_install_plan(plan)
    current = load_install_plan(target)
    if current["state"] != "DRAFT" or current["proposal_digest"] != digest:
        raise HostLifecycleError("host installation plan changed before confirmation")
    _atomic_json(target, plan)
    return plan


def _validate_source(plan: dict[str, Any]) -> Path:
    proposal = plan["proposal"]
    team_root = Path(proposal["team"]["root"])
    try:
        inspect_context_team(team_root)
    except ContextTeamError as exc:
        raise HostLifecycleError(f"authoritative team is invalid: {exc}") from exc
    _read_bound_relative(
        team_root,
        DESIGN_RELATIVE,
        proposal["team"]["design_digest"],
        label="team design",
    )
    _read_bound_relative(
        team_root,
        LOCK_RELATIVE,
        proposal["team"]["lock_digest"],
        label="team lock",
    )
    for record in proposal["files"]:
        _read_bound_relative(
            team_root,
            record["source"],
            record["sha256"],
            label="planned source",
        )
    return team_root


def _lock_document(
    plan: dict[str, Any],
    status: str,
    guard_binding: dict[str, Any],
    file_bindings: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    proposal = plan["proposal"]
    return {
        "schema_version": "1.1.0",
        "status": status,
        "team_id": proposal["team"]["team_id"],
        "host": proposal["host"]["id"],
        "proposal_digest": plan["proposal_digest"],
        "destination": proposal["destination"],
        "guard_binding": guard_binding,
        "proposal": proposal,
        "files": [
            {
                "path": record["path"],
                "stage_path": record["stage_path"],
                "intent_path": record["intent_path"],
                "sha256": record["sha256"],
                "binding": (
                    file_bindings.get(record["path"])
                    if file_bindings is not None
                    else None
                ),
                "state": "PRESENT" if file_bindings is not None else "PLANNED",
            }
            for record in proposal["files"]
        ],
    }


def _copy_exclusive(
    source_root: Path,
    source_relative: str,
    destination_root: RootHandle,
    target_relative: str,
    stage_relative: str,
    intent_relative: str,
    expected_digest: str,
    *,
    resuming: bool,
) -> None:
    """Publish exact bytes through one operation-owned inode.

    The random intent is created only after the exact APPLYING lock is durable.
    It remains as a hard link to the projected target until the ACTIVE lock has
    recorded that inode.  A retry can therefore distinguish our interrupted
    publication from an unrelated byte-identical target or stage.
    """

    content, _ = _read_bound_relative(
        source_root,
        source_relative,
        expected_digest,
        label="planned source",
    )
    target = Path(target_relative)
    stage = Path(stage_relative)
    intent_path = Path(intent_relative)
    if (
        target.parent != stage.parent
        or target.parent != intent_path.parent
        or stage_relative != _stage_relative(target_relative, expected_digest)
    ):
        raise HostLifecycleError("host installation stage path differs from the exact plan")
    with _parent_directory_fd(destination_root, target_relative, create=True) as (parent, name):
        stage_name = stage.name
        intent_name = intent_path.name

        def read_entry(candidate: str, label: str) -> tuple[bytes, os.stat_result] | None:
            try:
                descriptor = os.open(
                    candidate,
                    _nonblocking_read_flags(),
                    dir_fd=parent,
                )
            except FileNotFoundError:
                return None
            except OSError as exc:
                raise HostLifecycleError(f"{label} is unsafe: {exc}") from exc
            try:
                metadata = os.fstat(descriptor)
                if not stat.S_ISREG(metadata.st_mode):
                    raise HostLifecycleError(f"{label} is not a regular file")
                return _read_descriptor_bytes(descriptor), metadata
            finally:
                os.close(descriptor)

        intent = read_entry(intent_name, f"host recovery intent {intent_relative}")
        stage_entry = read_entry(stage_name, f"host recovery stage {stage_relative}")
        target_entry = read_entry(name, f"host installation target {target_relative}")
        if not resuming and any(item is not None for item in (intent, stage_entry, target_entry)):
            raise HostLifecycleError(
                f"host installation never overwrites target, stage, or intent: {target_relative}"
            )
        if intent is None:
            if stage_entry is not None or target_entry is not None:
                raise HostLifecycleError(
                    f"host recovery target or stage lacks its operation-bound intent: {target_relative}"
                )
            flags = (
                os.O_WRONLY
                | os.O_CREAT
                | os.O_EXCL
                | getattr(os, "O_NOFOLLOW", 0)
                | getattr(os, "O_CLOEXEC", 0)
            )
            intent_descriptor = os.open(intent_name, flags, 0o644, dir_fd=parent)
            try:
                with os.fdopen(intent_descriptor, "wb") as handle:
                    handle.write(content)
                    handle.flush()
                    os.fsync(handle.fileno())
                intent_metadata = os.stat(
                    intent_name,
                    dir_fd=parent,
                    follow_symlinks=False,
                )
            except Exception:
                raise
            os.fsync(parent)
            intent = (content, intent_metadata)
        elif not resuming:
            raise HostLifecycleError(
                f"host installation never overwrites a recovery intent: {intent_relative}"
            )

        if intent is None:  # pragma: no cover - guarded above
            raise HostLifecycleError(f"host recovery intent is missing: {intent_relative}")
        intent_identity = (intent[1].st_dev, intent[1].st_ino)
        if _sha256_bytes(intent[0]) != expected_digest:
            if stage_entry is not None or target_entry is not None:
                raise HostLifecycleError(
                    f"host recovery intent drifted and is preserved: {intent_relative}"
                )
            # A process exit while creating the exclusively named intent can
            # leave only that inode partially written.  No target or stage has
            # been published, so the exact APPLYING plan may safely rebuild it.
            descriptor = os.open(
                intent_name,
                os.O_WRONLY
                | os.O_TRUNC
                | getattr(os, "O_NOFOLLOW", 0)
                | getattr(os, "O_CLOEXEC", 0),
                dir_fd=parent,
            )
            try:
                metadata = os.fstat(descriptor)
                if (metadata.st_dev, metadata.st_ino) != intent_identity:
                    raise HostLifecycleError(
                        f"host recovery intent identity changed: {target_relative}"
                    )
                offset = 0
                while offset < len(content):
                    written = os.write(descriptor, content[offset:])
                    if written <= 0:
                        raise HostLifecycleError(
                            f"host recovery intent made no write progress: {target_relative}"
                        )
                    offset += written
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
            intent = read_entry(intent_name, f"host recovery intent {intent_relative}")
            if intent is None or _sha256_bytes(intent[0]) != expected_digest:
                raise HostLifecycleError(f"host recovery intent drifted: {intent_relative}")
            intent_identity = (intent[1].st_dev, intent[1].st_ino)

        for entry, label in (
            (stage_entry, "stage"),
            (target_entry, "target"),
        ):
            if entry is not None and (
                _sha256_bytes(entry[0]) != expected_digest
                or (entry[1].st_dev, entry[1].st_ino) != intent_identity
            ):
                raise HostLifecycleError(
                    f"host recovery {label} is not bound to this operation: {target_relative}"
                )

        if stage_entry is None and target_entry is None:
            os.link(
                intent_name,
                stage_name,
                src_dir_fd=parent,
                dst_dir_fd=parent,
                follow_symlinks=False,
            )
            os.fsync(parent)
            stage_entry = read_entry(stage_name, f"host recovery stage {stage_relative}")
        elif stage_entry is None and target_entry is not None:
            # Publication finished before interruption.  Keep the intent until
            # ACTIVE records the target inode; no scratch stage is needed.
            return

        if stage_entry is None or (
            stage_entry[1].st_dev,
            stage_entry[1].st_ino,
        ) != intent_identity:
            raise HostLifecycleError(
                f"host recovery stage is not bound to this operation: {stage_relative}"
            )
        if target_entry is None:
            try:
                os.link(
                    stage_name,
                    name,
                    src_dir_fd=parent,
                    dst_dir_fd=parent,
                    follow_symlinks=False,
                )
            except FileExistsError as exc:
                raise HostLifecycleError(
                    f"host installation never overwrites: {target_relative}"
                ) from exc
            os.fsync(parent)
        final_target = read_entry(name, f"host installation target {target_relative}")
        if final_target is None or (
            _sha256_bytes(final_target[0]) != expected_digest
            or (final_target[1].st_dev, final_target[1].st_ino) != intent_identity
        ):
            raise HostLifecycleError(
                f"host installation target lost its intent binding: {target_relative}"
            )
        current_stage = os.stat(stage_name, dir_fd=parent, follow_symlinks=False)
        if (current_stage.st_dev, current_stage.st_ino) != intent_identity:
            raise HostLifecycleError(f"host recovery stage identity changed: {stage_relative}")
        os.unlink(stage_name, dir_fd=parent)
        os.fsync(parent)


def _cleanup_active_install_intents(root: RootHandle, lock: dict[str, Any]) -> None:
    """Remove only intents whose inode is recorded by the durable ACTIVE lock."""

    if lock["status"] != "ACTIVE":
        raise HostLifecycleError("host recovery intents require an active install record")
    for record in lock["files"]:
        if _relative_present(root, record["stage_path"]):
            raise HostLifecycleError(
                f"active host installation retains a recovery stage: {record['stage_path']}"
            )
        content, metadata = _read_bound_relative(
            root,
            record["path"],
            record["sha256"],
            label="managed host file",
        )
        binding = _file_binding(content, metadata)
        if binding != record["binding"]:
            raise HostLifecycleError(
                f"managed host file identity differs from the installed baseline: {record['path']}"
            )
        if _relative_present(root, record["intent_path"]):
            _unlink_bound_relative(
                root,
                record["intent_path"],
                record["sha256"],
                allow_missing=False,
                expected_binding=record["binding"],
            )


def _load_install_lock(
    destination: Path,
    root: RootHandle | None = None,
) -> dict[str, Any]:
    storage_root: RootHandle = destination if root is None else root
    lock, _, _ = _load_relative_object(
        storage_root,
        INSTALL_LOCK_RELATIVE,
        "host installation lock",
    )
    version = lock.get("schema_version")
    if version == "1.0.0":
        schema_path = LEGACY_LOCK_SCHEMA
    elif version == "1.1.0":
        schema_path = LOCK_SCHEMA
    else:
        raise HostLifecycleError("unsupported host installation lock schema version")
    findings = validate_schema(lock, _load_schema(schema_path))
    if findings:
        raise HostLifecycleError(
            "invalid host installation lock: "
            + "; ".join(f"{item.path}: {item.message}" for item in findings)
        )
    if Path(lock["destination"]) != destination:
        raise HostLifecycleError("host installation lock belongs to another destination")
    if version == "1.1.0":
        proposal = lock["proposal"]
        candidate = {
            "schema_version": "1.1.0",
            "state": "DRAFT",
            "proposal": proposal,
            "proposal_digest": lock["proposal_digest"],
            "confirmation": None,
        }
        proposal_findings = validate_schema(candidate, _load_schema(PLAN_SCHEMA))
        if proposal_findings:
            raise HostLifecycleError(
                "host installation lock contains an invalid authority proposal: "
                + "; ".join(
                    f"{item.path}: {item.message}" for item in proposal_findings
                )
            )
        _validate_proposal_semantics(proposal)
        if _digest(proposal) != lock["proposal_digest"]:
            raise HostLifecycleError("host installation lock authority digest is invalid")
        expected_files = [
            (record["path"], record["stage_path"], record["intent_path"], record["sha256"])
            for record in proposal["files"]
        ]
        actual_files = [
            (record["path"], record["stage_path"], record["intent_path"], record["sha256"])
            for record in lock["files"]
        ]
        if actual_files != expected_files:
            raise HostLifecycleError("host installation lock files differ from its authority proposal")
        if lock["status"] == "APPLYING":
            if any(
                record["binding"] is not None or record["state"] != "PLANNED"
                for record in lock["files"]
            ):
                raise HostLifecycleError(
                    "applying host installation lock cannot claim installed file identities"
                )
        else:
            for record in lock["files"]:
                binding = record["binding"]
                if not isinstance(binding, dict) or binding["sha256"] != record["sha256"]:
                    raise HostLifecycleError(
                        "active host installation lock lacks an exact installed file identity"
                    )
                if lock["status"] == "ACTIVE" and record["state"] != "PRESENT":
                    raise HostLifecycleError(
                        "active host installation lock cannot claim removed files"
                    )
                if lock["status"] == "UNINSTALLING" and record["state"] not in {
                    "PRESENT",
                    "QUARANTINED",
                    "REMOVED",
                }:
                    raise HostLifecycleError(
                        "uninstalling host installation lock has an invalid file state"
                    )
        if (
            lock["team_id"] != proposal["team"]["team_id"]
            or lock["host"] != proposal["host"]["id"]
            or lock["destination"] != proposal["destination"]
        ):
            raise HostLifecycleError("host installation lock identity differs from its proposal")
    return lock


def _tombstone_document(lock: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "status": "UNINSTALLED",
        "team_id": lock["team_id"],
        "host": lock["host"],
        "proposal_digest": lock["proposal_digest"],
        "destination": lock["destination"],
        "removed_files": len(lock["files"]),
    }


def _load_uninstall_tombstone(
    destination: Path,
    root: RootHandle | None = None,
) -> dict[str, Any]:
    storage_root: RootHandle = destination if root is None else root
    tombstone, _, _ = _load_relative_object(
        storage_root,
        UNINSTALL_TOMBSTONE_RELATIVE,
        "host uninstall tombstone",
    )
    findings = validate_schema(tombstone, _load_schema(TOMBSTONE_SCHEMA))
    if findings:
        raise HostLifecycleError(
            "invalid host uninstall tombstone: "
            + "; ".join(f"{item.path}: {item.message}" for item in findings)
        )
    if Path(tombstone["destination"]) != destination:
        raise HostLifecycleError("host uninstall tombstone belongs to another destination")
    return tombstone


def _tombstone_binding(
    destination: Path,
    root: RootHandle | None = None,
) -> dict[str, Any] | None:
    storage_root: RootHandle = destination if root is None else root
    if not _relative_present(storage_root, UNINSTALL_TOMBSTONE_RELATIVE):
        return None
    tombstone, content, metadata = _load_relative_object(
        storage_root,
        UNINSTALL_TOMBSTONE_RELATIVE,
        "host uninstall tombstone",
    )
    findings = validate_schema(tombstone, _load_schema(TOMBSTONE_SCHEMA))
    if findings:
        raise HostLifecycleError(
            "invalid host uninstall tombstone: "
            + "; ".join(f"{item.path}: {item.message}" for item in findings)
        )
    if Path(tombstone["destination"]) != destination:
        raise HostLifecycleError("host uninstall tombstone belongs to another destination")
    return {
        **_file_binding(content, metadata),
        "team_id": tombstone["team_id"],
        "host": tombstone["host"],
        "proposal_digest": tombstone["proposal_digest"],
    }


def _unlink_bound_relative(
    root: RootHandle,
    relative: str,
    expected_digest: str,
    *,
    allow_missing: bool,
    expected_binding: dict[str, Any] | None = None,
) -> bool:
    """Recheck bytes and file identity immediately before unlinking one managed path."""

    try:
        with _parent_directory_fd(root, relative, create=False) as (parent, name):
            try:
                descriptor = os.open(
                    name,
                    _nonblocking_read_flags(),
                    dir_fd=parent,
                )
            except FileNotFoundError:
                if allow_missing:
                    return False
                raise HostLifecycleError(f"managed host file is missing: {relative}")
            try:
                metadata = os.fstat(descriptor)
                if not stat.S_ISREG(metadata.st_mode):
                    raise HostLifecycleError(f"managed host file is unsafe: {relative}")
                content = _read_descriptor_bytes(descriptor)
                if _sha256_bytes(content) != expected_digest:
                    raise HostLifecycleError(f"managed host file drifted: {relative}")
                if expected_binding is not None:
                    actual_binding = _file_binding(content, metadata)
                    binding_keys = ("sha256", "size", "device", "inode")
                    if any(
                        actual_binding[key] != expected_binding[key]
                        for key in binding_keys
                    ):
                        raise HostLifecycleError(
                            f"managed host file identity differs from the approved baseline: {relative}"
                        )
                current = os.stat(name, dir_fd=parent, follow_symlinks=False)
                if not stat.S_ISREG(current.st_mode) or (
                    current.st_dev,
                    current.st_ino,
                ) != (metadata.st_dev, metadata.st_ino):
                    raise HostLifecycleError(
                        f"managed host file identity changed before uninstall: {relative}"
                    )
                os.unlink(name, dir_fd=parent)
                os.fsync(parent)
            finally:
                os.close(descriptor)
    except HostLifecycleError:
        raise
    except OSError as exc:
        raise HostLifecycleError(f"cannot uninstall managed host file {relative}: {exc}") from exc
    return True


def _quarantine_bound_relative(
    root: RootHandle,
    relative: str,
    quarantine_relative: str,
    expected_binding: dict[str, Any],
) -> None:
    """Hard-link one exact managed inode to its declared recovery path."""

    target = Path(relative)
    quarantine = Path(quarantine_relative)
    if target.parent != quarantine.parent:
        raise HostLifecycleError("managed quarantine path differs from its target")
    try:
        with _parent_directory_fd(root, relative, create=False) as (parent, name):
            quarantine_name = quarantine.name
            descriptor = os.open(name, _nonblocking_read_flags(), dir_fd=parent)
            try:
                metadata = os.fstat(descriptor)
                content = _read_descriptor_bytes(descriptor)
                if (
                    not stat.S_ISREG(metadata.st_mode)
                    or _file_binding(content, metadata) != expected_binding
                ):
                    raise HostLifecycleError(
                        f"managed host file identity differs from the installed baseline: {relative}"
                    )
                try:
                    quarantine_metadata = os.stat(
                        quarantine_name,
                        dir_fd=parent,
                        follow_symlinks=False,
                    )
                except FileNotFoundError:
                    os.link(
                        name,
                        quarantine_name,
                        src_dir_fd=parent,
                        dst_dir_fd=parent,
                        follow_symlinks=False,
                    )
                    os.fsync(parent)
                    quarantine_metadata = os.stat(
                        quarantine_name,
                        dir_fd=parent,
                        follow_symlinks=False,
                    )
                if not stat.S_ISREG(quarantine_metadata.st_mode):
                    raise HostLifecycleError(
                        f"managed quarantine path is unsafe: {quarantine_relative}"
                    )
                current = os.stat(name, dir_fd=parent, follow_symlinks=False)
                if (
                    (current.st_dev, current.st_ino)
                    != (metadata.st_dev, metadata.st_ino)
                    or (quarantine_metadata.st_dev, quarantine_metadata.st_ino)
                    != (metadata.st_dev, metadata.st_ino)
                ):
                    raise HostLifecycleError(
                        f"managed host file identity changed before quarantine: {relative}"
                    )
            finally:
                os.close(descriptor)
    except HostLifecycleError:
        raise
    except OSError as exc:
        raise HostLifecycleError(
            f"cannot quarantine managed host file {relative}: {exc}"
        ) from exc


def _verify_installation_locked(
    root: Path,
    storage_root: RootHandle | None = None,
    *,
    allow_metadata_recovery_stage: bool = False,
) -> dict[str, Any]:
    handle: RootHandle = root if storage_root is None else storage_root
    lock = _load_install_lock(root, handle)
    if lock["status"] != "ACTIVE":
        raise HostLifecycleError("host installation is incomplete")
    legacy = lock["schema_version"] == "1.0.0"
    if not legacy:
        current_guard = _guard_binding(root, handle)
        if current_guard != lock["guard_binding"]:
            raise HostLifecycleError("host lifecycle guard differs from the install authority")
        if _tombstone_binding(root, handle) is not None:
            raise HostLifecycleError("active host installation has an unexpected uninstall tombstone")
    for record in lock["files"]:
        content, metadata = _read_bound_relative(
            handle,
            record["path"],
            record["sha256"],
            label="managed host file",
        )
        if not legacy and _file_binding(content, metadata) != record["binding"]:
            raise HostLifecycleError(
                f"managed host file identity differs from the installed baseline: {record['path']}"
            )
    if not legacy:
        for record in lock["proposal"]["files"]:
            if _relative_present(handle, record["stage_path"]):
                raise HostLifecycleError(
                    f"active host installation retains a recovery stage: {record['stage_path']}"
                )
            if _relative_present(handle, record["intent_path"]):
                raise HostLifecycleError(
                    f"active host installation retains a recovery intent: {record['intent_path']}"
                )
        metadata_recovery_stage_present = _relative_present(
            handle, METADATA_STAGE_RELATIVE
        )
        if metadata_recovery_stage_present and not allow_metadata_recovery_stage:
            raise HostLifecycleError(
                "active host installation retains the metadata recovery stage"
            )
        if _existing_apply_intents(handle):
            raise HostLifecycleError("active host installation retains an initial apply intent")
    else:
        metadata_recovery_stage_present = False
    return {
        "status": "LEGACY_UNBOUND" if legacy else "VALID",
        "team_id": lock["team_id"],
        "host": lock["host"],
        "destination": str(root),
        "proposal_digest": lock["proposal_digest"],
        "managed_files": len(lock["files"]),
        "ownership_bound": not legacy,
        "destructive_uninstall_enabled": not legacy,
        "metadata_recovery_stage_present": metadata_recovery_stage_present,
        "lifecycle": _lifecycle_contract(root) if not legacy else None,
        "external_integrations_enabled": False,
    }


def verify_installation(destination: Path) -> dict[str, Any]:
    root = destination.resolve()
    if destination.is_symlink() or not root.is_dir():
        raise HostLifecycleError("host installation destination is missing or symbolic")
    initial_lock = _load_install_lock(root)
    if initial_lock["schema_version"] == "1.0.0":
        report = _verify_installation_locked(root)
        report["concurrency_guarded"] = False
        report["lifecycle_compatibility"] = "v0.9-legacy-read-only"
        return report
    guard = root / OPERATION_GUARD_RELATIVE
    if not guard.exists() and not guard.is_symlink():
        raise HostLifecycleError("v1 host lifecycle guard is missing")
    with _operation_lock(root, create=False) as operation:
        _assert_directory_binding(root, operation["root_binding"])
        report = _verify_installation_locked(root, operation["root_fd"])
        report["concurrency_guarded"] = True
        report["lifecycle_compatibility"] = "v1-proposal-bound"
        return report


def preview_uninstall(destination: Path) -> dict[str, Any]:
    """Return the exact deletion scope without changing lifecycle state."""

    root = destination.resolve()
    if destination.is_symlink() or not root.is_dir():
        raise HostLifecycleError("host installation destination is missing or symbolic")
    lock_path = root / INSTALL_LOCK_RELATIVE
    tombstone_path = root / UNINSTALL_TOMBSTONE_RELATIVE
    if not lock_path.exists() and not lock_path.is_symlink():
        if not tombstone_path.exists() and not tombstone_path.is_symlink():
            raise HostLifecycleError("host installation lock is missing")
        with _operation_lock(root, create=False) as operation:
            handle = operation["root_fd"]
            _assert_directory_binding(root, operation["root_binding"])
            if _relative_present(handle, INSTALL_LOCK_RELATIVE):
                raise HostLifecycleError(
                    "host lifecycle changed during uninstall preview; run preview again"
                )
            tombstone = _load_uninstall_tombstone(root, handle)
            return {
                "status": "ALREADY_UNINSTALLED",
                "destination": str(root),
                "proposal_digest": tombstone["proposal_digest"],
                "filesystem_deletes": [],
                "filesystem_creates": [],
                "transient_files": [],
                "retained_files": _lifecycle_contract(root)["retained_files_after_uninstall"],
                "directories_removed": False,
                "requires_human_process_confirmation": False,
                "mutation_performed": False,
            }

    initial = _load_install_lock(root)
    if initial["schema_version"] == "1.0.0":
        return {
            "status": "LEGACY_UNBOUND",
            "destination": str(root),
            "proposal_digest": initial["proposal_digest"],
            "filesystem_deletes": [],
            "filesystem_creates": [],
            "transient_files": [],
            "directories_removed": False,
            "requires_human_process_confirmation": False,
            "destructive_uninstall_enabled": False,
            "reason": "v0.9 lock does not contain proposal-bound ownership; reconcile manually",
            "mutation_performed": False,
        }

    with _operation_lock(root, create=False) as operation:
        handle = operation["root_fd"]
        _assert_directory_binding(root, operation["root_binding"])
        lock = _load_install_lock(root, handle)
        if lock["guard_binding"] != operation["guard_binding"]:
            raise HostLifecycleError("host lifecycle guard differs from the install authority")
        filesystem_deletes: list[str] = []
        filesystem_creates: list[str] = []
        transient_files: list[str] = [METADATA_STAGE_RELATIVE]
        if lock["status"] == "ACTIVE":
            _verify_installation_locked(
                root,
                handle,
                allow_metadata_recovery_stage=True,
            )
            for record in lock["files"]:
                filesystem_deletes.extend((record["path"], record["stage_path"]))
                filesystem_creates.append(record["stage_path"])
                transient_files.append(record["stage_path"])
        elif lock["status"] == "UNINSTALLING":
            for record in lock["files"]:
                state = record["state"]
                target_present = _relative_present(handle, record["path"])
                quarantine_present = _relative_present(handle, record["stage_path"])
                if state == "REMOVED":
                    if quarantine_present:
                        content, metadata = _read_bound_relative(
                            handle,
                            record["stage_path"],
                            record["sha256"],
                            label="managed quarantine file",
                        )
                        if _file_binding(content, metadata) != record["binding"]:
                            raise HostLifecycleError(
                                "managed quarantine file identity differs from the installed baseline: "
                                + record["stage_path"]
                            )
                        filesystem_deletes.append(record["stage_path"])
                        transient_files.append(record["stage_path"])
                    continue
                if quarantine_present:
                    content, metadata = _read_bound_relative(
                        handle,
                        record["stage_path"],
                        record["sha256"],
                        label="managed quarantine file",
                    )
                    if _file_binding(content, metadata) != record["binding"]:
                        raise HostLifecycleError(
                            "managed quarantine file identity differs from the installed baseline: "
                            + record["stage_path"]
                        )
                    filesystem_deletes.append(record["stage_path"])
                    transient_files.append(record["stage_path"])
                elif state == "QUARANTINED":
                    raise HostLifecycleError(
                        "managed quarantine file is missing: " + record["stage_path"]
                    )
                else:
                    filesystem_creates.append(record["stage_path"])
                    filesystem_deletes.append(record["stage_path"])
                    transient_files.append(record["stage_path"])
                if target_present and state == "PRESENT":
                    content, metadata = _read_bound_relative(
                        handle,
                        record["path"],
                        record["sha256"],
                        label="remaining managed host file",
                    )
                    if _file_binding(content, metadata) != record["binding"]:
                        raise HostLifecycleError(
                            "remaining managed host file identity differs from the installed baseline: "
                            + record["path"]
                        )
                    filesystem_deletes.append(record["path"])
                elif state == "PRESENT":
                    raise HostLifecycleError(
                        "managed host file disappeared before quarantine: "
                        + record["path"]
                    )
                elif target_present:
                    metadata = _relative_stat(handle, record["path"])
                    if metadata is not None and _metadata_matches_binding(
                        metadata,
                        record["binding"],
                    ):
                        filesystem_deletes.append(record["path"])
        else:
            raise HostLifecycleError("host installation is not uninstallable in its current state")
        expected_tombstone = _tombstone_document(lock)
        if _relative_present(handle, UNINSTALL_TOMBSTONE_RELATIVE):
            if _load_uninstall_tombstone(root, handle) != expected_tombstone:
                raise HostLifecycleError("host uninstall tombstone differs from this installation")
        return {
            "status": lock["status"],
            "destination": str(root),
            "team_id": lock["team_id"],
            "host": lock["host"],
            "proposal_digest": lock["proposal_digest"],
            "filesystem_deletes": list(dict.fromkeys(filesystem_deletes))
            + [INSTALL_LOCK_RELATIVE, METADATA_STAGE_RELATIVE],
            "filesystem_creates": list(dict.fromkeys(filesystem_creates))
            + [
                UNINSTALL_TOMBSTONE_RELATIVE,
                METADATA_STAGE_RELATIVE,
            ],
            "transient_files": list(dict.fromkeys(transient_files)),
            "retained_files": _lifecycle_contract(root)["retained_files_after_uninstall"],
            "directories_removed": False,
            "requires_human_process_confirmation": lock["status"] == "ACTIVE",
            "confirmation_mechanism": (
                "review this preview, then provide the exact proposal digest to host uninstall; "
                "the CLI records no authenticated approval assertion"
            ),
            "mutation_performed": False,
        }


def apply_install_plan(path: Path) -> dict[str, Any]:
    plan = load_install_plan(path)
    if plan["state"] != "CONFIRMED":
        raise HostLifecycleError("preview and confirm the exact host plan before applying it")
    team_root = _validate_source(plan)
    proposal = plan["proposal"]
    destination = Path(proposal["destination"])
    try:
        pre_resolved = destination.resolve()
    except (OSError, RuntimeError) as exc:
        raise HostLifecycleError(
            "host installation destination path changed or became unsafe"
        ) from exc
    if destination.is_symlink() or pre_resolved != destination:
        raise HostLifecycleError("host installation destination path changed or became unsafe")
    destination.mkdir(parents=True, exist_ok=True)
    try:
        resolved = destination.resolve()
    except (OSError, RuntimeError) as exc:
        raise HostLifecycleError(
            "host installation destination path changed or became unsafe"
        ) from exc
    if resolved != destination or not resolved.is_dir():
        raise HostLifecycleError("host installation destination path changed or became unsafe")

    with _operation_lock(resolved, create=True) as operation:
        handle = operation["root_fd"]
        root_binding = operation["root_binding"]
        guard_binding = operation["guard_binding"]
        _assert_directory_binding(resolved, root_binding)
        lock_present = _relative_present(handle, INSTALL_LOCK_RELATIVE)
        resuming = False
        intent_binding: dict[str, Any] | None = None
        intent_relative = proposal["lifecycle"]["initial_apply_intent"]
        if lock_present:
            intents = _existing_apply_intents(handle)
            unexpected_intents = [item for item in intents if item != intent_relative]
            if unexpected_intents:
                raise HostLifecycleError(
                    "host apply intent differs from this exact plan"
                )
            lock = _load_install_lock(resolved, handle)
            if lock["schema_version"] == "1.0.0":
                raise HostLifecycleError(
                    "destination has a legacy unbound install record; reconcile it before v1 apply"
                )
            if lock["guard_binding"] != guard_binding:
                raise HostLifecycleError("host lifecycle guard differs from the install authority")
            if lock["proposal_digest"] == plan["proposal_digest"] and lock["status"] == "ACTIVE":
                # ACTIVE is durable before transient ownership links are
                # removed.  Replaying the exact plan finishes only those
                # cleanup operations bound to the recorded target inodes.
                _atomic_json_relative(
                    handle,
                    INSTALL_LOCK_RELATIVE,
                    lock,
                    expected_current_digest=_sha256_bytes(
                        _canonical(lock).encode("utf-8")
                    ),
                    intent_relative=lock["proposal"]["lifecycle"][
                        "metadata_recovery_intent"
                    ],
                    allow_existing_intent=True,
                )
                _cleanup_active_install_intents(handle, lock)
                report = _verify_installation_locked(resolved, handle)
                report["status"] = "ALREADY_APPLIED"
                report["concurrency_guarded"] = True
                return report
            if lock["proposal_digest"] != plan["proposal_digest"] or lock["status"] != "APPLYING":
                raise HostLifecycleError(
                    "destination is managed by another host installation or has an invalid lifecycle state"
                )
            if lock != _lock_document(plan, "APPLYING", guard_binding):
                raise HostLifecycleError(
                    "incomplete host installation lock differs from this exact plan"
                )
            resuming = True
            if _relative_present(handle, intent_relative):
                content, metadata = _read_regular_relative(
                    handle,
                    intent_relative,
                    label="host apply intent",
                )
                if content:
                    raise HostLifecycleError(
                        "host apply intent differs from this exact plan"
                    )
                intent_binding = _file_binding(content, metadata)
        else:
            expected_guard = proposal["lifecycle"]["expected_prior_guard"]
            if expected_guard is None:
                # A valid marker with no install record is an idempotent remnant
                # from a crash after guard fsync but before APPLYING was durable.
                # It grants no file-deletion authority and is safe to reuse.
                pass
            elif operation["created"] or guard_binding != expected_guard:
                raise HostLifecycleError(
                    "host lifecycle guard differs from the approved baseline"
                )

            intents = _existing_apply_intents(handle)
            unexpected_intents = [item for item in intents if item != intent_relative]
            if unexpected_intents:
                raise HostLifecycleError(
                    "host apply intent changed after planning; create and confirm a new plan"
                )
            intent_present = intent_relative in intents
            metadata_stage_present = _relative_present(handle, METADATA_STAGE_RELATIVE)
            if intent_present:
                raise HostLifecycleError(
                    "host apply intent appeared without a durable APPLYING record; "
                    "reconcile the interrupted destination before creating and confirming a new plan"
                )
            if metadata_stage_present:
                raise HostLifecycleError(
                    "host metadata recovery stage changed after planning; "
                    "create and confirm a new plan"
                )

        expected_tombstone = proposal["lifecycle"][
            "expected_prior_uninstall_tombstone"
        ]
        current_tombstone = _tombstone_binding(resolved, handle)
        if resuming:
            if current_tombstone is not None and current_tombstone != expected_tombstone:
                raise HostLifecycleError(
                    "host uninstall tombstone differs from the approved baseline"
                )
        elif current_tombstone != expected_tombstone:
            raise HostLifecycleError(
                "host uninstall tombstone changed after planning; create and confirm a new plan"
            )

        for record in proposal["files"]:
            _assert_directory_binding(resolved, root_binding)
            if _relative_present(handle, record["path"]):
                if not resuming:
                    raise HostLifecycleError(
                        f"host installation never overwrites: {record['path']}"
                    )
                _read_bound_relative(
                    handle,
                    record["path"],
                    record["sha256"],
                    label="partially installed host file",
                )
            if _relative_present(handle, record["stage_path"]):
                if not resuming:
                    raise HostLifecycleError(
                        f"host installation never overwrites a recovery stage: {record['stage_path']}"
                    )
                _read_regular_relative(
                    handle,
                    record["stage_path"],
                    label="host recovery stage",
                )
            if _relative_present(handle, record["intent_path"]):
                if not resuming:
                    raise HostLifecycleError(
                        f"host installation never overwrites a recovery intent: {record['intent_path']}"
                    )
                _read_regular_relative(
                    handle,
                    record["intent_path"],
                    label="host recovery intent",
                )

        if not resuming:
            intent_binding = _ensure_apply_intent(
                handle,
                intent_relative,
                may_resume=False,
            )
            _assert_directory_binding(resolved, root_binding)
            _atomic_json_relative(
                handle,
                INSTALL_LOCK_RELATIVE,
                _lock_document(plan, "APPLYING", guard_binding),
                expected_current_digest=None,
                intent_relative=proposal["lifecycle"]["metadata_recovery_intent"],
                allow_existing_intent=False,
            )
        if intent_binding is not None:
            _assert_directory_binding(resolved, root_binding)
            _unlink_bound_relative(
                handle,
                intent_relative,
                intent_binding["sha256"],
                allow_missing=False,
                expected_binding=intent_binding,
            )
        if current_tombstone is not None:
            _assert_directory_binding(resolved, root_binding)
            _unlink_bound_relative(
                handle,
                UNINSTALL_TOMBSTONE_RELATIVE,
                current_tombstone["sha256"],
                allow_missing=False,
                expected_binding=current_tombstone,
            )

        for record in proposal["files"]:
            _assert_directory_binding(resolved, root_binding)
            _copy_exclusive(
                team_root,
                record["source"],
                handle,
                record["path"],
                record["stage_path"],
                record["intent_path"],
                record["sha256"],
                resuming=resuming,
            )
            _assert_directory_binding(resolved, root_binding)
        installed_bindings: dict[str, dict[str, Any]] = {}
        for record in proposal["files"]:
            content, metadata = _read_bound_relative(
                handle,
                record["path"],
                record["sha256"],
                label="installed host file",
            )
            installed_bindings[record["path"]] = _file_binding(content, metadata)
        applying_document = _lock_document(plan, "APPLYING", guard_binding)
        active_document = _lock_document(
            plan,
            "ACTIVE",
            guard_binding,
            installed_bindings,
        )
        _atomic_json_relative(
            handle,
            INSTALL_LOCK_RELATIVE,
            active_document,
            expected_current_digest=_sha256_bytes(
                _canonical(applying_document).encode("utf-8")
            ),
            intent_relative=proposal["lifecycle"]["metadata_recovery_intent"],
            allow_existing_intent=True,
        )
        _assert_directory_binding(resolved, root_binding)
        _cleanup_active_install_intents(handle, active_document)
        _assert_directory_binding(resolved, root_binding)
        report = _verify_installation_locked(resolved, handle)
        report["concurrency_guarded"] = True
        report["lifecycle_compatibility"] = "v1-proposal-bound"
        return report


def uninstall_installation(destination: Path, *, digest: str) -> dict[str, Any]:
    root = destination.resolve()
    if destination.is_symlink() or not root.is_dir():
        raise HostLifecycleError("host installation destination is missing or symbolic")
    lock_path = root / INSTALL_LOCK_RELATIVE
    tombstone_path = root / UNINSTALL_TOMBSTONE_RELATIVE
    if lock_path.exists() or lock_path.is_symlink():
        initial_lock = _load_install_lock(root)
        if initial_lock["schema_version"] == "1.0.0":
            raise HostLifecycleError(
                "legacy v0.9 install records lack proposal-bound ownership; "
                "destructive uninstall is disabled and requires manual reconciliation"
            )
    elif not tombstone_path.exists() and not tombstone_path.is_symlink():
        raise HostLifecycleError("host installation lock is missing")

    with _operation_lock(root, create=False) as operation:
        handle = operation["root_fd"]
        root_binding = operation["root_binding"]
        guard_binding = operation["guard_binding"]
        _assert_directory_binding(root, root_binding)
        if not _relative_present(handle, INSTALL_LOCK_RELATIVE):
            if not _relative_present(handle, UNINSTALL_TOMBSTONE_RELATIVE):
                raise HostLifecycleError("host installation lock is missing")
            tombstone = _load_uninstall_tombstone(root, handle)
            if digest != tombstone["proposal_digest"]:
                raise HostLifecycleError(
                    "uninstall digest does not match the completed host uninstall"
                )
            return {
                "status": "ALREADY_UNINSTALLED",
                "team_id": tombstone["team_id"],
                "host": tombstone["host"],
                "destination": str(root),
                "proposal_digest": digest,
                "removed_files": tombstone["removed_files"],
                "preserved_unmanaged_content": True,
                "directories_removed": False,
                "concurrency_guarded": True,
                "lifecycle": _lifecycle_contract(root),
            }

        lock = _load_install_lock(root, handle)
        if lock["schema_version"] == "1.0.0":
            raise HostLifecycleError(
                "legacy v0.9 install records lack proposal-bound ownership; destructive uninstall is disabled"
            )
        if lock["guard_binding"] != guard_binding:
            raise HostLifecycleError("host lifecycle guard differs from the install authority")
        if digest != lock["proposal_digest"]:
            raise HostLifecycleError(
                "uninstall digest does not match the exact managed installation"
            )
        if lock["status"] == "ACTIVE":
            # A crash while publishing ACTIVE -> UNINSTALLING can leave the
            # declared fixed metadata scratch file while the authoritative
            # lock is still ACTIVE.  Ordinary verify rejects that residue;
            # this exact digest-bound mutation may rebuild and consume it.
            _verify_installation_locked(
                root,
                handle,
                allow_metadata_recovery_stage=True,
            )
            active_digest = _sha256_bytes(_canonical(lock).encode("utf-8"))
            lock = dict(lock)
            lock["status"] = "UNINSTALLING"
            _assert_directory_binding(root, root_binding)
            _atomic_json_relative(
                handle,
                INSTALL_LOCK_RELATIVE,
                lock,
                expected_current_digest=active_digest,
                intent_relative=lock["proposal"]["lifecycle"]["metadata_recovery_intent"],
                allow_existing_intent=True,
            )
        elif lock["status"] != "UNINSTALLING":
            raise HostLifecycleError("host installation is not uninstallable in its current state")

        expected_tombstone = _tombstone_document(lock)
        tombstone_present = _relative_present(handle, UNINSTALL_TOMBSTONE_RELATIVE)
        if tombstone_present:
            existing_tombstone = _load_uninstall_tombstone(root, handle)
            if existing_tombstone != expected_tombstone:
                raise HostLifecycleError("host uninstall tombstone differs from this installation")

        removed_now = 0
        for record_index, record in enumerate(lock["files"]):
            if record["state"] == "REMOVED":
                if _relative_present(handle, record["stage_path"]):
                    _unlink_bound_relative(
                        handle,
                        record["stage_path"],
                        record["sha256"],
                        allow_missing=False,
                        expected_binding=record["binding"],
                    )
                continue
            _assert_directory_binding(root, root_binding)
            if record["state"] == "PRESENT":
                _quarantine_bound_relative(
                    handle,
                    record["path"],
                    record["stage_path"],
                    record["binding"],
                )
                before_digest = _sha256_bytes(_canonical(lock).encode("utf-8"))
                record = {**record, "state": "QUARANTINED"}
                lock["files"][record_index] = record
                _atomic_json_relative(
                    handle,
                    INSTALL_LOCK_RELATIVE,
                    lock,
                    expected_current_digest=before_digest,
                    intent_relative=lock["proposal"]["lifecycle"]["metadata_recovery_intent"],
                    allow_existing_intent=True,
                )
            if record["state"] != "QUARANTINED":
                raise HostLifecycleError("managed host file removal state is invalid")
            target_removed = False
            if _relative_present(handle, record["path"]):
                metadata = _relative_stat(handle, record["path"])
                if metadata is not None and _metadata_matches_binding(
                    metadata,
                    record["binding"],
                ):
                    _unlink_bound_relative(
                        handle,
                        record["path"],
                        record["sha256"],
                        allow_missing=False,
                        expected_binding=record["binding"],
                    )
                    target_removed = True
            elif not _relative_present(handle, record["stage_path"]):
                raise HostLifecycleError(
                    "managed quarantine file is missing: " + record["stage_path"]
                )
            before_digest = _sha256_bytes(_canonical(lock).encode("utf-8"))
            record = {**record, "state": "REMOVED"}
            lock["files"][record_index] = record
            _atomic_json_relative(
                handle,
                INSTALL_LOCK_RELATIVE,
                lock,
                expected_current_digest=before_digest,
                intent_relative=lock["proposal"]["lifecycle"]["metadata_recovery_intent"],
                allow_existing_intent=True,
            )
            _unlink_bound_relative(
                handle,
                record["stage_path"],
                record["sha256"],
                allow_missing=False,
                expected_binding=record["binding"],
            )
            removed_now += int(target_removed)
        # Run the tombstone transition even when the desired tombstone already
        # exists.  The atomic helper then removes any declared metadata stage
        # left by a crash before install-lock removal.  An unsafe stage (for
        # example a symlink) still fails closed.
        _assert_directory_binding(root, root_binding)
        _atomic_json_relative(
            handle,
            UNINSTALL_TOMBSTONE_RELATIVE,
            expected_tombstone,
            expected_current_digest=None,
            intent_relative=lock["proposal"]["lifecycle"]["metadata_recovery_intent"],
            allow_existing_intent=True,
        )
        _assert_directory_binding(root, root_binding)
        _unlink_bound_relative(
            handle,
            INSTALL_LOCK_RELATIVE,
            _sha256_bytes(_canonical(lock).encode("utf-8")),
            allow_missing=False,
        )
        _assert_directory_binding(root, root_binding)
        return {
            "status": "UNINSTALLED",
            "team_id": lock["team_id"],
            "host": lock["host"],
            "destination": str(root),
            "proposal_digest": digest,
            "removed_files": len(lock["files"]),
            "removed_in_this_run": removed_now,
            "preserved_unmanaged_content": True,
            "directories_removed": False,
            "concurrency_guarded": True,
            "lifecycle": _lifecycle_contract(root),
        }
