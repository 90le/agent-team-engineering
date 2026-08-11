"""Dependency-free structural, link, policy, and secret validation."""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

from core.json_support import loads_strict
from core.schema_validation import validate_schema
from core.security import CREDENTIAL_PATTERNS

REQUIRED_PATHS = (
    "README.md",
    "README.zh-CN.md",
    "AI-BOOTSTRAP.md",
    "AI-START.md",
    "AGENTS.md",
    "CLAUDE.md",
    "LICENSE",
    "SECURITY.md",
    "CONTRIBUTING.md",
    "CODE_OF_CONDUCT.md",
    "agent-team",
    "VERSION",
    "CHANGELOG.md",
    "factory-package.json",
    "capability-package.json",
    "acceptance/cross-ai-takeover.json",
    "core/adapters.py",
    "core/adapter_ports.py",
    "core/agent_drivers.py",
    "core/adoption.py",
    "core/approval.py",
    "core/contracts.py",
    "core/contract_migration.py",
    "core/context_team.py",
    "core/doctor.py",
    "core/installation.py",
    "core/instance.py",
    "core/isolation.py",
    "core/json_support.py",
    "core/lifecycle.py",
    "core/reference_adapters.py",
    "core/team_creator.py",
    "core/team_runtime.py",
    "core/github_transport.py",
    "core/webhooks.py",
    "tools/cross_ai_takeover.py",
    "adapters/claude/adapter.json",
    "adapters/cli-model-router/adapter.json",
    "adapters/codex/adapter.json",
    "adapters/file-inbox/adapter.json",
    "adapters/generic-ai/adapter.json",
    "adapters/github/adapter.json",
    "adapters/local-dry-run/adapter.json",
    "adapters/manual-agent/adapter.json",
    "adapters/openclaw/adapter.json",
    "adapters/recording/adapter.json",
    "schemas/factory-package.schema.json",
    "schemas/team-instance.schema.json",
    "schemas/team-instance-lock.schema.json",
    "schemas/adoption-package.schema.json",
    "schemas/adoption-project.schema.json",
    "schemas/adoption-report.schema.json",
    "schemas/adoption-risk-policy.schema.json",
    "schemas/doctor-report.schema.json",
    "schemas/factory-installation.schema.json",
    "schemas/instance-lifecycle-journal.schema.json",
    "schemas/instance-recovery-manifest.schema.json",
    "schemas/instance-upgrade-plan.schema.json",
    "schemas/control-plane-audit.schema.json",
    "schemas/control-plane-status.schema.json",
    "schemas/cross-ai-takeover.schema.json",
    "schemas/outbox-effect.schema.json",
    "schemas/task-lease.schema.json",
    "schemas/adapter-empty-config.schema.json",
    "schemas/adapter.schema.json",
    "schemas/adapter-request.schema.json",
    "schemas/adapter-result.schema.json",
    "schemas/approval-assertion.schema.json",
    "schemas/team-spec.schema.json",
    "schemas/role-contract.schema.json",
    "schemas/workflow-spec.schema.json",
    "schemas/work-item-v2.schema.json",
    "schemas/plan-revision.schema.json",
    "schemas/approval-grant.schema.json",
    "schemas/run.schema.json",
    "schemas/evidence-bundle.schema.json",
    "schemas/adapter-descriptor.schema.json",
    "schemas/command-envelope.schema.json",
    "schemas/event-envelope.schema.json",
    "schemas/agent-step-result.schema.json",
    "schemas/agent-step-task.schema.json",
    "schemas/cli-model-router-config.schema.json",
    "schemas/execution-request.schema.json",
    "schemas/execution-result.schema.json",
    "schemas/external-reference.schema.json",
    "schemas/project-task-envelope.schema.json",
    "schemas/runner-profile.schema.json",
    "schemas/team-blueprint.schema.json",
    "schemas/team-design.schema.json",
    "schemas/context-team-lock.schema.json",
    "schemas/team-lock.schema.json",
    "schemas/adapter-authority-policy.schema.json",
    "policies/adapter-authority.json",
    "schemas/capability-package.schema.json",
    "schemas/capability-report.schema.json",
    "docs/01-principles/project-constitution.md",
    "docs/02-architecture/reference-architecture.md",
    "docs/03-security/threat-model.md",
    "docs/05-adoption/existing-project-adoption.md",
    "docs/08-factory/instance-lifecycle.md",
    "docs/10-adapters/sdk-isolation-and-approval.md",
    "docs/11-lifecycle/installation-upgrade-and-adoption.md",
    "docs/12-acceptance/cross-ai-takeover.md",
    "docs/13-team-creator/blueprint-compiler-and-reference-runtime.md",
    "docs/14-context-first/context-first-team-kit.md",
    "docs/14-context-first/platform-installation.md",
    "docs/15-upstream-independent/core-contracts-and-migration.md",
    "docs/15-upstream-independent/adapter-port-sdk.md",
    "docs/adr/ADR-0005-versioned-adapter-host-and-bound-approval.md",
    "docs/adr/ADR-0006-verified-install-and-transactional-instance-lifecycle.md",
    "docs/adr/ADR-0007-team-blueprint-compiler-and-governed-reference-runtime.md",
    "docs/adr/ADR-0008-context-first-team-kits-and-discovery-bundles.md",
    "docs/adr/ADR-0009-vendor-neutral-core-and-replaceable-ports.md",
    "contracts/core-contracts.json",
    "contracts/v07-to-v08-migration.json",
    "examples/v08-contracts/README.md",
    "examples/v08-contracts/valid/team-spec.json",
    "examples/v08-contracts/valid/role-contract.json",
    "examples/v08-contracts/valid/workflow-spec.json",
    "examples/v08-contracts/valid/work-item.json",
    "examples/v08-contracts/valid/plan-revision.json",
    "examples/v08-contracts/valid/approval-grant.json",
    "examples/v08-contracts/valid/run.json",
    "examples/v08-contracts/valid/evidence-bundle.json",
    "examples/v08-contracts/valid/adapter-descriptor.json",
    "examples/v08-contracts/valid/command-envelope.json",
    "examples/v08-contracts/valid/event-envelope.json",
    "examples/v08-contracts/valid/capability-report.json",
    "examples/v08-contracts/invalid/cases.json",
    "skills/create-agent-team/SKILL.md",
    "skills/manage-agent-team-factory/SKILL.md",
    "skills/implement-agent-team-adapter/SKILL.md",
    "skills/upgrade-agent-team-instance/SKILL.md",
    "team-packs/software-delivery/team-pack.json",
    "team-packs/software-delivery/workflow.json",
    "team-packs/software-delivery/risk-policy.json",
    "team-packs/software-delivery/quality-gates.json",
    "team-packs/software-delivery/tool-policy.json",
    "examples/team-instance/input/instance.json",
    "examples/context-first/team-design.json",
    "presets/software-lite.json",
    "presets/software-managed.json",
    "presets/custom.json",
    ".agents/plugins/marketplace.json",
    ".agents/plugins/plugins/agent-team/.codex-plugin/plugin.json",
    ".agents/plugins/plugins/agent-team/.claude-plugin/plugin.json",
    ".agents/plugins/plugins/agent-team/skills/bootstrap-agent-team/SKILL.md",
    ".claude-plugin/marketplace.json",
)

