"""Read-only project discovery and proposal generation."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any


MARKERS = {
    "node": ("package.json", "pnpm-lock.yaml", "yarn.lock"),
    "python": ("pyproject.toml", "requirements.txt", "Pipfile"),
    "go": ("go.mod",),
    "rust": ("Cargo.toml",),
    "java": ("pom.xml", "build.gradle", "build.gradle.kts"),
    "containers": ("Dockerfile", "Containerfile", "compose.yaml", "docker-compose.yml"),
}


def _git_commit(root: Path) -> str | None:
    result = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        check=False,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip() if result.returncode == 0 else None


def scan_project(repo: Path) -> dict[str, Any]:
    root = repo.resolve()
    if not root.is_dir():
        raise ValueError(f"project repository does not exist: {root}")

    files = {path.name for path in root.iterdir() if path.is_file()}
    technologies = sorted(
        technology
        for technology, markers in MARKERS.items()
        if any(marker in files for marker in markers)
    )
    ai_entries = sorted(name for name in ("AGENTS.md", "CLAUDE.md", "AI-BOOTSTRAP.md") if name in files)
    workflow_dir = root / ".github" / "workflows"
    workflows = sorted(path.name for path in workflow_dir.glob("*.y*ml")) if workflow_dir.is_dir() else []

    return {
        "schema_version": "1.0.0",
        "source_path": str(root),
        "source_commit": _git_commit(root),
        "technologies": technologies,
        "ai_entrypoints": ai_entries,
        "github_workflows": workflows,
        "has_tests": any((root / name).exists() for name in ("tests", "test", "spec")),
        "has_architecture_docs": any((root / name).exists() for name in ("docs", "doc", "architecture")),
        "hazards": [
            "Do not copy .env files, credentials, runtime databases, logs, or production data.",
            "Do not infer deployment authority from repository write access.",
        ],
        "recommendations": [
            "Review generated policy and bootstrap files on a proposal branch.",
            "Bind build, test, deployment, and secret providers explicitly before enablement.",
            "Run a simulated workflow and negative authorization tests before live integrations.",
        ],
    }


def write_adoption_proposal(repo: Path, output: Path) -> dict[str, Any]:
    source = repo.resolve()
    destination = output.resolve()
    if destination == source or source in destination.parents:
        raise ValueError("proposal output must be outside the analyzed repository")
    report = scan_project(source)
    (destination / ".agent-team").mkdir(parents=True, exist_ok=True)

    (destination / "ADOPTION-REPORT.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    project = {
        "schema_version": "1.0.0",
        "project_id": f"project.{source.name}",
        "status": "PROPOSED",
        "source_commit": report["source_commit"],
        "team_pack": "team-pack.software-delivery",
        "autonomy_level": "A1",
        "production_requires_human": True,
    }
    (destination / ".agent-team" / "project.json").write_text(
        json.dumps(project, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    risk_policy = {
        "schema_version": "1.0.0",
        "default_risk": "MEDIUM",
        "manual_only": ["secrets", "auth", "payments", "destructive-migration", "production-data", "infrastructure"],
    }
    (destination / ".agent-team" / "risk-policy.json").write_text(
        json.dumps(risk_policy, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (destination / "AI-BOOTSTRAP.md").write_text(
        "# Project agent bootstrap proposal\n\n"
        "This file is generated as a proposal. Read `.agent-team/project.json`, the project's "
        "authoritative architecture and the selected team pack before making changes. Do not "
        "assume production or secret access.\n",
        encoding="utf-8",
    )
    return report
