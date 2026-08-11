"""Scenario-first planning, confirmation, and safe application for Agent Teams."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from core.adoption import scan_project
from core.context_team import build_design, create_context_team
from core.instance import is_safe_git_branch
from core.json_support import loads_strict
from core.schema_validation import validate_schema
from core.security import find_inline_secret

ROOT = Path(__file__).resolve().parents[1]
PLAN_SCHEMA = ROOT / "schemas" / "guided-adoption-plan.schema.json"
PLATFORMS = ("openclaw", "codex", "claude", "generic-ai")
PURPOSES = ("software", "research-knowledge", "content", "operations", "custom")
AUTOMATION_LEVELS = ("files", "assisted", "managed")
CONFIRMATION_STATEMENT = "I approve this exact adoption proposal for local team creation."

PURPOSE_ROLES = {
    "research-knowledge": [
        "research-lead:Research Lead",
        "source-curator:Source Curator",
        "fact-checker:Fact Checker",
        "knowledge-editor:Knowledge Editor",
        "librarian:Knowledge Librarian",
    ],
    "content": [
        "content-strategist:Content Strategist",
        "researcher:Researcher",
        "writer:Writer",
        "editor:Editor",
        "publisher-handoff:Publisher Handoff",
    ],
    "operations": [
        "intake-coordinator:Intake Coordinator",
        "operations-analyst:Operations Analyst",
        "runbook-maintainer:Runbook Maintainer",
        "verifier:Independent Verifier",
        "change-reviewer:Change Reviewer",
    ],
}


class GuidedAdoptionError(ValueError):
    """Raised when a guided adoption plan is invalid, stale, or unconfirmed."""


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
        raise GuidedAdoptionError(f"guided adoption value is not strict JSON: {exc}") from exc


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
        raise GuidedAdoptionError(f"guided adoption value is not strict JSON: {exc}") from exc


def _digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_compact(value).encode("utf-8")).hexdigest()


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _load_object(path: Path) -> dict[str, Any]:
    if path.is_symlink():
        raise GuidedAdoptionError(f"adoption plan must not be a symbolic link: {path}")
    try:
        value = loads_strict(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise GuidedAdoptionError(f"cannot load adoption plan {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise GuidedAdoptionError(f"adoption plan root must be an object: {path}")
    return value


def _schema() -> dict[str, Any]:
    value = loads_strict(PLAN_SCHEMA.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise GuidedAdoptionError("guided adoption schema root must be an object")
    return value


def inspect_project(repo: Path) -> dict[str, Any]:
    """Return the existing secret-safe, read-only project discovery report."""

    return scan_project(repo)


def _recommendation(
    purpose: str,
    automation: str,
    custom_roles: list[str],
) -> tuple[str, str, str, list[str], list[str], list[str], list[str]]:
    if purpose not in PURPOSES:
        raise GuidedAdoptionError(f"purpose must be one of {list(PURPOSES)}")
    if automation not in AUTOMATION_LEVELS:
        raise GuidedAdoptionError(
            f"automation must be one of {list(AUTOMATION_LEVELS)}"
        )
    if purpose != "software" and automation == "managed":
        raise GuidedAdoptionError(
            "managed automation currently supports the governed software role map only; "
            "start with an assisted custom team, then map each external capability in a separate reviewed project"
        )
    if purpose == "software" and custom_roles:
        raise GuidedAdoptionError(
            "software recommendations use the governed software role map; choose custom purpose for user-defined roles"
        )
    roles = list(custom_roles)
    if purpose == "custom" and not roles:
        raise GuidedAdoptionError("custom purpose requires at least one --role")
    if purpose in PURPOSE_ROLES and not roles:
        roles = list(PURPOSE_ROLES[purpose])

    if purpose == "software" and automation == "managed":
        return (
            "software-managed",
            "managed",
            "A software team with durable, human-approved progression from feedback to a reviewed Draft PR.",
            [
                "The requested workflow needs state that survives restarts.",
                "Implementation begins only after confirmation of the exact plan.",
                "Testing and independent review are explicit stages before the Draft PR stop.",
            ],
            [
                "Use an assisted software team if people will coordinate each step through files and their AI tools."
            ],
            [
                "Live model accounts, repository writes, intake channels, and a production sandbox remain disabled.",
                "The generated controller stops at a reviewed Draft PR; it does not merge or deploy.",
            ],
            roles,
        )
    if purpose == "software":
        wording = (
            "A portable software team operated through shared files and the selected AI platforms."
            if automation == "assisted"
            else "A portable, file-based software team with no persistent controller."
        )
        return (
            "software-lite",
            "lite",
            wording,
            [
                "The project benefits from explicit product, architecture, frontend, backend, QA, review, and release-handoff roles.",
                "A persistent automation controller is not required for the requested starting point.",
                "The same Markdown authority can be used by each selected AI platform.",
            ],
            [
                "Choose managed automation later if feedback must progress durably to a reviewed Draft PR after exact human approval."
            ],
            [
                "Role files request capabilities but do not create credentials, sandboxes, repository permissions, or approval identity.",
                "People or the selected AI host must coordinate durable task and handoff records.",
            ],
            roles,
        )
    return (
        "custom",
        "lite",
        "A purpose-built team with named roles, shared context, evidence handoffs, and a human decision boundary.",
        [
            "The requested outcome is not limited to the built-in software-delivery workflow.",
            "Named roles make responsibility and handoffs understandable across AI products.",
            "A context-only starting point remains portable and avoids inventing external authority.",
        ],
        [
            "Map selected roles to a governed runtime later only after their tools, identities, approvals, and recovery are specified."
        ],
        [
            "This custom team is context-only and has no persistent controller.",
            "Generated role text cannot grant Shell, credentials, external writes, approval, merge, or deployment.",
        ],
        roles,
    )


def _absolute_new_path(path: Path, source: Path, label: str) -> Path:
    if path.is_symlink():
        raise GuidedAdoptionError(f"{label} must not be a symbolic link")
    resolved = path.resolve()
    if resolved.exists():
        raise GuidedAdoptionError(f"{label} already exists; guided adoption never overwrites")
    if resolved == source or source in resolved.parents:
        raise GuidedAdoptionError(f"{label} must be outside the target project")
    if resolved == ROOT or ROOT in resolved.parents:
        raise GuidedAdoptionError(f"{label} must be outside the Factory repository")
    if resolved == Path(resolved.anchor):
        raise GuidedAdoptionError(f"{label} must not be a filesystem root")
    return resolved


def build_plan(
    project_path: Path,
    *,
    purpose: str,
    goals: list[str],
    automation: str,
    platforms: list[str],
    team_name: str,
    project_name: str | None,
    owner: str,
    provider: str,
    repository: str | None,
    default_branch: str | None,
    output_path: Path,
    custom_roles: list[str] | None = None,
    summary: str | None = None,
) -> dict[str, Any]:
    discovery = inspect_project(project_path)
    source = Path(discovery["source_path"])
    output = _absolute_new_path(output_path, source, "team output")
    selected_platforms = list(dict.fromkeys(platforms))
    if not selected_platforms or any(item not in PLATFORMS for item in selected_platforms):
        raise GuidedAdoptionError(f"platforms must be selected from {list(PLATFORMS)}")
    selected_goals = [item.strip() for item in goals if item.strip()]
    if not selected_goals:
        raise GuidedAdoptionError("at least one non-empty goal is required")
    selected_roles = list(dict.fromkeys(custom_roles or []))
    (
        preset,
        mode,
        plain_language,
        reasons,
        alternatives,
        limitations,
        selected_roles,
    ) = _recommendation(purpose, automation, selected_roles)
    selected_name = (project_name or source.name).strip()
    selected_branch = (default_branch or discovery["current_branch"] or "main").strip()
    if not is_safe_git_branch(selected_branch):
        raise GuidedAdoptionError("default branch is not a safe Git branch name")
    if provider not in {"github", "gitlab", "gitea", "generic-git"}:
        raise GuidedAdoptionError("unsupported project provider")
    selected_repository = (repository or f"local/{source.name}").strip()
    if provider != "generic-git" and repository is None:
        raise GuidedAdoptionError("a hosted repository provider requires an explicit --repository")

    unknowns = [
        "Build, lint, test, and acceptance commands have not yet been owner-reviewed.",
        "Data sensitivity, secret providers, and production access have not been mapped.",
        "Deployment, rollback, monitoring, and service-level expectations remain project-owned.",
    ]
    if discovery["source_dirty"]:
        unknowns.append(
            "The inspected project has uncommitted changes; the plan binds its commit but cannot summarize uncommitted content."
        )
    if mode == "managed":
        unknowns.append(
            "Live intake, authenticated approval, model, SCM, and isolated Runner adapters are intentionally unconfigured."
        )
    proposal = {
        "discovery": {
            key: discovery[key]
            for key in (
                "source_path",
                "source_commit",
                "source_dirty",
                "current_branch",
                "technologies",
                "ai_entrypoints",
                "github_workflows",
                "has_tests",
                "has_architecture_docs",
            )
        },
        "intent": {
            "purpose": purpose,
            "goals": selected_goals,
            "automation": automation,
            "platforms": selected_platforms,
            "custom_roles": selected_roles,
        },
        "recommendation": {
            "preset": preset,
            "mode": mode,
            "plain_language": plain_language,
            "reasons": reasons,
            "alternatives": alternatives,
            "limitations": limitations,
        },
        "team": {
            "name": team_name.strip(),
            "project_name": selected_name,
            "owner": owner.strip(),
            "provider": provider,
            "repository": selected_repository,
            "default_branch": selected_branch,
            "summary": (summary or selected_goals[0]).strip(),
            "output_path": str(output),
        },
        "effects": {
            "target_project_mutated": False,
            "factory_mutated": False,
            "external_writes": False,
            "creates_new_team_directory": True,
            "project_export_requires_separate_confirmation": True,
        },
        "unknowns": unknowns,
    }
    digest = _digest(proposal)
    plan = {
        "$schema": "urn:agent-team:schema:guided-adoption-plan:1.0.0",
        "schema_version": "1.0.0",
        "plan_id": "adoption-plan-" + digest.removeprefix("sha256:")[:32],
        "state": "DRAFT",
        "proposal": proposal,
        "proposal_digest": digest,
        "confirmation": None,
    }
    validate_plan(plan)
    return plan


def validate_plan(plan: dict[str, Any]) -> dict[str, Any]:
    issues = validate_schema(plan, _schema())
    if issues:
        details = "; ".join(f"{issue.path}: {issue.message}" for issue in issues)
        raise GuidedAdoptionError(f"guided adoption plan violates schema: {details}")
    secret_path = find_inline_secret(plan)
    if secret_path:
        raise GuidedAdoptionError(
            f"guided adoption plan contains credential-like material at {secret_path}"
        )
    expected_digest = _digest(plan["proposal"])
    expected_id = "adoption-plan-" + expected_digest.removeprefix("sha256:")[:32]
    if plan["proposal_digest"] != expected_digest or plan["plan_id"] != expected_id:
        raise GuidedAdoptionError("adoption proposal digest or plan identity differs from content")
    confirmation = plan["confirmation"]
    if plan["state"] == "DRAFT" and confirmation is not None:
        raise GuidedAdoptionError("a draft plan must not contain confirmation")
    if plan["state"] == "CONFIRMED":
        if confirmation is None:
            raise GuidedAdoptionError("a confirmed plan requires confirmation")
        if confirmation["proposal_digest"] != expected_digest:
            raise GuidedAdoptionError("confirmation is not bound to the current proposal digest")
    proposal = plan["proposal"]
    recommendation = proposal["recommendation"]
    intent = proposal["intent"]
    if recommendation["mode"] == "managed" and intent["purpose"] != "software":
        raise GuidedAdoptionError("managed mode requires software purpose")
    if recommendation["preset"] == "custom" and not intent["custom_roles"]:
        raise GuidedAdoptionError("custom recommendation requires explicit roles")
    source = Path(proposal["discovery"]["source_path"])
    output = Path(proposal["team"]["output_path"])
    if not source.is_absolute() or not output.is_absolute():
        raise GuidedAdoptionError("source and output paths must be absolute")
    if output == source or source in output.parents or output == ROOT or ROOT in output.parents:
        raise GuidedAdoptionError("team output escapes the guided adoption boundary")
    if not is_safe_git_branch(proposal["team"]["default_branch"]):
        raise GuidedAdoptionError("default branch is not a safe Git branch name")
    return plan


def load_plan(path: Path) -> dict[str, Any]:
    return validate_plan(_load_object(path.resolve()))


def write_plan(plan: dict[str, Any], path: Path) -> dict[str, Any]:
    validate_plan(plan)
    source = Path(plan["proposal"]["discovery"]["source_path"])
    target = _absolute_new_path(path, source, "plan output")
    target.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(target, flags, 0o644)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(_canonical(plan))
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        if target.exists() and not target.is_symlink():
            target.unlink()
        raise
    _fsync_directory(target.parent)
    return plan


def preview_plan(plan: dict[str, Any]) -> str:
    validate_plan(plan)
    proposal = plan["proposal"]
    intent = proposal["intent"]
    recommendation = proposal["recommendation"]
    team = proposal["team"]
    roles = intent["custom_roles"] or ["Built-in software team role map"]
    lines = [
        "# Agent Team adoption proposal",
        "",
        f"State: `{plan['state']}`",
        f"Exact proposal digest: `{plan['proposal_digest']}`",
        "",
        "## Desired outcome",
        "",
        *[f"- {goal}" for goal in intent["goals"]],
        "",
        "## Recommendation",
        "",
        recommendation["plain_language"],
        "",
        f"- Team: `{team['name']}`",
        f"- Project: `{team['provider']}:{team['repository']}`",
        f"- AI platforms: `{', '.join(intent['platforms'])}`",
        f"- Implementation mapping: `{recommendation['preset']}` / `{recommendation['mode']}`",
        f"- Roles: `{', '.join(roles)}`",
        f"- New output directory: `{team['output_path']}`",
        "",
        "### Why this fits",
        "",
        *[f"- {item}" for item in recommendation["reasons"]],
        "",
        "### Alternative",
        "",
        *[f"- {item}" for item in recommendation["alternatives"]],
        "",
        "### Not enabled by this plan",
        "",
        *[f"- {item}" for item in recommendation["limitations"]],
        "- The target project is not modified; exporting an adapter into it is a later, separate confirmation.",
        "",
        "### Known unknowns",
        "",
        *[f"- {item}" for item in proposal["unknowns"]],
    ]
    if plan["state"] == "DRAFT":
        lines.extend(
            [
                "",
                "No team has been created. Confirm this exact digest before applying the plan.",
            ]
        )
    return "\n".join(lines) + "\n"


def confirm_plan(path: Path, *, digest: str, approved_by: str) -> dict[str, Any]:
    target = path.resolve()
    plan = load_plan(target)
    if plan["state"] != "DRAFT":
        raise GuidedAdoptionError("adoption plan is already confirmed")
    if digest != plan["proposal_digest"]:
        raise GuidedAdoptionError("confirmation digest does not match the exact proposal")
    actor = approved_by.strip()
    if not actor or len(actor) > 160:
        raise GuidedAdoptionError("approved-by must be a non-empty display name up to 160 characters")
    plan["state"] = "CONFIRMED"
    plan["confirmation"] = {
        "proposal_digest": digest,
        "approved_by": actor,
        "scope": "create-new-team-directory-only",
        "statement": CONFIRMATION_STATEMENT,
    }
    validate_plan(plan)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.confirm-", dir=target.parent
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o644)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(_canonical(plan))
            handle.flush()
            os.fsync(handle.fileno())
        if target.is_symlink() or not target.is_file():
            raise GuidedAdoptionError("adoption plan changed before confirmation")
        if load_plan(target) != {
            **plan,
            "state": "DRAFT",
            "confirmation": None,
        }:
            raise GuidedAdoptionError("adoption plan changed during confirmation")
        os.replace(temporary, target)
        _fsync_directory(target.parent)
    except Exception:
        if temporary.exists():
            temporary.unlink()
        raise
    return plan


def apply_plan(path: Path) -> dict[str, Any]:
    plan_path = path.resolve()
    plan = load_plan(plan_path)
    if plan["state"] != "CONFIRMED":
        raise GuidedAdoptionError("preview and confirm the exact adoption plan before applying it")
    proposal = plan["proposal"]
    discovery = proposal["discovery"]
    current = inspect_project(Path(discovery["source_path"]))
    if discovery["source_commit"] is not None and current["source_commit"] != discovery["source_commit"]:
        raise GuidedAdoptionError("target project commit changed after planning; create and confirm a new plan")
    output = Path(proposal["team"]["output_path"])
    if output.exists() or output.is_symlink():
        raise GuidedAdoptionError("team output already exists; guided adoption never overwrites")
    intent = proposal["intent"]
    team = proposal["team"]
    recommendation = proposal["recommendation"]
    design = build_design(
        recommendation["preset"],
        team_name=team["name"],
        project_name=team["project_name"],
        repository=team["repository"],
        provider=team["provider"],
        default_branch=team["default_branch"],
        owner_name=team["owner"],
        platforms=intent["platforms"],
        custom_roles=intent["custom_roles"],
        summary=team["summary"],
    )
    with tempfile.TemporaryDirectory(prefix="agent-team-guided-apply-") as temporary:
        design_path = Path(temporary) / "team-design.json"
        design_path.write_text(_canonical(design), encoding="utf-8")
        report = create_context_team(design_path, output)
    return {
        **report,
        "adoption_plan": str(plan_path),
        "proposal_digest": plan["proposal_digest"],
        "confirmation_scope": plan["confirmation"]["scope"],
        "target_project_mutated": False,
        "external_integrations_enabled": False,
        "next": [
            f"Read {output / 'GETTING-STARTED.md'} as the human quick start.",
            f"Ask an AI to read {output / 'AI-START.md'} and help start the first bounded task.",
            "Review project unknowns before granting tools or exporting a platform adapter.",
        ],
    }
