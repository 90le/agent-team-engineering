"""Read-only diagnostics for a Factory source and optional team instance."""

from __future__ import annotations

import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Any

from core.control_plane import ControlPlane
from core.installation import INSTALLATION_NAME, InstallationError, verify_factory_installation
from core.instance import (
    _factory_metadata,
    _git_revision,
    _load_json,
    factory_contract_digest,
    validate_instance_directory,
)
from core.schema_validation import validate_schema
from core.validation import validate_repository

ROOT = Path(__file__).resolve().parents[1]
DOCTOR_SCHEMA = ROOT / "schemas" / "doctor-report.schema.json"
STATUS_ORDER = {"PASS": 0, "WARN": 1, "FAIL": 2}

try:
    import fcntl as _fcntl  # noqa: F401

    LIFECYCLE_LOCKING_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised on non-POSIX hosts
    LIFECYCLE_LOCKING_AVAILABLE = False


def _check(
    identifier: str,
    status: str,
    summary: str,
    remediation: str | None = None,
) -> dict[str, Any]:
    return {
        "id": identifier,
        "status": status,
        "summary": summary,
        "remediation": remediation,
    }


def _git_source(version: str) -> tuple[dict[str, Any], dict[str, Any]]:
    revision, dirty = _git_revision()
    tag = f"v{version}"
    tags = subprocess.run(
        ["git", "-C", str(ROOT), "tag", "--points-at", "HEAD"],
        check=False,
        capture_output=True,
        text=True,
    )
    tag_type = subprocess.run(
        ["git", "-C", str(ROOT), "cat-file", "-t", f"refs/tags/{tag}"],
        check=False,
        capture_output=True,
        text=True,
    )
    exact_release = (
        revision != "unavailable"
        and not dirty
        and tags.returncode == 0
        and tag in {line.strip() for line in tags.stdout.splitlines()}
        and tag_type.returncode == 0
        and tag_type.stdout.strip() == "tag"
    )
    source = {
        "mode": "git-worktree" if revision != "unavailable" else "unknown",
        "revision": revision if revision != "unavailable" else None,
        "dirty": dirty if revision != "unavailable" else None,
        "release_verified": exact_release,
        "tag": tag if exact_release else None,
    }
    if revision == "unavailable":
        check = _check(
            "source.identity",
            "FAIL",
            "Factory source has neither a valid Git identity nor an installation manifest.",
            "Restore a verified release clone or reinstall from an annotated release tag.",
        )
    elif dirty:
        check = _check(
            "source.identity",
            "WARN",
            "Factory Git worktree contains uncommitted changes.",
            "Use a clean reviewed commit before installing or upgrading an instance.",
        )
    elif exact_release:
        check = _check(
            "source.identity", "PASS", f"Factory is the clean annotated release {tag}."
        )
    else:
        check = _check(
            "source.identity",
            "WARN",
            "Factory is a clean Git commit but not the exact annotated release tag.",
            "Use an annotated semantic release tag for installation and production lifecycle work.",
        )
    return source, check


def _source_diagnostics(version: str) -> tuple[dict[str, Any], dict[str, Any]]:
    installation_path = ROOT / INSTALLATION_NAME
    if installation_path.exists() or installation_path.is_symlink():
        try:
            manifest = verify_factory_installation(ROOT)
        except InstallationError as exc:
            return (
                {
                    "mode": "installed-distribution",
                    "revision": None,
                    "dirty": True,
                    "release_verified": False,
                    "tag": None,
                },
                _check(
                    "source.identity",
                    "FAIL",
                    f"Factory installation integrity failed: {exc}",
                    "Stop lifecycle operations and reinstall from a verified release.",
                ),
            )
        status = "PASS" if manifest["release_verified"] else "WARN"
        remediation = (
            None
            if status == "PASS"
            else "Replace the development snapshot with an annotated release installation."
        )
        return (
            {
                "mode": "installed-distribution",
                "revision": manifest["source_revision"],
                "dirty": not manifest["release_verified"],
                "release_verified": bool(manifest["release_verified"]),
                "tag": manifest["source_tag"],
            },
            _check(
                "source.identity",
                status,
                "Factory installation manifest and every declared file are intact.",
                remediation,
            ),
        )
    return _git_source(version)


