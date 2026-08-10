"""Dependency-free structural, link, policy, and secret validation."""

from __future__ import annotations

import json
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

from core.schema_validation import validate_schema

REQUIRED_PATHS = (
    "AI-BOOTSTRAP.md",
    "AGENTS.md",
    "CLAUDE.md",
    "VERSION",
    "CHANGELOG.md",
    "factory-package.json",
    "capability-package.json",
    "schemas/factory-package.schema.json",
    "schemas/team-instance.schema.json",
    "schemas/team-instance-lock.schema.json",
    "schemas/capability-package.schema.json",
    "docs/01-principles/project-constitution.md",
    "docs/02-architecture/reference-architecture.md",
    "docs/03-security/threat-model.md",
    "team-packs/software-delivery/team-pack.json",
    "team-packs/software-delivery/workflow.json",
    "team-packs/software-delivery/risk-policy.json",
    "team-packs/software-delivery/quality-gates.json",
    "team-packs/software-delivery/tool-policy.json",
    "examples/team-instance/input/instance.json",
)

SECRET_PATTERNS = (
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"\bghp_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bAKIA[A-Z0-9]{16}\b"),
)

MARKDOWN_LINK = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
IGNORED_DERIVED_DIRECTORIES = {".git", ".mypy_cache", ".pytest_cache", ".ruff_cache", "__pycache__"}


@dataclass(frozen=True)
class Finding:
    severity: str
    path: str
    message: str


def _tracked_files(root: Path) -> list[Path]:
    return sorted(
        path
        for path in root.rglob("*")
        if path.is_file() and not IGNORED_DERIVED_DIRECTORIES.intersection(path.parts)
    )


