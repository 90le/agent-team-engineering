"""Create bounded, hash-addressed handoff bundles for agents without repository access."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

BASE_FILES = (
    "AI-BOOTSTRAP.md",
    "docs/01-principles/project-constitution.md",
    "docs/02-architecture/reference-architecture.md",
    "docs/03-security/threat-model.md",
    "team-packs/software-delivery/team-pack.json",
    "team-packs/software-delivery/workflow.json",
    "team-packs/software-delivery/risk-policy.json",
    "team-packs/software-delivery/quality-gates.json",
    "team-packs/software-delivery/tool-policy.json",
    "team-packs/software-delivery/context-policy.json",
)


ROLE_SKILLS = {
    "public-intake": "skills/collect-feedback/SKILL.md",
    "intake": "skills/collect-feedback/SKILL.md",
    "triage": "skills/triage-work-item/SKILL.md",
    "product": "skills/specify-change/SKILL.md",
    "builder": "skills/implement-change/SKILL.md",
    "reviewer": "skills/review-change/SKILL.md",
    "qa": "skills/verify-release/SKILL.md",
    "release": "skills/deploy-and-rollback/SKILL.md",
    "operations": "skills/deploy-and-rollback/SKILL.md",
    "orchestrator": "skills/orchestrate-software-delivery/SKILL.md",
}


def build_context_bundle(root: Path, role: str, max_bytes: int = 200_000) -> dict[str, Any]:
    if role not in ROLE_SKILLS:
        raise ValueError(f"unknown role: {role}")
    paths = [*BASE_FILES, ROLE_SKILLS[role]]
    records = []
    total = 0
    for relative in paths:
        path = root / relative
        content = path.read_text(encoding="utf-8")
        size = len(content.encode("utf-8"))
        total += size
        if total > max_bytes:
            raise ValueError("context bundle exceeds configured size limit")
        records.append(
            {
                "path": relative,
                "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
                "content": content,
            }
        )
    return {
        "schema_version": "1.0.0",
        "role": role,
        "authority": "source Git files at the recorded hashes",
        "files": records,
    }


def write_context_bundle(root: Path, role: str, output: Path) -> None:
    bundle = build_context_bundle(root, role)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(bundle, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