def _instance_diagnostics(instance_root: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    checks: list[dict[str, Any]] = []
    root = instance_root.resolve()
    findings = validate_instance_directory(instance_root)
    errors = [finding for finding in findings if finding.severity == "ERROR"]
    warnings = [finding for finding in findings if finding.severity == "WARNING"]
    if errors:
        checks.append(
            _check(
                "instance.validation",
                "FAIL",
                f"Instance validation has {len(errors)} error(s) and {len(warnings)} warning(s).",
                "Inspect instance validate output; do not relock or run until every error is resolved.",
            )
        )
    elif warnings:
        checks.append(
            _check(
                "instance.validation",
                "WARN",
                f"Instance is valid with {len(warnings)} warning(s).",
                "Review seeded customization and Factory upgrade warnings before the next change.",
            )
        )
    else:
        checks.append(_check("instance.validation", "PASS", "Instance validation is clean."))

    journal = root / "runtime" / ".factory-lifecycle-journal.json"
    if journal.exists() or journal.is_symlink():
        checks.append(
            _check(
                "instance.lifecycle-journal",
                "FAIL",
                "An interrupted instance lifecycle journal is present.",
                "Keep the runtime paused and run instance recover after verifying the recovery bundle.",
            )
        )
    else:
        checks.append(
            _check("instance.lifecycle-journal", "PASS", "No interrupted lifecycle journal exists.")
        )

    detail: dict[str, Any] = {
        "root": str(root),
        "errors": len(errors),
        "warnings": len(warnings),
        "factory_version": None,
        "upgrade_available": False,
        "runtime": {"state": "UNKNOWN"},
    }
    try:
        document = _load_json(root / ".agent-team" / "instance.json")
        lock = _load_json(root / ".agent-team" / "instance.lock.json")
        current_version = str(_factory_metadata()["version"])
        detail["instance_id"] = document["instance_id"]
        detail["factory_version"] = lock["factory"]["version"]
        detail["upgrade_available"] = lock["factory"]["version"] != current_version
        database = (root / document["runtime"]["state_location"]).resolve()
        if root not in database.parents:
            raise RuntimeError("runtime database escapes the instance")
        if database.exists():
            with ControlPlane(database, create=False) as control:
                audit = control.verify_audit()
                status = control.status()
            detail["runtime"] = {
                "state": "AVAILABLE",
                "paused": status["paused"],
                "active_leases": status["active_leases"],
                "outbox": status["outbox"],
                "audit_events": audit["events"],
                "audit_head": audit["head"],
            }
            checks.append(
                _check("instance.runtime-audit", "PASS", "Runtime database and audit chain verify.")
            )
        else:
            detail["runtime"] = {"state": "ABSENT"}
            checks.append(
                _check(
                    "instance.runtime-audit",
                    "WARN",
                    "Runtime database has not been initialized.",
                    "Initialize it only when this instance is ready to run.",
                )
            )
    except (KeyError, OSError, RuntimeError, sqlite3.Error, ValueError) as exc:
        detail["runtime"] = {"state": "INVALID"}
        checks.append(
            _check(
                "instance.runtime-audit",
                "FAIL",
                f"Instance authority or runtime audit cannot be verified: {exc}",
                "Keep the instance paused and restore authority/runtime from a verified recovery point.",
            )
        )
    return detail, checks


def build_doctor_report(instance: Path | None = None) -> dict[str, Any]:
    factory = _factory_metadata()
    checks: list[dict[str, Any]] = []
    python_ok = sys.version_info >= (3, 11)
    checks.append(
        _check(
            "runtime.python",
            "PASS" if python_ok else "FAIL",
            f"Python runtime is {sys.version.split()[0]}.",
            None if python_ok else "Install Python 3.11 or newer.",
        )
    )
    git_path = shutil.which("git")
    checks.append(
        _check(
            "runtime.git",
            "PASS" if git_path else "FAIL",
            "Git executable is available." if git_path else "Git executable is unavailable.",
            None if git_path else "Install Git before Factory lifecycle operations.",
        )
    )
    checks.append(
        _check(
            "runtime.lifecycle-locking",
            "PASS" if LIFECYCLE_LOCKING_AVAILABLE else "FAIL",
            (
                "POSIX fcntl lifecycle locking is available."
                if LIFECYCLE_LOCKING_AVAILABLE
                else "POSIX fcntl lifecycle locking is unavailable."
            ),
            (
                None
                if LIFECYCLE_LOCKING_AVAILABLE
                else "Run instance lifecycle mutations on a POSIX platform with fcntl support."
            ),
        )
    )
    repository_findings = validate_repository(ROOT)
    repository_errors = [
        finding for finding in repository_findings if finding.severity == "ERROR"
    ]
    checks.append(
        _check(
            "factory.repository",
            "PASS" if not repository_errors else "FAIL",
            (
                "Factory contracts and repository structure validate."
                if not repository_errors
                else f"Factory repository validation has {len(repository_errors)} error(s)."
            ),
            None if not repository_errors else "Run validate and repair every reported error.",
        )
    )
    source, source_check = _source_diagnostics(str(factory["version"]))
    checks.append(source_check)
    try:
        contract_digest = factory_contract_digest()
        checks.append(_check("factory.contract", "PASS", "Factory contract digest was computed."))
    except (OSError, RuntimeError, ValueError) as exc:
        contract_digest = None
        checks.append(
            _check(
                "factory.contract",
                "FAIL",
                f"Factory contract digest cannot be computed: {exc}",
                "Restore the exact release files before using the Factory.",
            )
        )
    checks.append(
        _check(
            "factory.production-integrations",
            "PASS",
            "Factory release has no production integrations enabled by default.",
        )
    )
    instance_detail = None
    if instance is not None:
        instance_detail, instance_checks = _instance_diagnostics(instance)
        checks.extend(instance_checks)

    overall = max((check["status"] for check in checks), key=STATUS_ORDER.__getitem__)
    report = {
        "schema_version": "1.0.0",
        "overall": overall,
        "python": sys.version.split()[0],
        "git": git_path,
        "docker": shutil.which("docker"),
        "gh": shutil.which("gh"),
        "root": str(ROOT),
        "factory_id": factory["id"],
        "factory_version": factory["version"],
        "factory_contract_digest": contract_digest,
        "production_integrations_enabled": False,
        "source": source,
        "instance": instance_detail,
        "checks": checks,
    }
    schema = _load_json(DOCTOR_SCHEMA)
    issues = validate_schema(report, schema)
    if issues:
        details = "; ".join(f"{issue.path}: {issue.message}" for issue in issues)
        raise RuntimeError(f"doctor report violates schema: {details}")
    return report


def doctor_exit_code(report: dict[str, Any]) -> int:
    return 1 if report["overall"] == "FAIL" else 0