def validate_repository(root: Path) -> list[Finding]:
    findings: list[Finding] = []
    json_documents: dict[Path, object] = {}
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
                json_documents[path.resolve()] = json.loads(text)
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
                findings.append(
                    Finding("ERROR", skill.relative_to(root).as_posix(), "missing SKILL.md")
                )
                continue
            content = skill_file.read_text(encoding="utf-8")
            if "TODO" in content:
                findings.append(
                    Finding("ERROR", skill_file.relative_to(root).as_posix(), "unresolved TODO")
                )
            if not content.startswith("---\n") or f"name: {skill.name}" not in content:
                findings.append(
                    Finding(
                        "ERROR",
                        skill_file.relative_to(root).as_posix(),
                        "invalid Skill frontmatter or folder name",
                    )
                )

    team_path = root / "team-packs/software-delivery/team-pack.json"
    workflow_path = root / "team-packs/software-delivery/workflow.json"
    team = json_documents.get(team_path.resolve())
    workflow = json_documents.get(workflow_path.resolve())
    if team_path.is_file() and team is not None and not isinstance(team, dict):
        findings.append(
            Finding(
                "ERROR", team_path.relative_to(root).as_posix(), "team pack must be a JSON object"
            )
        )
    if workflow_path.is_file() and workflow is not None and not isinstance(workflow, dict):
        findings.append(
            Finding(
                "ERROR",
                workflow_path.relative_to(root).as_posix(),
                "workflow must be a JSON object",
            )
        )
    if isinstance(team, dict) and isinstance(workflow, dict):
        roles = {role["id"] for role in team.get("roles", [])}
        for transition in workflow.get("transitions", []):
            if transition.get("role") not in roles:
                findings.append(
                    Finding(
                        "ERROR",
                        workflow_path.relative_to(root).as_posix(),
                        f"unknown role: {transition.get('role')}",
                    )
                )
        for skill_id in team.get("skill_ids", []):
            if not (root / "skills" / skill_id / "SKILL.md").is_file():
                findings.append(
                    Finding(
                        "ERROR",
                        team_path.relative_to(root).as_posix(),
                        f"missing skill: {skill_id}",
                    )
                )
        tool_policy_path = team_path.parent / team.get("tool_policy", "")
        if not tool_policy_path.is_file():
            findings.append(
                Finding("ERROR", team_path.relative_to(root).as_posix(), "tool policy is missing")
            )
        else:
            tool_policy = json_documents.get(tool_policy_path.resolve())
            if not isinstance(tool_policy, dict):
                findings.append(
                    Finding(
                        "ERROR",
                        tool_policy_path.relative_to(root).as_posix(),
                        "tool policy must be a JSON object",
                    )
                )
                tool_policy = {}
            tool_roles = set(tool_policy.get("roles", {}))
            if roles != tool_roles:
                findings.append(
                    Finding(
                        "ERROR",
                        tool_policy_path.relative_to(root).as_posix(),
                        "tool policy roles differ from team roles",
                    )
                )
            for role_id, policy in tool_policy.get("roles", {}).items():
                overlap = set(policy.get("allowed", [])) & set(policy.get("denied", []))
                if overlap:
                    findings.append(
                        Finding(
                            "ERROR",
                            tool_policy_path.relative_to(root).as_posix(),
                            f"role {role_id} both allows and denies: {sorted(overlap)}",
                        )
                    )

    version_path = root / "VERSION"
    factory_path = root / "factory-package.json"
    capability_path = root / "capability-package.json"
    pyproject_path = root / "pyproject.toml"
    factory = json_documents.get(factory_path.resolve())
    capability = json_documents.get(capability_path.resolve())
    if (
        all(
            path.is_file()
            for path in (version_path, factory_path, capability_path, pyproject_path, team_path)
        )
        and isinstance(factory, dict)
        and isinstance(capability, dict)
        and isinstance(team, dict)
    ):
        factory_schema_path = root / "schemas/factory-package.schema.json"
        factory_schema = json_documents.get(factory_schema_path.resolve())
        if isinstance(factory_schema, dict):
            for issue in validate_schema(factory, factory_schema):
                findings.append(
                    Finding("ERROR", "factory-package.json", f"{issue.path}: {issue.message}")
                )
        try:
            versions = {
                "VERSION": version_path.read_text(encoding="utf-8").strip(),
                "factory-package.json": factory["version"],
                "capability-package.json": capability["version"],
                "pyproject.toml": tomllib.loads(pyproject_path.read_text(encoding="utf-8"))[
                    "project"
                ]["version"],
                "team-pack.json": team["version"],
            }
            if len(set(versions.values())) != 1:
                findings.append(Finding("ERROR", "VERSION", f"release versions differ: {versions}"))
        except (KeyError, TypeError, tomllib.TOMLDecodeError) as exc:
            findings.append(Finding("ERROR", "VERSION", f"release metadata is invalid: {exc}"))
        factory_packs = {
            (record.get("id"), record.get("version"), record.get("path"))
            for record in factory.get("team_packs", [])
        }
        expected_pack = (team.get("id"), team.get("version"), "team-packs/software-delivery")
        if expected_pack not in factory_packs:
            findings.append(
                Finding(
                    "ERROR",
                    "factory-package.json",
                    "software-delivery team pack version or path differs from its source manifest",
                )
            )
        management_skill = factory.get("management_skill", "")
        if not (root / "skills" / management_skill / "SKILL.md").is_file():
            findings.append(
                Finding(
                    "ERROR",
                    "factory-package.json",
                    f"management skill is missing: {management_skill}",
                )
            )
        for relative in factory.get("contract_files", []):
            contract_path = Path(relative)
            if contract_path.is_absolute() or ".." in contract_path.parts:
                findings.append(
                    Finding("ERROR", "factory-package.json", f"unsafe contract path: {relative}")
                )
            elif not (root / contract_path).is_file():
                findings.append(
                    Finding(
                        "ERROR", "factory-package.json", f"contract file is missing: {relative}"
                    )
                )

    try:
        from core.instance import validate_instance_document

        example_path = root / "examples/team-instance/input/instance.json"
        document = json_documents.get(example_path.resolve())
        if isinstance(document, dict):
            for issue in validate_instance_document(document):
                findings.append(
                    Finding(
                        issue.severity,
                        example_path.relative_to(root).as_posix(),
                        f"{issue.path}: {issue.message}",
                    )
                )
        elif example_path.is_file() and document is not None:
            findings.append(
                Finding(
                    "ERROR",
                    example_path.relative_to(root).as_posix(),
                    "instance example must be a JSON object",
                )
            )
    except (KeyError, TypeError, ValueError) as exc:
        findings.append(
            Finding(
                "ERROR",
                "examples/team-instance/input/instance.json",
                f"instance example validation failed: {exc}",
            )
        )

    return findings
