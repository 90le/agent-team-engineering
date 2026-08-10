#!/usr/bin/env python3
"""Vendor-neutral, no-chat-memory cold-start acceptance for the Factory."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.json_support import loads_strict  # noqa: E402
from core.schema_validation import validate_schema  # noqa: E402

PROFILE_PATH = ROOT / "acceptance" / "cross-ai-takeover.json"
PROFILE_SCHEMA = ROOT / "schemas" / "cross-ai-takeover.schema.json"


class TakeoverAcceptanceError(RuntimeError):
    """Raised when a portable cold-start assertion fails."""


def _load_object(path: Path) -> dict[str, Any]:
    value = loads_strict(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TakeoverAcceptanceError(f"JSON root must be an object: {path}")
    return value


def _run(*arguments: str, cwd: Path = ROOT) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["GIT_OPTIONAL_LOCKS"] = "0"
    result = subprocess.run(
        list(arguments),
        cwd=cwd,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise TakeoverAcceptanceError(
            f"command failed ({' '.join(arguments)}): {result.stderr.strip()}"
        )
    return result


def _tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        relative = path.relative_to(root).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return "sha256:" + digest.hexdigest()


def _validate_profile() -> dict[str, Any]:
    profile = _load_object(PROFILE_PATH)
    schema = _load_object(PROFILE_SCHEMA)
    issues = validate_schema(profile, schema)
    if issues:
        details = "; ".join(f"{issue.path}: {issue.message}" for issue in issues)
        raise TakeoverAcceptanceError(f"takeover profile violates schema: {details}")
    return profile


def run_takeover_acceptance() -> dict[str, Any]:
    profile = _validate_profile()
    _run(sys.executable, str(ROOT / "tools" / "agent_team.py"), "validate")

    primary = (ROOT / "AI-BOOTSTRAP.md").read_text(encoding="utf-8")
    if "Codex" not in primary or "Claude" not in primary or "Kimi" not in primary:
        raise TakeoverAcceptanceError("primary bootstrap does not identify cross-AI readers")
    for document in profile["required_documents"]:
        if not (ROOT / document).is_file():
            raise TakeoverAcceptanceError(f"required takeover document is missing: {document}")
    for entrypoint in profile["entrypoints"]:
        path = ROOT / entrypoint["path"]
        if not path.is_file():
            raise TakeoverAcceptanceError(f"takeover entrypoint is missing: {entrypoint['path']}")
        if entrypoint["authority"] == "thin-adapter":
            content = path.read_text(encoding="utf-8")
            if "AI-BOOTSTRAP.md" not in content or len(content.encode("utf-8")) > 1024:
                raise TakeoverAcceptanceError(
                    f"platform entrypoint is not a thin primary-bootstrap route: {entrypoint['path']}"
                )

    with tempfile.TemporaryDirectory(prefix="agent-team-cross-ai-") as temporary:
        workspace = Path(temporary)
        contexts = workspace / "contexts"
        context_digests: dict[str, str] = {}
        for role in profile["context_roles"]:
            output = contexts / f"{role}.json"
            _run(
                sys.executable,
                str(ROOT / "tools" / "agent_team.py"),
                "export-context",
                "--role",
                role,
                "--output",
                str(output),
            )
            bundle = _load_object(output)
            if bundle["role"] != role or not bundle["files"]:
                raise TakeoverAcceptanceError(f"role context is incomplete: {role}")
            for record in bundle["files"]:
                content_digest = hashlib.sha256(record["content"].encode("utf-8")).hexdigest()
                if record["sha256"] != content_digest:
                    raise TakeoverAcceptanceError(f"role context digest differs: {role}")
            context_digests[role] = "sha256:" + hashlib.sha256(output.read_bytes()).hexdigest()

        instance = workspace / "instance"
        _run(
            sys.executable,
            str(ROOT / "tools" / "agent_team.py"),
            "instance",
            "init",
            "--config",
            str(ROOT / "examples" / "team-instance" / "input" / "instance.json"),
            "--output",
            str(instance),
        )
        _run(
            sys.executable,
            str(ROOT / "tools" / "agent_team.py"),
            "instance",
            "validate",
            "--root",
            str(instance),
        )
        doctor = _run(
            sys.executable,
            str(ROOT / "tools" / "agent_team.py"),
            "doctor",
            "--instance",
            str(instance),
        )
        doctor_report = loads_strict(doctor.stdout)
        if doctor_report["overall"] not in {"PASS", "WARN"}:
            raise TakeoverAcceptanceError("generated instance Doctor did not pass")

        target = workspace / "target-project"
        target.mkdir()
        (target / "README.md").write_text("# Portable target\n", encoding="utf-8")
        (target / "pyproject.toml").write_text(
            '[project]\nname = "portable-target"\nversion = "0.1.0"\n',
            encoding="utf-8",
        )
        _run("git", "init", "-q", cwd=target)
        _run("git", "config", "user.name", "Cross AI Acceptance", cwd=target)
        _run("git", "config", "user.email", "acceptance@example.invalid", cwd=target)
        _run("git", "add", "README.md", "pyproject.toml", cwd=target)
        _run("git", "commit", "-q", "-m", "acceptance fixture", cwd=target)
        target_before = _tree_digest(target)

        proposal = workspace / "adoption-proposal"
        _run(
            sys.executable,
            str(ROOT / "tools" / "agent_team.py"),
            "adopt-project",
            "--repo",
            str(target),
            "--output",
            str(proposal),
            "--provider",
            "github",
            "--locator",
            "example/portable-target",
            "--default-branch",
            "main",
            "--project-id",
            "portable-target",
        )
        verification = _run(
            sys.executable,
            str(ROOT / "tools" / "agent_team.py"),
            "adoption",
            "verify",
            "--root",
            str(proposal),
        )
        package = loads_strict(verification.stdout)
        candidate_path = workspace / "candidate-instance.json"
        _run(
            sys.executable,
            str(ROOT / "tools" / "agent_team.py"),
            "adoption",
            "compose",
            "--base-config",
            str(ROOT / "examples" / "team-instance" / "input" / "instance.json"),
            "--proposal",
            str(proposal),
            "--output",
            str(candidate_path),
        )
        candidate = _load_object(candidate_path)
        base = _load_object(ROOT / "examples" / "team-instance" / "input" / "instance.json")
        if _tree_digest(target) != target_before:
            raise TakeoverAcceptanceError("adoption workflow mutated the target repository")
        if candidate["autonomy"] != base["autonomy"] or candidate["adapters"] != base["adapters"]:
            raise TakeoverAcceptanceError("candidate expanded autonomy or adapter authority")
        if candidate["projects"][-1]["mode"] != "proposal-only":
            raise TakeoverAcceptanceError("candidate project is not proposal-only")
        if any(adapter["enabled"] for adapter in candidate["adapters"]):
            raise TakeoverAcceptanceError("candidate enabled an external adapter")

    return {
        "schema_version": "1.0.0",
        "status": "PASS",
        "profile_id": profile["id"],
        "automated_only": True,
        "human_replay_required": profile["human_replay_required"],
        "entrypoints": len(profile["entrypoints"]),
        "context_roles": sorted(context_digests),
        "context_bundle_digests": context_digests,
        "instance_doctor": doctor_report["overall"],
        "adoption_package_id": package["package_id"],
        "target_repository_unchanged": True,
        "external_integrations_enabled": False,
    }


def main() -> int:
    try:
        report = run_takeover_acceptance()
    except (OSError, KeyError, TypeError, ValueError, TakeoverAcceptanceError) as exc:
        print(json.dumps({"status": "FAIL", "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
