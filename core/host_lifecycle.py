"""Plan and apply non-overwriting, reversible host-native team file projections."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from core.context_team import ContextTeamError, DESIGN_RELATIVE, LOCK_RELATIVE, inspect_context_team
from core.json_support import loads_strict
from core.schema_validation import validate_schema
from core.security import find_inline_secret

ROOT = Path(__file__).resolve().parents[1]
PLAN_SCHEMA = ROOT / "schemas" / "host-install-plan.schema.json"
LOCK_SCHEMA = ROOT / "schemas" / "host-install-lock.schema.json"
INSTALL_LOCK_RELATIVE = ".agent-team/host-install.lock.json"
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


class HostLifecycleError(ValueError):
    """Raised when a host installation lifecycle operation is unsafe or invalid."""


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


def _load_object(path: Path, label: str) -> dict[str, Any]:
    if path.is_symlink():
        raise HostLifecycleError(f"{label} must not be a symbolic link: {path}")
    try:
        value = loads_strict(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
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
    return bool(value) and not path.is_absolute() and ".." not in path.parts and value == path.as_posix()


def _symlink_component(root: Path, relative: str) -> Path | None:
    current = root
    for component in Path(relative).parts:
        current = current / component
        if current.is_symlink():
            return current
    return None


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
    except Exception:
        if temporary.exists():
            temporary.unlink()
        raise


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
    paths = [record["path"] for record in records]
    if len(paths) != len(set(paths)):
        raise HostLifecycleError("compiled host projection contains duplicate destination paths")
    return sorted(records, key=lambda item: item["path"])


def build_install_plan(team: Path, host_id: str, destination: Path) -> dict[str, Any]:
    team_root = team.resolve()
    summary = inspect_context_team(team_root)
    design = _load_object(team_root / DESIGN_RELATIVE, "team design")
    if host_id not in design["platform_targets"]:
        raise HostLifecycleError(f"team was not compiled for host {host_id}")
    descriptor = _host_descriptor(host_id)
    target = destination.resolve()
    if destination.is_symlink() or target == Path(target.anchor):
        raise HostLifecycleError("host destination must be a non-root, non-symbolic-link path")
    if target == team_root or team_root in target.parents:
        raise HostLifecycleError("host destination must be outside the authoritative team")
    if target == ROOT or ROOT in target.parents:
        raise HostLifecycleError("host destination must be outside the Factory repository")
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
        "destination": str(target),
        "files": _source_records(team_root, host_id),
        "effects": {
            "filesystem_writes": True,
            "external_writes": False,
            "bindings_created": False,
            "tasks_started": False,
            "credentials_read": False,
        },
        "limitations": [
            "Apply creates only previously absent files listed in this proposal.",
            "Apply does not edit live host configuration, authenticate, bind channels, start tasks, or call external APIs.",
            "Host object import or runtime activation remains a separate host-specific, explicitly authorized operation.",
        ],
    }
    plan = {
        "schema_version": "1.0.0",
        "state": "DRAFT",
        "proposal": proposal,
        "proposal_digest": _digest(proposal),
        "confirmation": None,
    }
    validate_install_plan(plan)
    return plan


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
    destination = Path(plan["proposal"]["destination"])
    if not destination.is_absolute() or destination == Path(destination.anchor):
        raise HostLifecycleError("host installation destination must be an absolute non-root path")
    seen: set[str] = set()
    for record in plan["proposal"]["files"]:
        relative = record["path"]
        source = record["source"]
        if not _safe_relative(relative) or not _safe_relative(source):
            raise HostLifecycleError("host installation file paths must be safe relative paths")
        if relative == INSTALL_LOCK_RELATIVE or relative in seen:
            raise HostLifecycleError("host installation file path is reserved or duplicated")
        seen.add(relative)
        if find_inline_secret(relative) or find_inline_secret(source):
            raise HostLifecycleError("host installation plan contains a credential-like path")
    if find_inline_secret(_canonical(plan)):
        raise HostLifecycleError("host installation plan contains a credential-like value")


def write_install_plan(plan: dict[str, Any], path: Path) -> None:
    validate_install_plan(plan)
    target = path.resolve()
    if path.is_symlink() or target.exists():
        raise HostLifecycleError("host installation plan output already exists")
    _atomic_json(target, plan)


def load_install_plan(path: Path) -> dict[str, Any]:
    plan = _load_object(path.resolve(), "host installation plan")
    validate_install_plan(plan)
    return plan


def preview_install_plan(plan: dict[str, Any]) -> str:
    validate_install_plan(plan)
    proposal = plan["proposal"]
    lines = [
        "# Host-native team installation proposal",
        "",
        f"State: `{plan['state']}`",
        f"Exact proposal digest: `{plan['proposal_digest']}`",
        f"Team: `{proposal['team']['team_id']}`",
        f"Team design digest: `{proposal['team']['design_digest']}`",
        f"Team lock digest: `{proposal['team']['lock_digest']}`",
        f"Host: `{proposal['host']['id']}` (`{proposal['host']['support_tier']}`)",
        f"Host descriptor schema: `{proposal['host']['descriptor_version']}`",
        f"Host descriptor digest: `{proposal['host']['descriptor_digest']}`",
        f"Destination: `{proposal['destination']}`",
        f"Factory-managed files to create: `{len(proposal['files'])}`",
        "",
        "## Exact managed files",
        "",
    ]
    lines.extend(
        f"- `{record['path']}` ← `{record['source']}` ({record['sha256']})"
        for record in proposal["files"]
    )
    lines.extend(
        [
            "",
            "## Effects",
            "",
            f"- Filesystem writes: `{str(proposal['effects']['filesystem_writes']).lower()}`",
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
            "Existing files are never overwritten. Confirm this exact digest before applying.",
            "",
        ]
    )
    return "\n".join(lines)


def confirm_install_plan(path: Path, *, digest: str, approved_by: str) -> dict[str, Any]:
    target = path.resolve()
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
        "scope": "create-factory-managed-host-files-only",
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
    if _sha256_bytes((team_root / DESIGN_RELATIVE).read_bytes()) != proposal["team"]["design_digest"]:
        raise HostLifecycleError("team design changed after host installation planning")
    if _sha256_bytes((team_root / LOCK_RELATIVE).read_bytes()) != proposal["team"]["lock_digest"]:
        raise HostLifecycleError("team lock changed after host installation planning")
    for record in proposal["files"]:
        source = team_root / record["source"]
        if _symlink_component(team_root, record["source"]) is not None or not source.is_file():
            raise HostLifecycleError(f"planned source is missing or unsafe: {record['source']}")
        if _sha256_bytes(source.read_bytes()) != record["sha256"]:
            raise HostLifecycleError(f"planned source changed: {record['source']}")
    return team_root


def _lock_document(plan: dict[str, Any], status: str) -> dict[str, Any]:
    proposal = plan["proposal"]
    return {
        "schema_version": "1.0.0",
        "status": status,
        "team_id": proposal["team"]["team_id"],
        "host": proposal["host"]["id"],
        "proposal_digest": plan["proposal_digest"],
        "destination": proposal["destination"],
        "files": [
            {"path": record["path"], "sha256": record["sha256"]}
            for record in proposal["files"]
        ],
    }


def _copy_exclusive(source: Path, target: Path) -> None:
    """Publish one complete file without ever replacing an existing path."""

    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{target.name}.host-stage-", dir=target.parent)
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o644)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(source.read_bytes())
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary, target)
    finally:
        if temporary.exists():
            temporary.unlink()


def _load_install_lock(destination: Path) -> dict[str, Any]:
    lock = _load_object(destination / INSTALL_LOCK_RELATIVE, "host installation lock")
    findings = validate_schema(lock, _load_schema(LOCK_SCHEMA))
    if findings:
        raise HostLifecycleError(
            "invalid host installation lock: "
            + "; ".join(f"{item.path}: {item.message}" for item in findings)
        )
    if Path(lock["destination"]) != destination:
        raise HostLifecycleError("host installation lock belongs to another destination")
    return lock


def verify_installation(destination: Path) -> dict[str, Any]:
    root = destination.resolve()
    if destination.is_symlink() or not root.is_dir():
        raise HostLifecycleError("host installation destination is missing or symbolic")
    lock = _load_install_lock(root)
    if lock["status"] != "ACTIVE":
        raise HostLifecycleError("host installation is incomplete")
    for record in lock["files"]:
        path = root / record["path"]
        if _symlink_component(root, record["path"]) is not None or not path.is_file():
            raise HostLifecycleError(f"managed host file is missing or unsafe: {record['path']}")
        if _sha256_bytes(path.read_bytes()) != record["sha256"]:
            raise HostLifecycleError(f"managed host file drifted: {record['path']}")
    return {
        "status": "VALID",
        "team_id": lock["team_id"],
        "host": lock["host"],
        "destination": str(root),
        "proposal_digest": lock["proposal_digest"],
        "managed_files": len(lock["files"]),
        "external_integrations_enabled": False,
    }


def apply_install_plan(path: Path) -> dict[str, Any]:
    plan = load_install_plan(path.resolve())
    if plan["state"] != "CONFIRMED":
        raise HostLifecycleError("preview and confirm the exact host plan before applying it")
    team_root = _validate_source(plan)
    destination = Path(plan["proposal"]["destination"])
    if destination.is_symlink():
        raise HostLifecycleError("host installation destination must not be symbolic")
    destination.mkdir(parents=True, exist_ok=True)
    destination = destination.resolve()
    lock_path = destination / INSTALL_LOCK_RELATIVE
    resuming = False
    if lock_path.exists() or lock_path.is_symlink():
        lock = _load_install_lock(destination)
        if lock["proposal_digest"] == plan["proposal_digest"] and lock["status"] == "ACTIVE":
            report = verify_installation(destination)
            report["status"] = "ALREADY_APPLIED"
            return report
        if lock["proposal_digest"] != plan["proposal_digest"] or lock["status"] != "APPLYING":
            raise HostLifecycleError(
                "destination is managed by another host installation or has an invalid lifecycle state"
            )
        if lock != _lock_document(plan, "APPLYING"):
            raise HostLifecycleError("incomplete host installation lock differs from this exact plan")
        resuming = True
    for record in plan["proposal"]["files"]:
        if _symlink_component(destination, record["path"]) is not None:
            raise HostLifecycleError(f"destination path crosses a symbolic link: {record['path']}")
        target = destination / record["path"]
        if target.exists() or target.is_symlink():
            if (
                resuming
                and target.is_file()
                and not target.is_symlink()
                and _sha256_bytes(target.read_bytes()) == record["sha256"]
            ):
                continue
            raise HostLifecycleError(f"host installation never overwrites: {record['path']}")

    if not resuming:
        _atomic_json(lock_path, _lock_document(plan, "APPLYING"))
    for record in plan["proposal"]["files"]:
        source = team_root / record["source"]
        target = destination / record["path"]
        if target.is_file() and _sha256_bytes(target.read_bytes()) == record["sha256"]:
            continue
        _copy_exclusive(source, target)
    _atomic_json(lock_path, _lock_document(plan, "ACTIVE"))
    return verify_installation(destination)


def uninstall_installation(destination: Path, *, digest: str) -> dict[str, Any]:
    root = destination.resolve()
    report = verify_installation(root)
    lock = _load_install_lock(root)
    if digest != lock["proposal_digest"]:
        raise HostLifecycleError("uninstall digest does not match the exact managed installation")
    paths = [root / record["path"] for record in lock["files"]]
    for path in paths:
        path.unlink()
    lock_path = root / INSTALL_LOCK_RELATIVE
    lock_path.unlink()
    directories = sorted(
        {parent for path in paths + [lock_path] for parent in path.parents if parent != root},
        key=lambda item: len(item.parts),
        reverse=True,
    )
    for directory in directories:
        try:
            directory.rmdir()
        except OSError:
            pass
    return {
        "status": "UNINSTALLED",
        "team_id": report["team_id"],
        "host": report["host"],
        "destination": str(root),
        "proposal_digest": digest,
        "removed_files": len(paths),
        "preserved_unmanaged_content": True,
    }
