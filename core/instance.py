"""Safe, deterministic lifecycle for declarative Agent Team instances."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core.schema_validation import validate_schema

ROOT = Path(__file__).resolve().parents[1]
INSTANCE_SCHEMA = ROOT / "schemas" / "team-instance.schema.json"
LOCK_SCHEMA = ROOT / "schemas" / "team-instance-lock.schema.json"
FACTORY_PACKAGE = ROOT / "factory-package.json"
TEMPLATE_ROOT = ROOT / "templates" / "team-instance"

AUTONOMY_ORDER = {f"A{level}": level for level in range(6)}
FACTORY_MAXIMUM_AUTONOMY = "A2"
SAFE_RELATIVE_PATH = re.compile(r"^[A-Za-z0-9._/-]+$")
SECRET_PATTERNS = (
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bAKIA[A-Z0-9]{16}\b"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{32,}\b"),
)
FORBIDDEN_SECRET_KEYS = {
    "access_key",
    "api_key",
    "client_secret",
    "password",
    "private_key",
    "secret_value",
    "token",
}
FORBIDDEN_RUNTIME_NAMES = {".env", "id_rsa", "id_ed25519"}
FORBIDDEN_RUNTIME_SUFFIXES = {".db", ".key", ".pem", ".sqlite", ".sqlite3"}


@dataclass(frozen=True)
class InstanceFinding:
    severity: str
    path: str
    message: str


class InstanceError(RuntimeError):
    pass


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _digest_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _digest_text(value: str) -> str:
    return _digest_bytes(value.encode("utf-8"))


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise InstanceError(f"required file does not exist: {path}") from exc
    except json.JSONDecodeError as exc:
        raise InstanceError(f"invalid JSON in {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise InstanceError(f"JSON root must be an object: {path}")
    return value


def _is_safe_relative(value: str) -> bool:
    path = Path(value)
    return (
        bool(value)
        and bool(SAFE_RELATIVE_PATH.fullmatch(value))
        and not path.is_absolute()
        and ".." not in path.parts
        and value not in {".", "./"}
    )


def _walk_values(value: Any, path: str = "$") -> list[tuple[str, str, Any]]:
    records: list[tuple[str, str, Any]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            records.append((child_path, str(key), child))
            records.extend(_walk_values(child, child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            records.extend(_walk_values(child, f"{path}[{index}]"))
    return records


def _is_secret_key(key: str) -> bool:
    normalized = key.casefold().replace("-", "_")
    return normalized in FORBIDDEN_SECRET_KEYS or any(
        normalized.endswith(suffix)
        for suffix in (
            "_access_key",
            "_api_key",
            "_client_secret",
            "_password",
            "_private_key",
            "_secret",
            "_token",
        )
    )


def validate_instance_document(document: dict[str, Any]) -> list[InstanceFinding]:
    schema = _load_json(INSTANCE_SCHEMA)
    findings = [
        InstanceFinding("ERROR", issue.path, issue.message)
        for issue in validate_schema(document, schema)
    ]
    if findings:
        return findings

    autonomy = document["autonomy"]
    initial = AUTONOMY_ORDER[autonomy["initial"]]
    maximum = AUTONOMY_ORDER[autonomy["maximum"]]
    if initial > maximum:
        findings.append(InstanceFinding("ERROR", "$.autonomy", "initial autonomy exceeds maximum"))
    if maximum > AUTONOMY_ORDER[FACTORY_MAXIMUM_AUTONOMY]:
        findings.append(
            InstanceFinding(
                "ERROR",
                "$.autonomy.maximum",
                f"Factory bootstrap cannot exceed {FACTORY_MAXIMUM_AUTONOMY}",
            )
        )
    if not autonomy["production_requires_human"]:
        findings.append(
            InstanceFinding(
                "ERROR",
                "$.autonomy.production_requires_human",
                "initial Factory instances require human production approval",
            )
        )

    supported_packs = {
        (team_pack["id"], team_pack["version"]) for team_pack in _factory_metadata()["team_packs"]
    }
    selected_pack = (document["team_pack"]["id"], document["team_pack"]["version"])
    if selected_pack not in supported_packs:
        findings.append(
            InstanceFinding(
                "ERROR",
                "$.team_pack",
                "selected team pack and version are not provided by this Factory release",
            )
        )

    owner_id = document["owner"]["id"]
    for gate in ("plan_approvers", "production_approvers"):
        if owner_id not in document["approvals"][gate]:
            findings.append(
                InstanceFinding(
                    "ERROR", f"$.approvals.{gate}", "instance owner must be an approver"
                )
            )

    project_ids = [project["id"] for project in document["projects"]]
    if len(project_ids) != len(set(project_ids)):
        findings.append(InstanceFinding("ERROR", "$.projects", "project ids must be unique"))
    adapter_slots = [adapter["slot"] for adapter in document["adapters"]]
    if len(adapter_slots) != len(set(adapter_slots)):
        findings.append(InstanceFinding("ERROR", "$.adapters", "adapter slots must be unique"))

    runtime = document["runtime"]
    for field in ("state_location", "workspace_root", "artifact_root"):
        if not _is_safe_relative(runtime[field]):
            findings.append(
                InstanceFinding("ERROR", f"$.runtime.{field}", "must be a safe relative path")
            )

    for value_path, key, value in _walk_values(document):
        if _is_secret_key(key):
            findings.append(
                InstanceFinding(
                    "ERROR",
                    value_path,
                    "inline secret field is forbidden; use secret_refs with an external identifier",
                )
            )
        if isinstance(value, str) and any(pattern.search(value) for pattern in SECRET_PATTERNS):
            findings.append(
                InstanceFinding("ERROR", value_path, "credential-like value is forbidden")
            )
    return findings


def _factory_metadata() -> dict[str, Any]:
    return _load_json(FACTORY_PACKAGE)


def _git_revision() -> tuple[str, bool]:
    revision = subprocess.run(
        ["git", "-C", str(ROOT), "rev-parse", "HEAD"],
        check=False,
        capture_output=True,
        text=True,
    )
    dirty = subprocess.run(
        ["git", "-C", str(ROOT), "status", "--porcelain", "--untracked-files=no"],
        check=False,
        capture_output=True,
        text=True,
    )
    if revision.returncode != 0:
        return "unavailable", True
    return revision.stdout.strip(), dirty.returncode != 0 or bool(dirty.stdout.strip())


def _contract_paths(metadata: dict[str, Any]) -> list[Path]:
    relatives = [
        "factory-package.json",
        "schemas/team-instance.schema.json",
        "schemas/team-instance-lock.schema.json",
    ]
    relatives.extend(metadata["contract_files"])
    relatives.extend(
        path.relative_to(ROOT).as_posix() for path in sorted(TEMPLATE_ROOT.rglob("*.template"))
    )
    return [ROOT / relative for relative in sorted(set(relatives))]


def factory_contract_digest() -> str:
    metadata = _factory_metadata()
    digest = hashlib.sha256()
    for path in _contract_paths(metadata):
        relative = path.relative_to(ROOT).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return f"sha256:{digest.hexdigest()}"


def _render_template(relative: str, values: dict[str, str]) -> str:
    content = (TEMPLATE_ROOT / relative).read_text(encoding="utf-8")
    for key, value in values.items():
        content = content.replace("{{" + key + "}}", value)
    unresolved = re.findall(r"\{\{[A-Z0-9_]+\}\}", content)
    if unresolved:
        raise InstanceError(
            f"unresolved template variables in {relative}: {sorted(set(unresolved))}"
        )
    return content


def _build_seed_files(document: dict[str, Any]) -> dict[str, tuple[str, str]]:
    metadata = _factory_metadata()
    values = {
        "INSTANCE_ID": document["instance_id"],
        "INSTANCE_NAME": document["display_name"],
        "FACTORY_ID": metadata["id"],
        "FACTORY_VERSION": metadata["version"],
        "TEAM_PACK_ID": document["team_pack"]["id"],
        "TEAM_PACK_VERSION": document["team_pack"]["version"],
    }
    return {
        "README.md": (_render_template("README.md.template", values), "seeded"),
        "AI-BOOTSTRAP.md": (_render_template("AI-BOOTSTRAP.md.template", values), "managed"),
        "AGENTS.md": (_render_template("AGENTS.md.template", values), "managed"),
        "CLAUDE.md": (_render_template("CLAUDE.md.template", values), "managed"),
        "AI-INSTRUCTIONS.md": (_render_template("AI-INSTRUCTIONS.md.template", values), "managed"),
        ".gitignore": (_render_template("gitignore.template", values), "seeded"),
        ".agent-team/README.md": (
            _render_template("agent-team-README.md.template", values),
            "managed",
        ),
        "docs/README.md": (_render_template("docs-README.md.template", values), "seeded"),
    }


def _build_lock(document: dict[str, Any], files: dict[str, tuple[str, str]]) -> dict[str, Any]:
    metadata = _factory_metadata()
    revision, dirty = _git_revision()
    records = [
        {"path": path, "ownership": ownership, "sha256": f"sha256:{_digest_text(content)}"}
        for path, (content, ownership) in sorted(files.items())
    ]
    return {
        "schema_version": "1.0.0",
        "instance_id": document["instance_id"],
        "factory": {
            "id": metadata["id"],
            "version": metadata["version"],
            "source_revision": revision,
            "source_dirty": dirty,
            "contract_digest": factory_contract_digest(),
        },
        "team_pack": document["team_pack"],
        "instance_digest": f"sha256:{_digest_text(_canonical_json(document))}",
        "files": records,
    }


def _write_text(root: Path, relative: str, content: str) -> None:
    target = root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def init_instance(config_path: Path, output: Path) -> dict[str, Any]:
    document = _load_json(config_path.resolve())
    findings = validate_instance_document(document)
    errors = [finding for finding in findings if finding.severity == "ERROR"]
    if errors:
        details = "; ".join(f"{finding.path}: {finding.message}" for finding in errors)
        raise InstanceError(f"instance configuration is invalid: {details}")

    destination = output.resolve()
    if (
        destination == Path(destination.anchor)
        or destination == ROOT
        or ROOT in destination.parents
    ):
        raise InstanceError(
            "instance output must be a new directory outside the Factory repository"
        )
    if destination.exists():
        raise InstanceError(
            "instance output already exists; initialization never overwrites a path"
        )
    destination.parent.mkdir(parents=True, exist_ok=True)

    stage = Path(tempfile.mkdtemp(prefix=f".{destination.name}.factory-", dir=destination.parent))
    try:
        files = _build_seed_files(document)
        for relative, (content, _) in files.items():
            _write_text(stage, relative, content)
        _write_text(stage, ".agent-team/instance.json", _canonical_json(document))
        lock = _build_lock(document, files)
        _write_text(stage, ".agent-team/instance.lock.json", _canonical_json(lock))
        validation = validate_instance_directory(stage)
        errors = [finding for finding in validation if finding.severity == "ERROR"]
        if errors:
            details = "; ".join(f"{finding.path}: {finding.message}" for finding in errors)
            raise InstanceError(f"generated instance failed validation: {details}")
        os.replace(stage, destination)
    except Exception:
        if stage.exists():
            shutil.rmtree(stage)
        raise

    return instance_summary(destination)


def _parse_version(value: str) -> tuple[int, int, int]:
    match = re.fullmatch(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)", value)
    if not match:
        raise ValueError(value)
    return tuple(int(part) for part in match.groups())


def validate_instance_directory(
    root: Path, *, allow_stale_instance_digest: bool = False
) -> list[InstanceFinding]:
    instance_root = root.resolve()
    findings: list[InstanceFinding] = []
    try:
        document = _load_json(instance_root / ".agent-team" / "instance.json")
        lock = _load_json(instance_root / ".agent-team" / "instance.lock.json")
    except InstanceError as exc:
        return [InstanceFinding("ERROR", str(instance_root), str(exc))]

    findings.extend(validate_instance_document(document))
    lock_schema = _load_json(LOCK_SCHEMA)
    findings.extend(
        InstanceFinding("ERROR", issue.path, issue.message)
        for issue in validate_schema(lock, lock_schema)
    )
    if any(finding.severity == "ERROR" for finding in findings):
        return findings

    metadata = _factory_metadata()
    if lock["instance_id"] != document["instance_id"]:
        findings.append(
            InstanceFinding(
                "ERROR",
                ".agent-team/instance.lock.json",
                "instance id differs from authority document",
            )
        )
    if lock["factory"]["id"] != metadata["id"]:
        findings.append(
            InstanceFinding(
                "ERROR", ".agent-team/instance.lock.json", "instance belongs to a different Factory"
            )
        )
    try:
        locked_version = _parse_version(lock["factory"]["version"])
        current_version = _parse_version(metadata["version"])
        if locked_version > current_version:
            findings.append(
                InstanceFinding(
                    "ERROR",
                    ".agent-team/instance.lock.json",
                    "instance was created by a newer Factory version",
                )
            )
        elif locked_version < current_version:
            findings.append(
                InstanceFinding(
                    "WARNING",
                    ".agent-team/instance.lock.json",
                    "instance has an available Factory upgrade",
                )
            )
        elif lock["factory"]["contract_digest"] != factory_contract_digest():
            findings.append(
                InstanceFinding(
                    "ERROR",
                    ".agent-team/instance.lock.json",
                    "Factory contract digest differs from the locked release",
                )
            )
    except ValueError:
        findings.append(
            InstanceFinding(
                "ERROR", ".agent-team/instance.lock.json", "invalid Factory semantic version"
            )
        )

    actual_instance_digest = f"sha256:{_digest_text(_canonical_json(document))}"
    if lock["instance_digest"] != actual_instance_digest and not allow_stale_instance_digest:
        findings.append(
            InstanceFinding(
                "ERROR",
                ".agent-team/instance.json",
                "validated configuration changed after locking; run `instance relock`",
            )
        )

    for record in lock["files"]:
        relative = record["path"]
        if not _is_safe_relative(relative):
            findings.append(InstanceFinding("ERROR", relative, "locked path is unsafe"))
            continue
        target = instance_root / relative
        if not target.is_file():
            severity = "ERROR" if record["ownership"] == "managed" else "WARNING"
            findings.append(InstanceFinding(severity, relative, "locked file is missing"))
            continue
        actual = f"sha256:{_digest_bytes(target.read_bytes())}"
        if actual != record["sha256"]:
            severity = "ERROR" if record["ownership"] == "managed" else "WARNING"
            message = (
                "Factory-managed file drifted"
                if severity == "ERROR"
                else "seeded file was customized"
            )
            findings.append(InstanceFinding(severity, relative, message))

    for path in sorted(item for item in instance_root.rglob("*") if item.is_file()):
        relative = path.relative_to(instance_root).as_posix()
        if ".git" in path.parts or "runtime" in path.parts:
            continue
        if (
            path.name in FORBIDDEN_RUNTIME_NAMES
            or path.suffix.casefold() in FORBIDDEN_RUNTIME_SUFFIXES
        ):
            findings.append(
                InstanceFinding(
                    "ERROR",
                    relative,
                    "secret or runtime file must not be committed to the instance repository",
                )
            )
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            findings.append(
                InstanceFinding(
                    "ERROR", relative, "binary file is not allowed in the instance repository"
                )
            )
            continue
        if any(pattern.search(content) for pattern in SECRET_PATTERNS):
            findings.append(
                InstanceFinding("ERROR", relative, "credential-like value is forbidden")
            )
    return findings


def relock_instance(root: Path) -> dict[str, Any]:
    instance_root = root.resolve()
    findings = validate_instance_directory(instance_root, allow_stale_instance_digest=True)
    errors = [finding for finding in findings if finding.severity == "ERROR"]
    if errors:
        details = "; ".join(f"{finding.path}: {finding.message}" for finding in errors)
        raise InstanceError(f"instance cannot be relocked: {details}")
    document = _load_json(instance_root / ".agent-team" / "instance.json")
    lock_path = instance_root / ".agent-team" / "instance.lock.json"
    lock = _load_json(lock_path)
    metadata = _factory_metadata()
    if lock["factory"]["version"] != metadata["version"]:
        raise InstanceError("instance must be upgraded to the current Factory before relocking")
    lock["instance_digest"] = f"sha256:{_digest_text(_canonical_json(document))}"
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".instance.lock.", suffix=".tmp", dir=lock_path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(_canonical_json(lock))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, lock_path)
    finally:
        if temporary.exists():
            temporary.unlink()
    return instance_summary(instance_root)


def instance_summary(root: Path) -> dict[str, Any]:
    instance_root = root.resolve()
    document = _load_json(instance_root / ".agent-team" / "instance.json")
    lock = _load_json(instance_root / ".agent-team" / "instance.lock.json")
    findings = validate_instance_directory(instance_root)
    return {
        "instance_id": document["instance_id"],
        "display_name": document["display_name"],
        "root": str(instance_root),
        "factory_version": lock["factory"]["version"],
        "factory_source_revision": lock["factory"]["source_revision"],
        "factory_source_dirty": lock["factory"]["source_dirty"],
        "factory_contract_digest": lock["factory"]["contract_digest"],
        "team_pack": document["team_pack"],
        "autonomy": document["autonomy"],
        "projects": len(document["projects"]),
        "enabled_adapters": sorted(
            adapter["slot"] for adapter in document["adapters"] if adapter["enabled"]
        ),
        "errors": sum(finding.severity == "ERROR" for finding in findings),
        "warnings": sum(finding.severity == "WARNING" for finding in findings),
    }
