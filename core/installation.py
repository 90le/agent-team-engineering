"""Atomic, provenance-bound installation of a Factory release."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from core.json_support import loads_strict
from core.schema_validation import validate_schema

ROOT = Path(__file__).resolve().parents[1]
INSTALLATION_NAME = ".factory-installation.json"
INSTALLATION_SCHEMA = ROOT / "schemas" / "factory-installation.schema.json"
SAFE_PATH = re.compile(r"^[A-Za-z0-9._/-]+$")
DERIVED_DIRECTORIES = frozenset(
    {".git", ".mypy_cache", ".pytest_cache", ".ruff_cache", "__pycache__"}
)
MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_TREE_BYTES = 100 * 1024 * 1024


class InstallationError(RuntimeError):
    """Raised when release provenance or installation integrity fails."""


def _strict_object(path: Path) -> dict[str, Any]:
    if path.is_symlink():
        raise InstallationError(f"JSON file must not be a symbolic link: {path}")
    try:
        value = loads_strict(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise InstallationError(f"cannot load JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise InstallationError(f"JSON root must be an object: {path}")
    return value


def _canonical(value: Any) -> str:
    try:
        return json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError) as exc:
        raise InstallationError(f"installation value is not strict JSON: {exc}") from exc


def _pretty(value: Any) -> bytes:
    try:
        return (
            json.dumps(
                value,
                allow_nan=False,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n"
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise InstallationError(f"installation value is not strict JSON: {exc}") from exc


def _digest(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _run_git(*arguments: str, binary: bool = False) -> bytes | str:
    environment = os.environ.copy()
    environment["GIT_OPTIONAL_LOCKS"] = "0"
    result = subprocess.run(
        ["git", "-C", str(ROOT), *arguments],
        check=False,
        capture_output=True,
        text=not binary,
        env=environment,
    )
    if result.returncode != 0:
        stderr = result.stderr.decode("utf-8", "replace") if binary else result.stderr
        raise InstallationError(f"Git command failed: {stderr.strip()}")
    return result.stdout


def _safe_relative(value: str) -> bool:
    path = Path(value)
    return (
        bool(value)
        and bool(SAFE_PATH.fullmatch(value))
        and not path.is_absolute()
        and ".." not in path.parts
        and not DERIVED_DIRECTORIES.intersection(path.parts)
        and value != INSTALLATION_NAME
    )


def _tree_digest(records: list[dict[str, Any]], contents: dict[str, bytes]) -> str:
    digest = hashlib.sha256()
    for record in sorted(records, key=lambda item: item["path"]):
        path = str(record["path"])
        digest.update(path.encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(record["mode"]).encode("ascii"))
        digest.update(b"\0")
        digest.update(contents[path])
        digest.update(b"\0")
    return "sha256:" + digest.hexdigest()


def _release_identity(version: str) -> tuple[str, str | None, bool]:
    revision = str(_run_git("rev-parse", "HEAD")).strip()
    if not re.fullmatch(r"[a-f0-9]{40}", revision):
        raise InstallationError("Git HEAD is not a full commit identity")
    status = str(_run_git("status", "--porcelain", "--untracked-files=all"))
    tag = f"v{version}"
    points_at = {
        line.strip()
        for line in str(_run_git("tag", "--points-at", "HEAD")).splitlines()
        if line.strip()
    }
    tag_type = str(_run_git("cat-file", "-t", f"refs/tags/{tag}")).strip() if tag in points_at else None
    verified = not status.strip() and tag in points_at and tag_type == "tag"
    return revision, tag if tag in points_at else None, verified


def _committed_source() -> tuple[list[dict[str, Any]], dict[str, bytes]]:
    raw = _run_git("ls-tree", "-r", "-z", "--full-tree", "HEAD", binary=True)
    assert isinstance(raw, bytes)
    records: list[dict[str, Any]] = []
    contents: dict[str, bytes] = {}
    total = 0
    for entry in raw.split(b"\0"):
        if not entry:
            continue
        header, encoded_path = entry.split(b"\t", 1)
        mode, object_type, _ = header.decode("ascii").split(" ", 2)
        relative = encoded_path.decode("utf-8")
        if object_type != "blob" or mode not in {"100644", "100755"}:
            raise InstallationError(f"unsupported Git object in release tree: {relative}")
        if not _safe_relative(relative):
            raise InstallationError(f"unsafe release path: {relative}")
        content = _run_git("show", f"HEAD:{relative}", binary=True)
        assert isinstance(content, bytes)
        if len(content) > MAX_FILE_BYTES:
            raise InstallationError(f"release file exceeds 10 MiB: {relative}")
        total += len(content)
        if total > MAX_TREE_BYTES:
            raise InstallationError("Factory release tree exceeds 100 MiB")
        record = {
            "path": relative,
            "sha256": _digest(content),
            "mode": 0o755 if mode == "100755" else 0o644,
            "size": len(content),
        }
        records.append(record)
        contents[relative] = content
    return sorted(records, key=lambda item: item["path"]), contents


def _development_source() -> tuple[list[dict[str, Any]], dict[str, bytes]]:
    records: list[dict[str, Any]] = []
    contents: dict[str, bytes] = {}
    total = 0
    for path in sorted(ROOT.rglob("*")):
        if not path.is_file() and not path.is_symlink():
            continue
        relative = path.relative_to(ROOT).as_posix()
        if DERIVED_DIRECTORIES.intersection(path.relative_to(ROOT).parts):
            continue
        if not _safe_relative(relative):
            raise InstallationError(f"unsafe development source path: {relative}")
        if path.is_symlink() or not stat.S_ISREG(path.stat().st_mode):
            raise InstallationError(f"development source is not a regular file: {relative}")
        content = path.read_bytes()
        if len(content) > MAX_FILE_BYTES:
            raise InstallationError(f"development file exceeds 10 MiB: {relative}")
        total += len(content)
        if total > MAX_TREE_BYTES:
            raise InstallationError("Factory development tree exceeds 100 MiB")
        mode = 0o755 if path.stat().st_mode & stat.S_IXUSR else 0o644
        record = {
            "path": relative,
            "sha256": _digest(content),
            "mode": mode,
            "size": len(content),
        }
        records.append(record)
        contents[relative] = content
    return records, contents


def build_installation_manifest(
    *, _allow_unreleased: bool = False
) -> tuple[dict[str, Any], dict[str, bytes]]:
    factory = _strict_object(ROOT / "factory-package.json")
    revision, tag, verified = _release_identity(str(factory["version"]))
    if not verified and not _allow_unreleased:
        raise InstallationError(
            f"Factory install requires a clean annotated v{factory['version']} release tag"
        )
    records, contents = (
        _committed_source() if verified else _development_source()
    )
    body: dict[str, Any] = {
        "schema_version": "1.0.0",
        "factory_id": factory["id"],
        "factory_version": factory["version"],
        "source_revision": revision,
        "source_tag": tag,
        "release_verified": verified,
        "tree_digest": _tree_digest(records, contents),
        "files": records,
    }
    manifest = {
        **body,
        "installation_id": "installation-"
        + hashlib.sha256(_canonical(body).encode("utf-8")).hexdigest()[:32],
    }
    schema = _strict_object(INSTALLATION_SCHEMA)
    issues = validate_schema(manifest, schema)
    if issues:
        details = "; ".join(f"{issue.path}: {issue.message}" for issue in issues)
        raise InstallationError(f"installation manifest violates schema: {details}")
    return manifest, contents


def _write_file(path: Path, content: bytes, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags, mode)
    try:
        os.fchmod(descriptor, mode)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        if path.exists() and not path.is_symlink():
            path.unlink()
        raise


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _fsync_tree_directories(root: Path) -> None:
    directories = [root, *(path for path in root.rglob("*") if path.is_dir())]
    for directory in sorted(directories, key=lambda item: len(item.parts), reverse=True):
        _fsync_directory(directory)


def verify_factory_installation(root: Path) -> dict[str, Any]:
    if root.is_symlink():
        raise InstallationError("Factory installation root must not be a symbolic link")
    installation = root.resolve()
    if not installation.is_dir():
        raise InstallationError(f"Factory installation does not exist: {installation}")
    manifest = _strict_object(installation / INSTALLATION_NAME)
    if stat.S_IMODE((installation / INSTALLATION_NAME).stat().st_mode) != 0o644:
        raise InstallationError("installation manifest permissions must be 0644")
    schema = _strict_object(INSTALLATION_SCHEMA)
    issues = validate_schema(manifest, schema)
    if issues:
        details = "; ".join(f"{issue.path}: {issue.message}" for issue in issues)
        raise InstallationError(f"installation manifest violates schema: {details}")
    body = {key: value for key, value in manifest.items() if key != "installation_id"}
    expected_id = "installation-" + hashlib.sha256(
        _canonical(body).encode("utf-8")
    ).hexdigest()[:32]
    if manifest["installation_id"] != expected_id:
        raise InstallationError("installation identity differs from its manifest")
    factory = _strict_object(installation / "factory-package.json")
    if (
        factory.get("id") != manifest["factory_id"]
        or factory.get("version") != manifest["factory_version"]
    ):
        raise InstallationError("installed Factory identity differs from its manifest")

    seen: set[str] = set()
    records: list[dict[str, Any]] = []
    contents: dict[str, bytes] = {}
    total = 0
    expected_paths = {INSTALLATION_NAME}
    for record in manifest["files"]:
        relative = str(record["path"])
        if relative in seen:
            raise InstallationError(f"installation manifest duplicates path: {relative}")
        seen.add(relative)
        if not _safe_relative(relative):
            raise InstallationError(f"installation manifest has unsafe path: {relative}")
        target = installation / relative
        if target.is_symlink():
            raise InstallationError(f"installed file is a symbolic link: {relative}")
        try:
            metadata = target.stat()
        except FileNotFoundError as exc:
            raise InstallationError(f"installed file is missing: {relative}") from exc
        if not stat.S_ISREG(metadata.st_mode):
            raise InstallationError(f"installed path is not a regular file: {relative}")
        content = target.read_bytes()
        total += len(content)
        if total > MAX_TREE_BYTES:
            raise InstallationError("installed Factory exceeds 100 MiB")
        if (
            len(content) != record["size"]
            or _digest(content) != record["sha256"]
            or stat.S_IMODE(metadata.st_mode) != record["mode"]
        ):
            raise InstallationError(f"installed file metadata differs: {relative}")
        records.append(record)
        contents[relative] = content
        expected_paths.add(relative)
    if _tree_digest(records, contents) != manifest["tree_digest"]:
        raise InstallationError("installed Factory tree digest differs")
    actual_paths: set[str] = set()
    for path in installation.rglob("*"):
        relative_path = path.relative_to(installation)
        if path.is_symlink():
            raise InstallationError(
                f"Factory installation contains a symbolic link: {relative_path.as_posix()}"
            )
        if DERIVED_DIRECTORIES.intersection(relative_path.parts):
            raise InstallationError(
                "Factory installation contains an undeclared derived cache: "
                f"{relative_path.as_posix()}"
            )
        if path.is_file():
            actual_paths.add(relative_path.as_posix())
    if actual_paths != expected_paths:
        raise InstallationError("Factory installation contains undeclared files")
    return manifest


def current_source_release_verified() -> bool:
    installation_path = ROOT / INSTALLATION_NAME
    if installation_path.exists() or installation_path.is_symlink():
        try:
            return bool(verify_factory_installation(ROOT)["release_verified"])
        except InstallationError:
            return False
    try:
        factory = _strict_object(ROOT / "factory-package.json")
        return _release_identity(str(factory["version"]))[2]
    except InstallationError:
        return False


def install_factory(
    output: Path, *, _allow_unreleased: bool = False
) -> dict[str, Any]:
    destination = output.resolve()
    if destination == ROOT or ROOT in destination.parents:
        raise InstallationError("Factory installation must be outside the source repository")
    if destination.exists() or output.is_symlink():
        raise InstallationError(f"installation output already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    manifest, contents = build_installation_manifest(_allow_unreleased=_allow_unreleased)
    stage = Path(
        tempfile.mkdtemp(prefix=f".{destination.name}.install-", dir=destination.parent)
    )
    try:
        for record in manifest["files"]:
            relative = str(record["path"])
            _write_file(stage / relative, contents[relative], int(record["mode"]))
        _write_file(stage / INSTALLATION_NAME, _pretty(manifest), 0o644)
        _fsync_tree_directories(stage)
        verify_factory_installation(stage)
        from core.validation import validate_repository

        errors = [
            finding
            for finding in validate_repository(stage)
            if finding.severity == "ERROR"
        ]
        if errors:
            details = "; ".join(f"{finding.path}: {finding.message}" for finding in errors)
            raise InstallationError(f"installed Factory failed repository validation: {details}")
        if destination.exists():
            raise InstallationError(f"installation output appeared during publication: {destination}")
        os.replace(stage, destination)
        _fsync_directory(destination.parent)
    except Exception:
        if stage.exists():
            shutil.rmtree(stage)
        raise
    verified = verify_factory_installation(destination)
    return {
        "status": "INSTALLED",
        "root": str(destination),
        "installation_id": verified["installation_id"],
        "factory_id": verified["factory_id"],
        "factory_version": verified["factory_version"],
        "source_revision": verified["source_revision"],
        "source_tag": verified["source_tag"],
        "release_verified": verified["release_verified"],
        "tree_digest": verified["tree_digest"],
        "files": len(verified["files"]),
    }
