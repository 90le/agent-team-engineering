"""Dependency-free structural, link, policy, and secret validation."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path


REQUIRED_PATHS = (
    "AI-BOOTSTRAP.md",
    "AGENTS.md",
    "CLAUDE.md",
    "VERSION",
    "capability-package.json",
    "schemas/capability-package.schema.json",
    "docs/01-principles/project-constitution.md",
    "docs/02-architecture/reference-architecture.md",
    "docs/03-security/threat-model.md",
    "team-packs/software-delivery/team-pack.json",
    "team-packs/software-delivery/workflow.json",
    "team-packs/software-delivery/risk-policy.json",
    "team-packs/software-delivery/quality-gates.json",
    "team-packs/software-delivery/tool-policy.json",
)

SECRET_PATTERNS = (
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"\bghp_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bAKIA[A-Z0-9]{16}\b"),
)

MARKDOWN_LINK = re.compile(r"\[[^\]]+\]\(([^)]+)\)")


@dataclass(frozen=True)
class Finding:
    severity: str
    path: str
    message: str


def _tracked_files(root: Path) -> list[Path]:
    return sorted(
        path
        for path in root.rglob("*")
        if path.is_file() and ".git" not in path.parts and "__pycache__" not in path.parts
    )


def validate_repository(root: Path) -> list[Finding]:
    findings: list[Finding] = []
    for relative in REQUIRED_PATHS:
        if not (root / relative).is_file():
            findings.append(Finding("ERROR", relative, "required file is missing"))

    for path in _tracked_files(root):
        relative = path.relative_to(root).as_posix()
        if path.stat().st_size > 10 * 1024 * 1024:
            findings.append(Finding("ERROR", relative, "ordinary Git file exceeds 10 MiB"))
        if path.name == ".env" or path.suffix.lower() in {".pem", ".key", ".db", ".sqlite"}:
            findings.append(Finding("ERROR", relative, "forbidden secret or runtime file type"))
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            findings.append(Finding("ERROR", relative, "non-UTF-8 or binary file is not allowed"))
            continue
        for pattern in SECRET_PATTERNS:
            if pattern.search(text):
                findings.append(Finding("ERROR", relative, "high-confidence credential pattern"))

        if path.suffix == ".json":
            try:
                json.loads(text)
            except json.JSONDecodeError as exc:
                findings.append(Finding("ERROR", relative, f"invalid JSON: {exc}"))
        if path.suffix == ".md":
            for link in MARKDOWN_LINK.findall(text):
                target = link.split("#", 1)[0]
                if not target or "://" in target or target.startswith("mailto:"):
                    continue
                resolved = (path.parent / target).resolve()
                if not resolved.exists():
                    findings.append(Finding("ERROR", relative, f"broken local link: {link}"))

    skill_root = root / "skills"
    if skill_root.is_dir():
        for skill in sorted(path for path in skill_root.iterdir() if path.is_dir()):
            skill_file = skill / "SKILL.md"
            if not skill_file.is_file():
                findings.append(Finding("ERROR", skill.relative_to(root).as_posix(), "missing SKILL.md"))
                continue
            content = skill_file.read_text(encoding="utf-8")
            if "TODO" in content:
                findings.append(Finding("ERROR", skill_file.relative_to(root).as_posix(), "unresolved TODO"))
            if not content.startswith("---\n") or f"name: {skill.name}" not in content:
                findings.append(Finding("ERROR", skill_file.relative_to(root).as_posix(), "invalid Skill frontmatter or folder name"))

    team_path = root / "team-packs/software-delivery/team-pack.json"
    workflow_path = root / "team-packs/software-delivery/workflow.json"
    if team_path.is_file() and workflow_path.is_file():
        team = json.loads(team_path.read_text(encoding="utf-8"))
        workflow = json.loads(workflow_path.read_text(encoding="utf-8"))
        roles = {role["id"] for role in team.get("roles", [])}
        for transition in workflow.get("transitions", []):
            if transition.get("role") not in roles:
                findings.append(Finding("ERROR", workflow_path.relative_to(root).as_posix(), f"unknown role: {transition.get('role')}"))
        for skill_id in team.get("skill_ids", []):
            if not (root / "skills" / skill_id / "SKILL.md").is_file():
                findings.append(Finding("ERROR", team_path.relative_to(root).as_posix(), f"missing skill: {skill_id}"))
        tool_policy_path = team_path.parent / team.get("tool_policy", "")
        if not tool_policy_path.is_file():
            findings.append(Finding("ERROR", team_path.relative_to(root).as_posix(), "tool policy is missing"))
        else:
            tool_policy = json.loads(tool_policy_path.read_text(encoding="utf-8"))
            tool_roles = set(tool_policy.get("roles", {}))
            if roles != tool_roles:
                findings.append(Finding("ERROR", tool_policy_path.relative_to(root).as_posix(), "tool policy roles differ from team roles"))
            for role_id, policy in tool_policy.get("roles", {}).items():
                overlap = set(policy.get("allowed", [])) & set(policy.get("denied", []))
                if overlap:
                    findings.append(Finding("ERROR", tool_policy_path.relative_to(root).as_posix(), f"role {role_id} both allows and denies: {sorted(overlap)}"))

    return findings
