"""Plan and apply non-overwriting, reversible host-native team file projections."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import tempfile
import unicodedata
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
) -> dict[str, Any]:
    return {
        **_lifecycle_contract(destination),
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
) -> None:
    """Crash-recoverable JSON publication through one bound root descriptor."""

    content = _canonical(value).encode("utf-8")
    desired_digest = _sha256_bytes(content)
    with _parent_directory_fd(root, relative, create=True) as (parent, name):
        stage_path = Path(METADATA_STAGE_RELATIVE)
        if Path(relative).parent != stage_path.parent:
            raise HostLifecycleError(
                "host lifecycle JSON target must share the declared recovery-stage directory"
            )
        stage_name = stage_path.name

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
        if current is not None and _sha256_bytes(current[0]) == desired_digest:
            if stage is not None:
                stage_now = os.stat(stage_name, dir_fd=parent, follow_symlinks=False)
                if (stage_now.st_dev, stage_now.st_ino) != (
                    stage[1].st_dev,
                    stage[1].st_ino,
                ):
                    raise HostLifecycleError(
                        f"host lifecycle JSON recovery stage changed: {relative}"
                    )
                os.unlink(stage_name, dir_fd=parent)
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

        if stage is not None and _sha256_bytes(stage[0]) != desired_digest:
            stage_now = os.stat(stage_name, dir_fd=parent, follow_symlinks=False)
            if (stage_now.st_dev, stage_now.st_ino) != (
                stage[1].st_dev,
                stage[1].st_ino,
            ):
                raise HostLifecycleError(
                    f"host lifecycle JSON recovery stage changed: {relative}"
                )
            os.unlink(stage_name, dir_fd=parent)
            os.fsync(parent)
            stage = None
        if stage is None:
            descriptor = os.open(
                stage_name,
                os.O_WRONLY
                | os.O_CREAT
                | os.O_EXCL
                | getattr(os, "O_NOFOLLOW", 0)
                | getattr(os, "O_CLOEXEC", 0),
                0o644,
                dir_fd=parent,
            )
            try:
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
            os.fsync(parent)
        os.replace(
            stage_name,
            name,
            src_dir_fd=parent,
            dst_dir_fd=parent,
        )
        os.fsync(parent)


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
            "The declared metadata recovery stage is transient scratch: apply or uninstall may replace or remove it, and success requires it to be absent.",
            "Uninstall retains the empty operation guard and digest-bound tombstone so concurrent operations and replay remain fail-closed.",
            "Uninstall removes no directories because the file-only ownership record cannot prove who created an empty parent directory.",
            "The kernel lock serializes cooperating local Factory processes; hostile privileged filesystem mutation is outside this boundary.",
            "Apply does not edit live host configuration, authenticate, bind channels, start tasks, or call external APIs.",
            "Host object import or runtime activation remains a separate host-specific, explicitly authorized operation.",
        ],
    }
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
    if lifecycle != _proposal_lifecycle_contract(
        destination=destination,
        prior_guard=lifecycle["expected_prior_guard"],
        prior_tombstone=lifecycle["expected_prior_uninstall_tombstone"],
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
        if (
            not _safe_relative(relative)
            or not _safe_relative(source)
            or not _safe_relative(stage_path)
        ):
            raise HostLifecycleError("host installation file paths must be safe relative paths")
        if relative in RESERVED_DESTINATIONS or relative in seen:
            raise HostLifecycleError("host installation file path is reserved or duplicated")
        if (
            stage_path in RESERVED_DESTINATIONS
            or stage_path in seen
            or stage_path in stages
            or stage_path != _stage_relative(relative, record["sha256"])
        ):
            raise HostLifecycleError("host installation stage path is reserved or inconsistent")
        seen.add(relative)
        stages.add(stage_path)
        if (
            find_inline_secret(relative)
            or find_inline_secret(source)
            or find_inline_secret(stage_path)
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
        f"- `{record['path']}` ← `{record['source']}` ({record['sha256']}; recovery stage `{record['stage_path']}`)"
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
            "Projected files are never overwritten. Apply manages the declared transient metadata stage and may additionally delete only the exact prior tombstone shown above.",
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
            {"path": record["path"], "sha256": record["sha256"]}
            for record in proposal["files"]
        ],
    }


def _copy_exclusive(
    source_root: Path,
    source_relative: str,
    destination_root: RootHandle,
    target_relative: str,
    stage_relative: str,
    expected_digest: str,
    *,
    resuming: bool,
) -> None:
    """Publish exact bytes through a deterministic, crash-recoverable stage."""

    content, _ = _read_bound_relative(
        source_root,
        source_relative,
        expected_digest,
        label="planned source",
    )
    target = Path(target_relative)
    stage = Path(stage_relative)
    if target.parent != stage.parent or stage_relative != _stage_relative(
        target_relative, expected_digest
    ):
        raise HostLifecycleError("host installation stage path differs from the exact plan")
    with _parent_directory_fd(destination_root, target_relative, create=True) as (parent, name):
        stage_name = stage.name
        flags = (
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0)
        )
        stage_ready = False
        try:
            existing = os.open(
                stage_name,
                _nonblocking_read_flags(),
                dir_fd=parent,
            )
        except FileNotFoundError:
            existing = None
        except OSError as exc:
            raise HostLifecycleError(f"host recovery stage is unsafe: {stage_relative}: {exc}") from exc
        if existing is not None:
            try:
                metadata = os.fstat(existing)
                if not stat.S_ISREG(metadata.st_mode):
                    raise HostLifecycleError(
                        f"host recovery stage is not a regular file: {stage_relative}"
                    )
                existing_content = _read_descriptor_bytes(existing)
                if not resuming:
                    raise HostLifecycleError(
                        f"host installation never overwrites a recovery stage: {stage_relative}"
                    )
                if _sha256_bytes(existing_content) == expected_digest:
                    stage_ready = True
                else:
                    # An exact APPLYING lock proves this stage path was absent at
                    # preflight and was reserved by this proposal. Recheck the
                    # open inode immediately before removing a torn write.
                    current = os.stat(stage_name, dir_fd=parent, follow_symlinks=False)
                    if (current.st_dev, current.st_ino) != (
                        metadata.st_dev,
                        metadata.st_ino,
                    ):
                        raise HostLifecycleError(
                            f"host recovery stage identity changed: {stage_relative}"
                        )
                    os.unlink(stage_name, dir_fd=parent)
                    os.fsync(parent)
            finally:
                os.close(existing)
        if not stage_ready:
            descriptor = os.open(stage_name, flags, 0o644, dir_fd=parent)
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.fsync(parent)

        try:
            target_descriptor = os.open(
                name,
                _nonblocking_read_flags(),
                dir_fd=parent,
            )
        except FileNotFoundError:
            target_descriptor = None
        except OSError as exc:
            raise HostLifecycleError(
                f"host installation target is unsafe: {target_relative}: {exc}"
            ) from exc
        if target_descriptor is not None:
            try:
                metadata = os.fstat(target_descriptor)
                if not stat.S_ISREG(metadata.st_mode):
                    raise HostLifecycleError(
                        f"host installation target is unsafe: {target_relative}"
                    )
                target_content = _read_descriptor_bytes(target_descriptor)
                if not resuming or _sha256_bytes(target_content) != expected_digest:
                    raise HostLifecycleError(
                        f"host installation never overwrites: {target_relative}"
                    )
            finally:
                os.close(target_descriptor)
        else:
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
        stage_content, stage_metadata = _read_regular_relative(
            destination_root,
            stage_relative,
            label="host recovery stage",
        )
        if _sha256_bytes(stage_content) != expected_digest:
            raise HostLifecycleError(f"host recovery stage drifted: {stage_relative}")
        current_stage = os.stat(stage_name, dir_fd=parent, follow_symlinks=False)
        if (current_stage.st_dev, current_stage.st_ino) != (
            stage_metadata.st_dev,
            stage_metadata.st_ino,
        ):
            raise HostLifecycleError(f"host recovery stage identity changed: {stage_relative}")
        os.unlink(stage_name, dir_fd=parent)
        os.fsync(parent)


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
            {"path": record["path"], "sha256": record["sha256"]}
            for record in proposal["files"]
        ]
        if lock["files"] != expected_files:
            raise HostLifecycleError("host installation lock files differ from its authority proposal")
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
        _read_bound_relative(
            handle,
            record["path"],
            record["sha256"],
            label="managed host file",
        )
    if not legacy:
        for record in lock["proposal"]["files"]:
            if _relative_present(handle, record["stage_path"]):
                raise HostLifecycleError(
                    f"active host installation retains a recovery stage: {record['stage_path']}"
                )
        metadata_recovery_stage_present = _relative_present(
            handle, METADATA_STAGE_RELATIVE
        )
        if metadata_recovery_stage_present and not allow_metadata_recovery_stage:
            raise HostLifecycleError(
                "active host installation retains the metadata recovery stage"
            )
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
        if lock["status"] == "ACTIVE":
            _verify_installation_locked(
                root,
                handle,
                allow_metadata_recovery_stage=True,
            )
        elif lock["status"] == "UNINSTALLING":
            for record in lock["files"]:
                if _relative_present(handle, record["path"]):
                    _read_bound_relative(
                        handle,
                        record["path"],
                        record["sha256"],
                        label="remaining managed host file",
                    )
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
            "filesystem_deletes": [
                record["path"] for record in lock["files"]
            ]
            + [INSTALL_LOCK_RELATIVE, METADATA_STAGE_RELATIVE],
            "filesystem_creates": [
                UNINSTALL_TOMBSTONE_RELATIVE,
                METADATA_STAGE_RELATIVE,
            ],
            "transient_files": [METADATA_STAGE_RELATIVE],
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
        if lock_present:
            lock = _load_install_lock(resolved, handle)
            if lock["schema_version"] == "1.0.0":
                raise HostLifecycleError(
                    "destination has a legacy unbound install record; reconcile it before v1 apply"
                )
            if lock["guard_binding"] != guard_binding:
                raise HostLifecycleError("host lifecycle guard differs from the install authority")
            if lock["proposal_digest"] == plan["proposal_digest"] and lock["status"] == "ACTIVE":
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

        if not resuming:
            _assert_directory_binding(resolved, root_binding)
            _atomic_json_relative(
                handle,
                INSTALL_LOCK_RELATIVE,
                _lock_document(plan, "APPLYING", guard_binding),
                expected_current_digest=None,
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
                record["sha256"],
                resuming=resuming,
            )
            _assert_directory_binding(resolved, root_binding)
        applying_document = _lock_document(plan, "APPLYING", guard_binding)
        _atomic_json_relative(
            handle,
            INSTALL_LOCK_RELATIVE,
            _lock_document(plan, "ACTIVE", guard_binding),
            expected_current_digest=_sha256_bytes(
                _canonical(applying_document).encode("utf-8")
            ),
        )
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
        for record in lock["files"]:
            _assert_directory_binding(root, root_binding)
            removed_now += int(
                _unlink_bound_relative(
                    handle,
                    record["path"],
                    record["sha256"],
                    allow_missing=True,
                )
            )
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