MARKDOWN_LINK = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
IGNORED_DERIVED_DIRECTORIES = {".git", ".mypy_cache", ".pytest_cache", ".ruff_cache", "__pycache__"}

REQUIRED_CONTRACT_FILES = frozenset(
    {
        "docs/05-adoption/existing-project-adoption.md",
        "docs/08-factory/instance-lifecycle.md",
        "docs/11-lifecycle/installation-upgrade-and-adoption.md",
        "docs/12-acceptance/cross-ai-takeover.md",
        "docs/13-team-creator/blueprint-compiler-and-reference-runtime.md",
        "docs/14-context-first/context-first-team-kit.md",
        "docs/14-context-first/platform-installation.md",
        "docs/15-upstream-independent/core-contracts-and-migration.md",
        "docs/15-upstream-independent/adapter-port-sdk.md",
        "docs/adr/ADR-0006-verified-install-and-transactional-instance-lifecycle.md",
        "docs/adr/ADR-0007-team-blueprint-compiler-and-governed-reference-runtime.md",
        "docs/adr/ADR-0008-context-first-team-kits-and-discovery-bundles.md",
        "docs/adr/ADR-0009-vendor-neutral-core-and-replaceable-ports.md",
        "contracts/core-contracts.json",
        "contracts/v07-to-v08-migration.json",
        "schemas/team-spec.schema.json",
        "schemas/role-contract.schema.json",
        "schemas/workflow-spec.schema.json",
        "schemas/work-item-v2.schema.json",
        "schemas/plan-revision.schema.json",
        "schemas/approval-grant.schema.json",
        "schemas/run.schema.json",
        "schemas/evidence-bundle.schema.json",
        "schemas/adapter-descriptor.schema.json",
        "schemas/command-envelope.schema.json",
        "schemas/event-envelope.schema.json",
        "schemas/capability-report.schema.json",
        "examples/v08-contracts/README.md",
        "examples/v08-contracts/valid/capability-report.json",
        "examples/v08-contracts/invalid/cases.json",
        "schemas/adoption-package.schema.json",
        "schemas/adoption-project.schema.json",
        "schemas/adoption-report.schema.json",
        "schemas/adoption-risk-policy.schema.json",
        "schemas/doctor-report.schema.json",
        "schemas/cross-ai-takeover.schema.json",
        "schemas/factory-installation.schema.json",
        "schemas/instance-lifecycle-journal.schema.json",
        "schemas/instance-recovery-manifest.schema.json",
        "schemas/instance-upgrade-plan.schema.json",
        "schemas/agent-step-result.schema.json",
        "schemas/agent-step-task.schema.json",
        "schemas/cli-model-router-config.schema.json",
        "schemas/runner-profile.schema.json",
        "schemas/team-blueprint.schema.json",
        "schemas/team-design.schema.json",
        "schemas/context-team-lock.schema.json",
        "schemas/team-lock.schema.json",
        "AI-START.md",
        ".agents/plugins/marketplace.json",
        ".agents/plugins/plugins/agent-team/.codex-plugin/plugin.json",
        ".agents/plugins/plugins/agent-team/.claude-plugin/plugin.json",
        ".agents/plugins/plugins/agent-team/skills/bootstrap-agent-team/SKILL.md",
        ".claude-plugin/marketplace.json",
        "presets/custom.json",
        "presets/software-lite.json",
        "presets/software-managed.json",
        "skills/create-agent-team/SKILL.md",
        "skills/upgrade-agent-team-instance/SKILL.md",
        "acceptance/cross-ai-takeover.json",
    }
)


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

    for path in sorted(root.rglob("*")):
        if path.is_symlink() and not IGNORED_DERIVED_DIRECTORIES.intersection(path.parts):
            findings.append(
                Finding(
                    "ERROR",
                    path.relative_to(root).as_posix(),
                    "symbolic links are not allowed",
                )
            )

    for path in _tracked_files(root):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            continue
        if path.stat().st_size > 10 * 1024 * 1024:
            findings.append(Finding("ERROR", relative, "ordinary Git file exceeds 10 MiB"))
        if path.name == ".env" or path.suffix.lower() in {".pem", ".key", ".db", ".sqlite"}:
            findings.append(Finding("ERROR", relative, "forbidden secret or runtime file type"))
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            findings.append(Finding("ERROR", relative, "non-UTF-8 or binary file is not allowed"))
            continue
        for pattern in CREDENTIAL_PATTERNS:
            if pattern.search(text):
                findings.append(Finding("ERROR", relative, "high-confidence credential pattern"))

        if path.suffix == ".json":
            try:
                json_documents[path.resolve()] = loads_strict(text)
            except ValueError as exc:
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

    adapter_schema_path = root / "schemas/adapter.schema.json"
    adapter_schema = json_documents.get(adapter_schema_path.resolve())
    adapter_ids: set[str] = set()
    outbound_operations: set[tuple[str, str]] = set()
    if isinstance(adapter_schema, dict):
        for manifest_path in sorted((root / "adapters").glob("*/adapter.json")):
            relative = manifest_path.relative_to(root).as_posix()
            manifest = json_documents.get(manifest_path.resolve())
            if not isinstance(manifest, dict):
                findings.append(Finding("ERROR", relative, "adapter manifest must be an object"))
                continue
            for issue in validate_schema(manifest, adapter_schema):
                findings.append(Finding("ERROR", relative, f"{issue.path}: {issue.message}"))
            adapter_id = manifest.get("id")
            if isinstance(adapter_id, str):
                if adapter_id in adapter_ids:
                    findings.append(
                        Finding("ERROR", relative, f"duplicate adapter id: {adapter_id}")
                    )
                else:
                    adapter_ids.add(adapter_id)
            manifest_slot_values = manifest.get("slots", [])
            if not isinstance(manifest_slot_values, list):
                manifest_slot_values = []
            manifest_slots = {str(slot) for slot in manifest_slot_values if isinstance(slot, str)}
            config_schema_ref = manifest.get("config_schema")
            if isinstance(config_schema_ref, str):
                config_path = (root / config_schema_ref).resolve()
                schema_root = (root / "schemas").resolve()
                if schema_root not in config_path.parents or not config_path.is_file():
                    findings.append(
                        Finding(
                            "ERROR",
                            relative,
                            f"unsafe or missing config_schema: {config_schema_ref}",
                        )
                    )
            operation_names: set[str] = set()
            operations = manifest.get("operations", [])
            if not isinstance(operations, list):
                operations = []
            for operation in operations:
                if not isinstance(operation, dict):
                    continue
                name = operation.get("name")
                if isinstance(name, str):
                    if name in operation_names:
                        findings.append(
                            Finding("ERROR", relative, f"duplicate adapter operation: {name}")
                        )
                    else:
                        operation_names.add(name)
                operation_slot_values = operation.get("slots", [])
                if not isinstance(operation_slot_values, list):
                    operation_slot_values = []
                operation_slots = {
                    str(slot) for slot in operation_slot_values if isinstance(slot, str)
                }
                if not operation_slots <= manifest_slots:
                    findings.append(
                        Finding(
                            "ERROR",
                            relative,
                            f"operation slots exceed adapter slots: {name}",
                        )
                    )
                if operation.get("direction") == "outbound" and isinstance(name, str):
                    outbound_operations.add((name, str(operation.get("capability"))))
                if operation.get("external_effect") == "write" and operation.get(
                    "delivery"
                ) not in {
                    "provider-idempotency",
                    "reconcile-before-retry",
                    "at-most-once",
                }:
                    findings.append(
                        Finding(
                            "ERROR",
                            relative,
                            f"write operation lacks bounded delivery: {name}",
                        )
                    )
                for field in ("input_schema", "output_schema"):
                    schema_ref = operation.get(field)
                    if not isinstance(schema_ref, str):
                        continue
                    referenced = (root / schema_ref).resolve()
                    schema_root = (root / "schemas").resolve()
                    if schema_root not in referenced.parents or not referenced.is_file():
                        findings.append(
                            Finding(
                                "ERROR",
                                relative,
                                f"unsafe or missing {field}: {schema_ref}",
                            )
                        )
                scope = operation.get("project_scope")
                input_schema_ref = operation.get("input_schema")
                if isinstance(scope, dict) and isinstance(input_schema_ref, str):
                    input_schema = json_documents.get((root / input_schema_ref).resolve())
                    input_properties = (
                        input_schema.get("properties", {}) if isinstance(input_schema, dict) else {}
                    )
                    if not isinstance(input_properties, dict):
                        input_properties = {}
                    for field_name in (
                        scope.get("payload_field"),
                        scope.get("default_branch_field"),
                        scope.get("source_ref_field"),
                    ):
                        if isinstance(field_name, str) and field_name not in input_properties:
                            findings.append(
                                Finding(
                                    "ERROR",
                                    relative,
                                    f"project scope field is absent from input schema: {field_name}",
                                )
                            )
            implementation = manifest.get("implementation", {})
            if isinstance(implementation, dict):
                mode = implementation.get("mode")
                entrypoint = implementation.get("entrypoint")
                if mode == "contract-only" and entrypoint is not None:
                    findings.append(
                        Finding("ERROR", relative, "contract-only adapter has an entrypoint")
                    )
                if mode == "python-reference" and not entrypoint:
                    findings.append(
                        Finding("ERROR", relative, "python-reference adapter lacks an entrypoint")
                    )

    authority_path = root / "policies/adapter-authority.json"
    authority_schema_path = root / "schemas/adapter-authority-policy.schema.json"
    authority = json_documents.get(authority_path.resolve())
    authority_schema = json_documents.get(authority_schema_path.resolve())
    if isinstance(authority, dict) and isinstance(authority_schema, dict):
        for issue in validate_schema(authority, authority_schema):
            findings.append(
                Finding(
                    "ERROR",
                    authority_path.relative_to(root).as_posix(),
                    f"{issue.path}: {issue.message}",
                )
            )
        authority_grants = authority.get("grants", [])
        if not isinstance(authority_grants, list):
            authority_grants = []
        granted = {
            (str(grant.get("operation")), str(grant.get("capability")))
            for grant in authority_grants
            if isinstance(grant, dict)
        }
        for operation in sorted(outbound_operations - granted):
            findings.append(
                Finding(
                    "ERROR",
                    authority_path.relative_to(root).as_posix(),
                    f"outbound adapter operation has no authority grant: {operation}",
                )
            )
        for operation in sorted(granted - outbound_operations):
            findings.append(
                Finding(
                    "ERROR",
                    authority_path.relative_to(root).as_posix(),
                    f"authority grant has no outbound adapter operation: {operation}",
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
        declared_contract_files = set(factory.get("contract_files", []))
        missing_contract_files = sorted(REQUIRED_CONTRACT_FILES - declared_contract_files)
        if missing_contract_files:
            findings.append(
                Finding(
                    "ERROR",
                    "factory-package.json",
                    f"required lifecycle contract files are undeclared: {missing_contract_files}",
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

    root_cli = root / "agent-team"
    if root_cli.is_file() and not root_cli.stat().st_mode & 0o100:
        findings.append(Finding("ERROR", "agent-team", "root CLI must be owner-executable"))

    design_path = root / "examples/context-first/team-design.json"
    design_schema_path = root / "schemas/team-design.schema.json"
    design = json_documents.get(design_path.resolve())
    design_schema = json_documents.get(design_schema_path.resolve())
    if isinstance(design, dict) and isinstance(design_schema, dict):
        for issue in validate_schema(design, design_schema):
            findings.append(
                Finding(
                    "ERROR",
                    design_path.relative_to(root).as_posix(),
                    f"{issue.path}: {issue.message}",
                )
            )
        role_ids = {
            str(role.get("id")) for role in design.get("roles", []) if isinstance(role, dict)
        }
        known_actors = role_ids | {"human.owner"}
        for role in design.get("roles", []):
            if not isinstance(role, dict):
                continue
            for handoff in role.get("handoffs", []):
                if isinstance(handoff, dict) and handoff.get("to") not in known_actors:
                    findings.append(
                        Finding(
                            "ERROR",
                            design_path.relative_to(root).as_posix(),
                            f"role {role.get('id')} hands off to an unknown actor",
                        )
                    )
    elif design_path.is_file() and design is not None:
        findings.append(
            Finding("ERROR", design_path.relative_to(root).as_posix(), "design example must be an object")
        )

    release_version = version_path.read_text(encoding="utf-8").strip() if version_path.is_file() else ""
    codex_marketplace_path = root / ".agents/plugins/marketplace.json"
    codex_manifest_path = root / ".agents/plugins/plugins/agent-team/.codex-plugin/plugin.json"
    claude_manifest_path = root / ".agents/plugins/plugins/agent-team/.claude-plugin/plugin.json"
    claude_marketplace_path = root / ".claude-plugin/marketplace.json"
    codex_marketplace = json_documents.get(codex_marketplace_path.resolve())
    codex_manifest = json_documents.get(codex_manifest_path.resolve())
    claude_manifest = json_documents.get(claude_manifest_path.resolve())
    claude_marketplace = json_documents.get(claude_marketplace_path.resolve())
    for relative, manifest in (
        (codex_manifest_path.relative_to(root).as_posix(), codex_manifest),
        (claude_manifest_path.relative_to(root).as_posix(), claude_manifest),
    ):
        if isinstance(manifest, dict):
            if manifest.get("name") != "agent-team":
                findings.append(Finding("ERROR", relative, "plugin name must be agent-team"))
            if manifest.get("version") != release_version:
                findings.append(Finding("ERROR", relative, "plugin version must match VERSION"))
            if manifest.get("license") != "Apache-2.0":
                findings.append(Finding("ERROR", relative, "plugin license must be Apache-2.0"))
    if isinstance(codex_marketplace, dict):
        plugins = codex_marketplace.get("plugins", [])
        if not isinstance(plugins, list) or len(plugins) != 1:
            findings.append(
                Finding("ERROR", codex_marketplace_path.relative_to(root).as_posix(), "marketplace must declare exactly one plugin")
            )
        else:
            source = plugins[0].get("source", {}) if isinstance(plugins[0], dict) else {}
            local_path = source.get("path") if isinstance(source, dict) else None
            if local_path != "./plugins/agent-team":
                findings.append(
                    Finding("ERROR", codex_marketplace_path.relative_to(root).as_posix(), "plugin source must resolve inside the marketplace")
                )
    if isinstance(claude_marketplace, dict):
        plugins = claude_marketplace.get("plugins", [])
        plugin = plugins[0] if isinstance(plugins, list) and len(plugins) == 1 else None
        if not isinstance(plugin, dict) or plugin.get("source") != "./.agents/plugins/plugins/agent-team":
            findings.append(
                Finding("ERROR", claude_marketplace_path.relative_to(root).as_posix(), "Claude marketplace must use the self-contained plugin bundle")
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

    takeover_path = root / "acceptance/cross-ai-takeover.json"
    takeover_schema_path = root / "schemas/cross-ai-takeover.schema.json"
    takeover = json_documents.get(takeover_path.resolve())
    takeover_schema = json_documents.get(takeover_schema_path.resolve())
    if isinstance(takeover, dict) and isinstance(takeover_schema, dict):
        for issue in validate_schema(takeover, takeover_schema):
            findings.append(
                Finding(
                    "ERROR",
                    takeover_path.relative_to(root).as_posix(),
                    f"{issue.path}: {issue.message}",
                )
            )
        for record in takeover.get("entrypoints", []):
            if not isinstance(record, dict) or not isinstance(record.get("path"), str):
                continue
            entrypoint = root / str(record["path"])
            if not entrypoint.is_file():
                findings.append(
                    Finding(
                        "ERROR",
                        takeover_path.relative_to(root).as_posix(),
                        f"takeover entrypoint is missing: {record['path']}",
                    )
                )
        for relative in takeover.get("required_documents", []):
            if isinstance(relative, str) and not (root / relative).is_file():
                findings.append(
                    Finding(
                        "ERROR",
                        takeover_path.relative_to(root).as_posix(),
                        f"takeover document is missing: {relative}",
                    )
                )

    return findings
