#!/usr/bin/env python3
"""Portable command line entrypoint for the reference engineering repository."""

from __future__ import annotations

import argparse
import json
import shlex
import sys
import tempfile
from pathlib import Path

# Installed Factory trees are manifest-verified and must not acquire undeclared bytecode.
sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.adapters import load_adapter_catalog  # noqa: E402
from core.adoption import (  # noqa: E402
    compose_instance_candidate,
    verify_adoption_proposal,
    write_adoption_proposal,
)
from core.approval import HMACApprovalVerifier  # noqa: E402
from core.context import write_context_bundle  # noqa: E402
from core.context_team import (  # noqa: E402
    PLATFORMS,
    build_design,
    create_context_team,
    export_context_target,
    inspect_context_team,
    list_presets,
    validate_context_team,
    validate_design_document,
)
from core.contracts import (  # noqa: E402
    CONTRACT_SCHEMAS,
    load_contract_file,
    validate_writer_authority,
)
from core.control_plane import ControlPlane  # noqa: E402
from core.doctor import build_doctor_report, doctor_exit_code  # noqa: E402
from core.installation import install_factory, verify_factory_installation  # noqa: E402
from core.instance import (  # noqa: E402
    init_instance,
    instance_summary,
    relock_instance,
    validate_instance_directory,
)
from core.json_support import loads_strict  # noqa: E402
from core.guided_adoption import (  # noqa: E402
    apply_plan as apply_guided_adoption_plan,
    build_plan as build_guided_adoption_plan,
    confirm_plan as confirm_guided_adoption_plan,
    inspect_project as inspect_guided_adoption_project,
    load_plan as load_guided_adoption_plan,
    preview_plan as preview_guided_adoption_plan,
    write_plan as write_guided_adoption_plan,
)
from core.host_catalog import (  # noqa: E402
    list_host_ids,
    load_host_catalog,
    probe_host,
)
from core.host_lifecycle import (  # noqa: E402
    apply_install_plan as apply_host_install_plan,
    build_install_plan as build_host_install_plan,
    confirm_install_plan as confirm_host_install_plan,
    load_install_plan as load_host_install_plan,
    preview_install_plan as preview_host_install_plan,
    preview_uninstall as preview_host_uninstall,
    uninstall_installation as uninstall_host_installation,
    verify_installation as verify_host_installation,
    write_install_plan as write_host_install_plan,
)
from core.lifecycle import (  # noqa: E402
    apply_instance_upgrade,
    inspect_recovery_bundle,
    recover_interrupted_lifecycle,
    rollback_instance,
    write_instance_upgrade_plan,
)
from core.models import Actor, FeedbackEvent  # noqa: E402
from core.native_controller import NativeController  # noqa: E402
from core.native_scenario import (  # noqa: E402
    load_reference_workflow,
    run_native_reference_scenario,
)
from core.simulation import run_feedback_to_release  # noqa: E402
from core.team_creator import (  # noqa: E402
    create_team,
    export_team_target,
    inspect_team,
    validate_team_directory,
)
from core.team_runtime import (  # noqa: E402
    approve_team_plan,
    create_reference_demo,
    ingest_team_feedback,
    run_team,
)
from core.validation import validate_repository  # noqa: E402


def command_doctor(args: argparse.Namespace) -> int:
    report = build_doctor_report(Path(args.instance) if args.instance else None)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return doctor_exit_code(report)


def command_factory_install(args: argparse.Namespace) -> int:
    report = install_factory(Path(args.output))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def command_factory_verify(args: argparse.Namespace) -> int:
    manifest = verify_factory_installation(Path(args.root))
    report = {
        "status": "VALID",
        "root": str(Path(args.root).resolve()),
        "installation_id": manifest["installation_id"],
        "factory_id": manifest["factory_id"],
        "factory_version": manifest["factory_version"],
        "source_revision": manifest["source_revision"],
        "source_tag": manifest["source_tag"],
        "release_verified": manifest["release_verified"],
        "tree_digest": manifest["tree_digest"],
        "files": len(manifest["files"]),
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def command_validate(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve() if args.root else ROOT
    findings = validate_repository(root)
    for finding in findings:
        print(f"{finding.severity} {finding.path}: {finding.message}")
    errors = [finding for finding in findings if finding.severity == "ERROR"]
    print(f"validated={root} errors={len(errors)} findings={len(findings)}")
    return 1 if errors else 0


def command_simulate(args: argparse.Namespace) -> int:
    input_path = (
        Path(args.input).resolve()
        if args.input
        else ROOT / "examples/feedback-to-release/input/feedback.json"
    )
    event = FeedbackEvent.from_dict(loads_strict(input_path.read_text(encoding="utf-8")))
    item = run_feedback_to_release(event, approve_production=args.approve_production)
    output = json.dumps(item.to_dict(), ensure_ascii=False, indent=2) + "\n"
    if args.output:
        target = Path(args.output).resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(output, encoding="utf-8")
    print(output, end="")
    return 0


def command_adopt(args: argparse.Namespace) -> int:
    report = write_adoption_proposal(
        Path(args.repo),
        Path(args.output),
        provider=args.provider,
        locator=args.locator,
        default_branch=args.default_branch,
        project_id=args.project_id,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def command_adoption_verify(args: argparse.Namespace) -> int:
    package = verify_adoption_proposal(Path(args.root))
    print(json.dumps(package, ensure_ascii=False, indent=2))
    return 0


def command_adoption_compose(args: argparse.Namespace) -> int:
    candidate = compose_instance_candidate(
        Path(args.base_config), Path(args.proposal), Path(args.output)
    )
    print(json.dumps(candidate, ensure_ascii=False, indent=2))
    return 0


def command_export_context(args: argparse.Namespace) -> int:
    write_context_bundle(ROOT, args.role, Path(args.output).resolve())
    print(
        json.dumps(
            {"role": args.role, "output": str(Path(args.output).resolve())}, ensure_ascii=False
        )
    )
    return 0


def command_instance_init(args: argparse.Namespace) -> int:
    summary = init_instance(Path(args.config), Path(args.output))
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def command_instance_validate(args: argparse.Namespace) -> int:
    root = Path(args.root)
    findings = validate_instance_directory(root)
    for finding in findings:
        print(f"{finding.severity} {finding.path}: {finding.message}")
    errors = sum(finding.severity == "ERROR" for finding in findings)
    warnings = sum(finding.severity == "WARNING" for finding in findings)
    print(f"validated_instance={root} errors={errors} warnings={warnings}")
    return 1 if errors else 0


def command_instance_inspect(args: argparse.Namespace) -> int:
    print(json.dumps(instance_summary(Path(args.root)), ensure_ascii=False, indent=2))
    return 0


def command_instance_relock(args: argparse.Namespace) -> int:
    summary = relock_instance(Path(args.root))
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def command_instance_upgrade_plan(args: argparse.Namespace) -> int:
    plan = write_instance_upgrade_plan(Path(args.root), Path(args.output))
    print(json.dumps(plan, ensure_ascii=False, indent=2))
    return 0


def command_instance_upgrade_apply(args: argparse.Namespace) -> int:
    result = apply_instance_upgrade(
        Path(args.root), Path(args.plan), Path(args.recovery)
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def command_instance_recover(args: argparse.Namespace) -> int:
    result = recover_interrupted_lifecycle(Path(args.root))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def command_instance_rollback(args: argparse.Namespace) -> int:
    result = rollback_instance(
        Path(args.root), Path(args.recovery), Path(args.rescue)
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def command_instance_recovery_inspect(args: argparse.Namespace) -> int:
    manifest = inspect_recovery_bundle(Path(args.bundle))
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


def command_team_create(args: argparse.Namespace) -> int:
    summary = create_team(Path(args.blueprint), Path(args.output))
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def command_team_validate(args: argparse.Namespace) -> int:
    root = Path(args.root)
    findings = validate_team_directory(root)
    for finding in findings:
        print(f"{finding.severity} {finding.path}: {finding.message}")
    errors = sum(finding.severity == "ERROR" for finding in findings)
    warnings = sum(finding.severity == "WARNING" for finding in findings)
    print(f"validated_team={root} errors={errors} warnings={warnings}")
    return 1 if errors else 0


def command_team_inspect(args: argparse.Namespace) -> int:
    print(json.dumps(inspect_team(Path(args.root)), ensure_ascii=False, indent=2))
    return 0


def command_team_export(args: argparse.Namespace) -> int:
    result = export_team_target(Path(args.root), args.target, Path(args.output))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def command_team_ingest(args: argparse.Namespace) -> int:
    result = ingest_team_feedback(
        Path(args.root),
        Path(args.event),
        idempotency_key=args.idempotency_key,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def command_team_run(args: argparse.Namespace) -> int:
    result = run_team(
        Path(args.root),
        args.work_item,
        Path(args.repo),
        Path(args.runner_profile),
        project_id=args.project_id,
        model_mode=args.model_mode,
        provider=args.provider,
        allow_host_runner=args.allow_host_runner,
        allow_provider_writes=args.allow_provider_writes,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def command_team_approve_plan(args: argparse.Namespace) -> int:
    result = approve_team_plan(Path(args.root), args.work_item, args.scope_hash)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def command_team_demo(args: argparse.Namespace) -> int:
    result = create_reference_demo(Path(args.output))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def _interactive_value(value: str | None, prompt: str, default: str | None = None) -> str:
    if value:
        return value
    if not sys.stdin.isatty():
        raise ValueError(f"missing required value: {prompt}")
    suffix = f" [{default}]" if default else ""
    entered = input(f"{prompt}{suffix}: ").strip()
    if entered:
        return entered
    if default is not None:
        return default
    raise ValueError(f"a value is required for: {prompt}")


def command_context_create(args: argparse.Namespace) -> int:
    if args.design:
        report = create_context_team(Path(args.design), Path(args.output))
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    if args.guided and not args.preset:
        return command_onboard_guided(
            argparse.Namespace(
                project_path=args.project_path,
                purpose=args.purpose,
                automation=args.automation,
                goal=args.goal,
                platform=args.platform,
                team_name=args.name,
                project_name=args.project,
                owner=args.owner,
                provider=args.provider,
                repository=args.repo,
                default_branch=args.default_branch,
                role=args.role,
                summary=args.summary,
                output=args.output,
                plan=args.plan,
            )
        )
    preset = args.preset
    if args.guided:
        preset = _interactive_value(preset, "Compiler preset", "software-lite")
    if not preset:
        raise ValueError("use --preset, --design, or --guided")
    name = _interactive_value(args.name, "Team name")
    project = _interactive_value(args.project, "Project name", name.removesuffix(" Team"))
    owner = _interactive_value(args.owner, "Human owner display name", "Project Owner")
    repository = _interactive_value(args.repo, "Repository locator", f"local/{project}")
    default_branch = _interactive_value(args.default_branch, "Default branch", "main")
    platforms = args.platform or ["generic-ai"]
    provider = args.provider
    if provider is None:
        looks_like_github = (
            repository.count("/") == 1
            and "://" not in repository
            and not repository.startswith(("local/", "file/"))
        )
        provider = "github" if looks_like_github else "generic-git"
    design = build_design(
        preset,
        team_name=name,
        project_name=project,
        repository=repository,
        provider=provider,
        default_branch=default_branch,
        owner_name=owner,
        platforms=platforms,
        custom_roles=args.role,
        summary=args.summary,
    )
    with tempfile.TemporaryDirectory(prefix="agent-team-design-") as temporary:
        design_path = Path(temporary) / "team-design.json"
        design_path.write_text(
            json.dumps(design, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        report = create_context_team(design_path, Path(args.output))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def command_context_validate(args: argparse.Namespace) -> int:
    findings = validate_context_team(Path(args.root))
    for finding in findings:
        print(f"{finding.severity} {finding.path}: {finding.message}")
    errors = sum(finding.severity == "ERROR" for finding in findings)
    warnings = sum(finding.severity == "WARNING" for finding in findings)
    print(f"validated_context_team={args.root} errors={errors} warnings={warnings}")
    return 1 if errors else 0


def command_context_inspect(args: argparse.Namespace) -> int:
    print(json.dumps(inspect_context_team(Path(args.root)), ensure_ascii=False, indent=2))
    return 0


def command_context_export(args: argparse.Namespace) -> int:
    report = export_context_target(Path(args.root), args.target, Path(args.output))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def command_context_design_validate(args: argparse.Namespace) -> int:
    document = _load_json_object(args.file)
    findings = validate_design_document(document)
    for finding in findings:
        print(f"{finding.severity} {finding.path}: {finding.message}")
    errors = sum(finding.severity == "ERROR" for finding in findings)
    print(f"validated_team_design={args.file} errors={errors}")
    return 1 if errors else 0


def command_presets(_: argparse.Namespace) -> int:
    print(json.dumps({"presets": list_presets()}, ensure_ascii=False, indent=2))
    return 0


def command_onboard_inspect(args: argparse.Namespace) -> int:
    report = inspect_guided_adoption_project(Path(args.project_path))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def _build_onboarding_plan_from_args(args: argparse.Namespace) -> dict:
    return build_guided_adoption_plan(
        Path(args.project_path),
        purpose=args.purpose,
        goals=args.goal,
        automation=args.automation,
        platforms=args.platform,
        team_name=args.team_name,
        project_name=args.project_name,
        owner=args.owner,
        provider=args.provider,
        repository=args.repository,
        default_branch=args.default_branch,
        output_path=Path(args.output),
        custom_roles=args.role,
        summary=args.summary,
    )


def command_onboard_plan(args: argparse.Namespace) -> int:
    plan = _build_onboarding_plan_from_args(args)
    write_guided_adoption_plan(plan, Path(args.plan))
    print(
        json.dumps(
            {
                "status": "PLANNED",
                "schema_version": plan["schema_version"],
                "state": plan["state"],
                "plan": str(Path(args.plan).resolve()),
                "proposal_digest": plan["proposal_digest"],
                "recommendation": plan["proposal"]["recommendation"],
                "target_project_mutated": False,
                "next": "preview the plan, then confirm its exact digest",
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def command_onboard_validate(args: argparse.Namespace) -> int:
    plan = load_guided_adoption_plan(Path(args.plan))
    print(
        json.dumps(
            {
                "status": "VALID",
                "plan": str(Path(args.plan).resolve()),
                "state": plan["state"],
                "plan_id": plan["plan_id"],
                "proposal_digest": plan["proposal_digest"],
                "target_project_mutated": False,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def command_onboard_preview(args: argparse.Namespace) -> int:
    plan_path = Path(args.plan).resolve()
    plan = load_guided_adoption_plan(plan_path)
    quoted_plan = shlex.quote(str(plan_path))
    quoted_output = shlex.quote(plan["proposal"]["team"]["output_path"])
    print(preview_guided_adoption_plan(plan), end="")
    print(
        "\nNext only after the human owner approves this exact digest:\n\n"
        f"./agent-team onboard confirm --plan {quoted_plan} "
        f"--digest {plan['proposal_digest']} --approved-by \"<Human Owner>\"\n"
        f"./agent-team onboard apply --plan {quoted_plan}\n"
        f"./agent-team context validate --root {quoted_output}\n"
    )
    return 0


def command_onboard_confirm(args: argparse.Namespace) -> int:
    plan = confirm_guided_adoption_plan(
        Path(args.plan), digest=args.digest, approved_by=args.approved_by
    )
    print(
        json.dumps(
            {
                "status": "CONFIRMED",
                "plan": str(Path(args.plan).resolve()),
                "proposal_digest": plan["proposal_digest"],
                "scope": plan["confirmation"]["scope"],
                "external_writes_authorized": False,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def command_onboard_apply(args: argparse.Namespace) -> int:
    report = apply_guided_adoption_plan(Path(args.plan))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def _split_interactive_values(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def command_onboard_guided(args: argparse.Namespace) -> int:
    project_path = _interactive_value(
        args.project_path,
        "Target project directory (read-only inspection)",
        str(Path.cwd()),
    )
    source = Path(project_path).resolve()
    purpose = _interactive_value(
        args.purpose,
        "Team purpose: software, research-knowledge, content, operations, or custom",
        "software",
    )
    automation = _interactive_value(
        args.automation,
        "Automation: files, assisted, or managed-to-reviewed-Draft-PR",
        "assisted",
    )
    raw_platforms = _interactive_value(
        ",".join(args.platform) if args.platform else None,
        "AI hosts (comma-separated: codex, claude, openclaw, hermes, multica, generic-ai)",
        "generic-ai",
    )
    goal = args.goal or [
        _interactive_value(None, "What outcome should this team help produce?")
    ]
    project_name = _interactive_value(args.project_name, "Project name", source.name)
    team_name = _interactive_value(args.team_name, "Team name", f"{project_name} Team")
    owner = _interactive_value(args.owner, "Human owner display name", "Project Owner")
    repository = _interactive_value(
        args.repository,
        "Repository locator",
        f"local/{source.name}",
    )
    provider = args.provider
    if provider is None:
        looks_like_github = (
            repository.count("/") == 1
            and "://" not in repository
            and not repository.startswith(("local/", "file/"))
        )
        provider = "github" if looks_like_github else "generic-git"
    roles = args.role
    if purpose == "custom" and not roles:
        roles = _split_interactive_values(
            _interactive_value(
                None,
                "Roles (comma-separated role-id:Display Name)",
            )
        )
    output = Path(args.output).resolve()
    plan_path = (
        Path(args.plan).resolve()
        if args.plan
        else output.with_name(output.name + "-adoption-plan.json")
    )
    plan = build_guided_adoption_plan(
        source,
        purpose=purpose,
        goals=goal,
        automation=automation,
        platforms=_split_interactive_values(raw_platforms),
        team_name=team_name,
        project_name=project_name,
        owner=owner,
        provider=provider,
        repository=repository,
        default_branch=args.default_branch,
        output_path=output,
        custom_roles=roles,
        summary=args.summary,
    )
    write_guided_adoption_plan(plan, plan_path)
    print(preview_guided_adoption_plan(plan), end="")
    if not sys.stdin.isatty():
        raise ValueError(
            f"guided confirmation requires an interactive terminal; draft plan saved at {plan_path}"
        )
    answer = input("Type yes to create this exact team, or anything else to stop: ").strip()
    if answer.casefold() != "yes":
        print(
            json.dumps(
                {
                    "status": "AWAITING_CONFIRMATION",
                    "plan": str(plan_path),
                    "proposal_digest": plan["proposal_digest"],
                    "team_created": False,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    confirm_guided_adoption_plan(
        plan_path,
        digest=plan["proposal_digest"],
        approved_by=owner,
    )
    report = apply_guided_adoption_plan(plan_path)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def _load_json_object(path: str) -> dict:
    target = Path(path).resolve()
    value = loads_strict(target.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON root must be an object: {target}")
    return value


def _runtime_database(instance: str) -> tuple[Path, Path]:
    supplied_root = Path(instance)
    if supplied_root.is_symlink():
        raise RuntimeError("instance root must not be a symbolic link")
    instance_root = supplied_root.resolve()
    journal = instance_root / "runtime" / ".factory-lifecycle-journal.json"
    if journal.exists() or journal.is_symlink():
        raise RuntimeError("instance lifecycle recovery is required before runtime operations")
    findings = validate_instance_directory(instance_root)
    errors = [finding for finding in findings if finding.severity == "ERROR"]
    if errors:
        details = "; ".join(f"{finding.path}: {finding.message}" for finding in errors)
        raise RuntimeError(f"instance is invalid: {details}")
    document = _load_json_object(str(instance_root / ".agent-team" / "instance.json"))
    database = (instance_root / document["runtime"]["state_location"]).resolve()
    if instance_root not in database.parents:
        raise RuntimeError("runtime database must remain inside the instance root")
    return instance_root, database


def command_runtime_init(args: argparse.Namespace) -> int:
    instance_root, database = _runtime_database(args.instance)
    with ControlPlane(database, create=True) as control:
        report = control.status()
        report["instance_root"] = str(instance_root)
        report["database"] = str(database)
        print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def command_runtime_status(args: argparse.Namespace) -> int:
    _, database = _runtime_database(args.instance)
    with ControlPlane(database, create=False) as control:
        print(json.dumps(control.status(), ensure_ascii=False, indent=2))
    return 0


def command_runtime_ingest(args: argparse.Namespace) -> int:
    _, database = _runtime_database(args.instance)
    event = FeedbackEvent.from_dict(_load_json_object(args.event))
    with ControlPlane(database, create=False) as control:
        result = control.ingest_feedback(event, idempotency_key=args.idempotency_key)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def command_runtime_lease(args: argparse.Namespace) -> int:
    _, database = _runtime_database(args.instance)
    actor = Actor(args.actor_id, args.role, kind="agent")
    with ControlPlane(database, create=False) as control:
        result = control.acquire_lease(
            args.work_item,
            actor,
            expected_revision=args.expected_revision,
            ttl_seconds=args.ttl_seconds,
            idempotency_key=args.idempotency_key,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def command_runtime_apply(args: argparse.Namespace) -> int:
    _, database = _runtime_database(args.instance)
    actor = Actor(args.actor_id, args.role, kind=args.actor_kind)
    evidence = _load_json_object(args.evidence)
    approval_inputs = (
        args.approval_assertion,
        args.approval_key_file,
        args.approval_provider,
    )
    if any(approval_inputs) and not all(approval_inputs):
        raise ValueError("approval assertion, key file, and provider must be supplied together")
    approval_assertion = (
        _load_json_object(args.approval_assertion) if args.approval_assertion else None
    )
    verifier = None
    if args.approval_key_file:
        key_path = Path(args.approval_key_file)
        if key_path.is_symlink() or not key_path.is_file():
            raise ValueError("approval key must be a regular non-symlink file")
        if key_path.stat().st_mode & 0o077:
            raise ValueError("approval key file must deny group and other access")
        verifier = HMACApprovalVerifier(args.approval_provider, key_path.read_bytes())
    with ControlPlane(database, create=False, approval_verifier=verifier) as control:
        result = control.apply_transition(
            args.work_item,
            args.action,
            actor,
            evidence,
            expected_revision=args.expected_revision,
            idempotency_key=args.idempotency_key,
            lease_id=args.lease_id,
            approval_assertion=approval_assertion,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def command_runtime_pause(args: argparse.Namespace) -> int:
    _, database = _runtime_database(args.instance)
    owner = Actor(args.owner_id, "owner", kind="human")
    with ControlPlane(database, create=False) as control:
        result = control.set_paused(
            args.paused,
            owner,
            reason=args.reason,
            idempotency_key=args.idempotency_key,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def command_runtime_reconcile(args: argparse.Namespace) -> int:
    _, database = _runtime_database(args.instance)
    with ControlPlane(database, create=False) as control:
        print(json.dumps(control.reconcile(), ensure_ascii=False, indent=2))
    return 0


def command_runtime_verify_audit(args: argparse.Namespace) -> int:
    _, database = _runtime_database(args.instance)
    with ControlPlane(database, create=False) as control:
        print(json.dumps(control.verify_audit(), ensure_ascii=False, indent=2))
    return 0


def command_runtime_backup(args: argparse.Namespace) -> int:
    _, database = _runtime_database(args.instance)
    with ControlPlane(database, create=False) as control:
        print(json.dumps(control.backup(Path(args.output)), ensure_ascii=False, indent=2))
    return 0


def command_runtime_restore(args: argparse.Namespace) -> int:
    _, database = _runtime_database(args.instance)
    print(
        json.dumps(
            ControlPlane.restore(Path(args.backup), database),
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def command_adapter_catalog(_: argparse.Namespace) -> int:
    catalog = load_adapter_catalog()
    report = {
        "schema_version": "1.0.0",
        "adapters": [catalog[key].summary() for key in sorted(catalog)],
        "dynamic_loading_enabled": False,
        "production_integrations_enabled": False,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def command_host_list(_: argparse.Namespace) -> int:
    catalog = load_host_catalog()
    hosts = []
    for host_id in sorted(catalog):
        descriptor = catalog[host_id]
        hosts.append(
            {
                "id": host_id,
                "display_name": descriptor["display_name"],
                "support_tier": descriptor["support_tier"],
                "integration_mode": descriptor["integration_mode"],
                "capabilities": descriptor["capabilities"],
                "limitations": descriptor["limitations"],
            }
        )
    print(
        json.dumps(
            {
                "schema_version": "1.0.0",
                "hosts": hosts,
                "live_configuration_read": False,
                "external_integrations_enabled": False,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def command_host_probe(args: argparse.Namespace) -> int:
    print(json.dumps(probe_host(args.target), ensure_ascii=False, indent=2))
    return 0


def command_host_plan(args: argparse.Namespace) -> int:
    plan = build_host_install_plan(
        Path(args.team),
        args.target,
        Path(args.destination),
    )
    write_host_install_plan(plan, Path(args.output))
    print(
        json.dumps(
            {
                "status": "PLANNED",
                "state": plan["state"],
                "plan": str(Path(args.output).resolve()),
                "proposal_digest": plan["proposal_digest"],
                "host": plan["proposal"]["host"],
                "destination": plan["proposal"]["destination"],
                "managed_files": len(plan["proposal"]["files"]),
                "lifecycle": plan["proposal"]["lifecycle"],
                "external_writes": False,
                "next": "preview the plan, then confirm its exact digest",
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def command_host_preview(args: argparse.Namespace) -> int:
    plan_path = Path(args.plan).resolve()
    plan = load_host_install_plan(plan_path)
    quoted_plan = shlex.quote(str(plan_path))
    quoted_destination = shlex.quote(plan["proposal"]["destination"])
    print(preview_host_install_plan(plan), end="")
    if plan["state"] == "DRAFT":
        print(
            "Next only after the human owner approves this exact digest:\n\n"
            f"./agent-team host confirm --plan {quoted_plan} "
            f"--digest {plan['proposal_digest']} --approved-by \"<Human Owner>\"\n"
            f"./agent-team host apply --plan {quoted_plan}\n"
            f"./agent-team host verify --root {quoted_destination}\n"
        )
    else:
        print(
            "This exact proposal is already confirmed. Next:\n\n"
            f"./agent-team host apply --plan {quoted_plan}\n"
            f"./agent-team host verify --root {quoted_destination}\n"
        )
    return 0


def command_host_confirm(args: argparse.Namespace) -> int:
    plan = confirm_host_install_plan(
        Path(args.plan),
        digest=args.digest,
        approved_by=args.approved_by,
    )
    print(
        json.dumps(
            {
                "status": "CONFIRMED",
                "plan": str(Path(args.plan).resolve()),
                "proposal_digest": plan["proposal_digest"],
                "scope": plan["confirmation"]["scope"],
                "external_writes_authorized": False,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def command_host_apply(args: argparse.Namespace) -> int:
    print(
        json.dumps(
            apply_host_install_plan(Path(args.plan)),
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def command_host_verify(args: argparse.Namespace) -> int:
    print(
        json.dumps(
            verify_host_installation(Path(args.root)),
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def command_host_uninstall_preview(args: argparse.Namespace) -> int:
    print(
        json.dumps(
            preview_host_uninstall(Path(args.root)),
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def command_host_uninstall(args: argparse.Namespace) -> int:
    print(
        json.dumps(
            uninstall_host_installation(Path(args.root), digest=args.digest),
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def command_native_contract_validate(args: argparse.Namespace) -> int:
    document = load_contract_file(args.contract, Path(args.file).resolve())
    print(
        json.dumps(
            {
                "status": "VALID",
                "contract": args.contract,
                "schema": document.get("$schema"),
                "file": str(Path(args.file).resolve()),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def command_native_writer_authority_validate(args: argparse.Namespace) -> int:
    topology = load_contract_file("writer_topology", Path(args.topology).resolve())
    plan = load_contract_file("plan_revision", Path(args.plan).resolve())
    approval = load_contract_file("approval_grant", Path(args.approval).resolve())
    issues = validate_writer_authority(topology, plan, approval)
    if issues:
        detail = "; ".join(f"{issue.path}: {issue.message}" for issue in issues)
        raise ValueError(f"invalid writer authority chain: {detail}")
    print(
        json.dumps(
            {
                "status": "VALID",
                "topology_id": topology["topology_id"],
                "topology_digest": topology["topology_digest"],
                "plan_digest": plan["plan_digest"],
                "approval_scope_digest": approval["scope_digest"],
                "automatic_execution": False,
                "identity_or_signature_verified": False,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def command_native_demo(args: argparse.Namespace) -> int:
    result = run_native_reference_scenario(Path(args.database))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def command_native_status(args: argparse.Namespace) -> int:
    with NativeController(
        Path(args.database), load_reference_workflow(), create=False
    ) as controller:
        print(json.dumps(controller.status(), ensure_ascii=False, indent=2))
    return 0


def command_native_verify(args: argparse.Namespace) -> int:
    with NativeController(
        Path(args.database), load_reference_workflow(), create=False
    ) as controller:
        print(json.dumps(controller.verify_invariants(), ensure_ascii=False, indent=2))
    return 0


def command_native_recover(args: argparse.Namespace) -> int:
    with NativeController(
        Path(args.database), load_reference_workflow(), create=False
    ) as controller:
        print(json.dumps(controller.recover_orphans(), ensure_ascii=False, indent=2))
    return 0


def command_native_backup(args: argparse.Namespace) -> int:
    with NativeController(
        Path(args.database), load_reference_workflow(), create=False
    ) as controller:
        print(json.dumps(controller.backup(Path(args.output)), ensure_ascii=False, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agent-team", description=__doc__)
    parser.add_argument(
        "--version",
        action="version",
        version=(ROOT / "VERSION").read_text(encoding="utf-8").strip(),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    create = subparsers.add_parser(
        "create", help="create a context-first Agent Team from a preset or design"
    )
    create.add_argument("--guided", action="store_true", help="prompt for missing values")
    create.add_argument(
        "--preset", choices=("software-lite", "software-managed", "custom")
    )
    create.add_argument("--design", help="use a complete team-design JSON file")
    create.add_argument("--project-path", help="target project directory for read-only discovery")
    create.add_argument(
        "--purpose",
        choices=("software", "research-knowledge", "content", "operations", "custom"),
    )
    create.add_argument("--automation", choices=("files", "assisted", "managed"))
    create.add_argument("--goal", action="append")
    create.add_argument("--plan", help="new guided adoption plan JSON path")
    create.add_argument("--name", help="team display name")
    create.add_argument("--project", help="target project display name")
    create.add_argument("--repo", help="repository locator such as owner/repo or a local label")
    create.add_argument(
        "--provider", choices=("github", "gitlab", "gitea", "generic-git")
    )
    create.add_argument("--default-branch", default="main")
    create.add_argument("--owner", default="Project Owner")
    create.add_argument("--summary")
    create.add_argument(
        "--platform",
        action="append",
        choices=PLATFORMS,
        help="repeat to generate more than one platform adapter",
    )
    create.add_argument(
        "--role",
        action="append",
        help="custom role as role-id or role-id:Display Name; repeat for multiple roles",
    )
    create.add_argument("--output", required=True)
    create.set_defaults(func=command_context_create)

    presets = subparsers.add_parser("presets", help="list built-in context-first team presets")
    presets.set_defaults(func=command_presets)

    onboard = subparsers.add_parser(
        "onboard",
        help="turn a user outcome into a previewed, confirmed, and validated Agent Team",
    )
    onboard_commands = onboard.add_subparsers(dest="onboard_command", required=True)
    onboard_inspect = onboard_commands.add_parser(
        "inspect", help="inspect a target project read-only without creating files"
    )
    onboard_inspect.add_argument("--project-path", required=True)
    onboard_inspect.set_defaults(func=command_onboard_inspect)

    onboard_plan = onboard_commands.add_parser(
        "plan", help="create a strict draft proposal from an already clarified user intent"
    )
    onboard_plan.add_argument("--project-path", required=True)
    onboard_plan.add_argument(
        "--purpose",
        choices=("software", "research-knowledge", "content", "operations", "custom"),
        required=True,
    )
    onboard_plan.add_argument(
        "--automation", choices=("files", "assisted", "managed"), required=True
    )
    onboard_plan.add_argument("--goal", action="append", required=True)
    onboard_plan.add_argument(
        "--platform",
        action="append",
        choices=PLATFORMS,
        required=True,
    )
    onboard_plan.add_argument("--team-name", required=True)
    onboard_plan.add_argument("--project-name")
    onboard_plan.add_argument("--owner", default="Project Owner")
    onboard_plan.add_argument(
        "--provider",
        choices=("github", "gitlab", "gitea", "generic-git"),
        default="generic-git",
    )
    onboard_plan.add_argument("--repository")
    onboard_plan.add_argument("--default-branch")
    onboard_plan.add_argument("--role", action="append")
    onboard_plan.add_argument("--summary")
    onboard_plan.add_argument("--output", required=True, help="new team directory to create later")
    onboard_plan.add_argument("--plan", required=True, help="new plan JSON path")
    onboard_plan.set_defaults(func=command_onboard_plan)

    onboard_validate = onboard_commands.add_parser(
        "validate", help="validate plan schema, digest, confirmation, paths, and safety boundary"
    )
    onboard_validate.add_argument("--plan", required=True)
    onboard_validate.set_defaults(func=command_onboard_validate)
    onboard_preview = onboard_commands.add_parser(
        "preview", help="show a human-readable proposal without applying it"
    )
    onboard_preview.add_argument("--plan", required=True)
    onboard_preview.set_defaults(func=command_onboard_preview)
    onboard_confirm = onboard_commands.add_parser(
        "confirm", help="bind local team-creation approval to the exact proposal digest"
    )
    onboard_confirm.add_argument("--plan", required=True)
    onboard_confirm.add_argument("--digest", required=True)
    onboard_confirm.add_argument("--approved-by", required=True)
    onboard_confirm.set_defaults(func=command_onboard_confirm)
    onboard_apply = onboard_commands.add_parser(
        "apply", help="create and validate a team from an exact confirmed plan"
    )
    onboard_apply.add_argument("--plan", required=True)
    onboard_apply.set_defaults(func=command_onboard_apply)

    onboard_guided = onboard_commands.add_parser(
        "guided", help="interactive scenario interview, preview, confirmation, and creation"
    )
    onboard_guided.add_argument("--project-path")
    onboard_guided.add_argument(
        "--purpose",
        choices=("software", "research-knowledge", "content", "operations", "custom"),
    )
    onboard_guided.add_argument("--automation", choices=("files", "assisted", "managed"))
    onboard_guided.add_argument("--goal", action="append")
    onboard_guided.add_argument(
        "--platform",
        action="append",
        choices=PLATFORMS,
    )
    onboard_guided.add_argument("--team-name")
    onboard_guided.add_argument("--project-name")
    onboard_guided.add_argument("--owner")
    onboard_guided.add_argument(
        "--provider", choices=("github", "gitlab", "gitea", "generic-git")
    )
    onboard_guided.add_argument("--repository")
    onboard_guided.add_argument("--default-branch")
    onboard_guided.add_argument("--role", action="append")
    onboard_guided.add_argument("--summary")
    onboard_guided.add_argument("--output", required=True)
    onboard_guided.add_argument("--plan")
    onboard_guided.set_defaults(func=command_onboard_guided)

    host = subparsers.add_parser(
        "host", help="discover and safely install a team projection for an AI host"
    )
    host_commands = host.add_subparsers(dest="host_command", required=True)
    host_choices = list_host_ids()
    host_list = host_commands.add_parser(
        "list", help="list versioned host capabilities and evidence tiers without probing"
    )
    host_list.set_defaults(func=command_host_list)
    host_probe = host_commands.add_parser(
        "probe", help="run only the selected host's isolated local version command"
    )
    host_probe.add_argument("--target", choices=host_choices, required=True)
    host_probe.set_defaults(func=command_host_probe)
    host_plan = host_commands.add_parser(
        "plan", help="create a zero-external-write plan for factory-managed host files"
    )
    host_plan.add_argument("--team", required=True, help="validated context-first team root")
    host_plan.add_argument("--target", choices=host_choices, required=True)
    host_plan.add_argument("--destination", required=True)
    host_plan.add_argument("--output", required=True, help="new host plan JSON path")
    host_plan.set_defaults(func=command_host_plan)
    host_preview = host_commands.add_parser(
        "preview", help="show the exact host installation proposal without applying it"
    )
    host_preview.add_argument("--plan", required=True)
    host_preview.set_defaults(func=command_host_preview)
    host_confirm = host_commands.add_parser(
        "confirm", help="bind approval to one exact host installation proposal digest"
    )
    host_confirm.add_argument("--plan", required=True)
    host_confirm.add_argument("--digest", required=True)
    host_confirm.add_argument("--approved-by", required=True)
    host_confirm.set_defaults(func=command_host_confirm)
    host_apply = host_commands.add_parser(
        "apply", help="create only absent factory-managed files from a confirmed plan"
    )
    host_apply.add_argument("--plan", required=True)
    host_apply.set_defaults(func=command_host_apply)
    host_verify = host_commands.add_parser(
        "verify", help="verify every managed host file against its installation lock"
    )
    host_verify.add_argument("--root", required=True)
    host_verify.set_defaults(func=command_host_verify)
    host_uninstall_preview = host_commands.add_parser(
        "uninstall-preview",
        help="show exact managed-file deletion and retained lifecycle evidence without mutation",
    )
    host_uninstall_preview.add_argument("--root", required=True)
    host_uninstall_preview.set_defaults(func=command_host_uninstall_preview)
    host_uninstall = host_commands.add_parser(
        "uninstall", help="remove only unchanged managed files using the exact lock digest"
    )
    host_uninstall.add_argument("--root", required=True)
    host_uninstall.add_argument("--digest", required=True)
    host_uninstall.set_defaults(func=command_host_uninstall)

    context_team = subparsers.add_parser(
        "context", help="validate, inspect, or export a context-first team"
    )
    context_commands = context_team.add_subparsers(dest="context_command", required=True)
    context_validate = context_commands.add_parser(
        "validate", help="verify design, digest lock, generated context, and managed runtime"
    )
    context_validate.add_argument("--root", required=True)
    context_validate.set_defaults(func=command_context_validate)
    context_inspect = context_commands.add_parser(
        "inspect", help="show a secret-safe context team summary"
    )
    context_inspect.add_argument("--root", required=True)
    context_inspect.set_defaults(func=command_context_inspect)
    context_export = context_commands.add_parser(
        "export", help="export one platform adapter with its authoritative shared context"
    )
    context_export.add_argument(
        "--target", choices=PLATFORMS, required=True
    )
    context_export.add_argument("--root", required=True)
    context_export.add_argument("--output", required=True)
    context_export.set_defaults(func=command_context_export)
    design_validate = context_commands.add_parser(
        "design-validate", help="validate one team-design JSON before compiling it"
    )
    design_validate.add_argument("--file", required=True)
    design_validate.set_defaults(func=command_context_design_validate)

    doctor = subparsers.add_parser("doctor", help="report portable runtime prerequisites")
    doctor.add_argument("--instance")
    doctor.set_defaults(func=command_doctor)

    factory = subparsers.add_parser("factory", help="install or verify an immutable Factory")
    factory_commands = factory.add_subparsers(dest="factory_command", required=True)
    factory_install = factory_commands.add_parser(
        "install", help="atomically install the current annotated release"
    )
    factory_install.add_argument("--output", required=True)
    factory_install.set_defaults(func=command_factory_install)
    factory_verify = factory_commands.add_parser(
        "verify", help="verify an installed Factory manifest and every file"
    )
    factory_verify.add_argument("--root", required=True)
    factory_verify.set_defaults(func=command_factory_verify)

    validate = subparsers.add_parser(
        "validate", help="validate repository contracts and safety gates"
    )
    validate.add_argument("--root")
    validate.set_defaults(func=command_validate)

    simulate = subparsers.add_parser(
        "simulate", help="run the side-effect-free feedback-to-release scenario"
    )
    simulate.add_argument("--input")
    simulate.add_argument("--output")
    simulate.add_argument("--approve-production", action="store_true")
    simulate.set_defaults(func=command_simulate)

    adopt = subparsers.add_parser(
        "adopt-project", help="create a proposal outside an existing project"
    )
    adopt.add_argument("--repo", required=True)
    adopt.add_argument("--output", required=True)
    adopt.add_argument(
        "--provider",
        choices=("github", "gitlab", "gitea", "generic-git"),
        default="generic-git",
    )
    adopt.add_argument("--locator")
    adopt.add_argument("--default-branch")
    adopt.add_argument("--project-id")
    adopt.set_defaults(func=command_adopt)

    adoption = subparsers.add_parser(
        "adoption", help="verify a proposal or compose a candidate instance config"
    )
    adoption_commands = adoption.add_subparsers(dest="adoption_command", required=True)
    adoption_verify = adoption_commands.add_parser(
        "verify", help="verify proposal hashes, schemas, scope, and secret safety"
    )
    adoption_verify.add_argument("--root", required=True)
    adoption_verify.set_defaults(func=command_adoption_verify)
    adoption_compose = adoption_commands.add_parser(
        "compose", help="add one proposal-only project to a new candidate config"
    )
    adoption_compose.add_argument("--base-config", required=True)
    adoption_compose.add_argument("--proposal", required=True)
    adoption_compose.add_argument("--output", required=True)
    adoption_compose.set_defaults(func=command_adoption_compose)

    export_context = subparsers.add_parser(
        "export-context", help="export a bounded role context bundle"
    )
    export_context.add_argument("--role", required=True)
    export_context.add_argument("--output", required=True)
    export_context.set_defaults(func=command_export_context)

    instance = subparsers.add_parser(
        "instance", help="create and govern a declarative team instance"
    )
    instance_commands = instance.add_subparsers(dest="instance_command", required=True)

    instance_init = instance_commands.add_parser(
        "init", help="atomically create a new instance directory"
    )
    instance_init.add_argument("--config", required=True)
    instance_init.add_argument("--output", required=True)
    instance_init.set_defaults(func=command_instance_init)

    instance_validate = instance_commands.add_parser(
        "validate", help="validate instance authority and locked files"
    )
    instance_validate.add_argument("--root", required=True)
    instance_validate.set_defaults(func=command_instance_validate)

    instance_inspect = instance_commands.add_parser(
        "inspect", help="show a non-secret instance summary"
    )
    instance_inspect.add_argument("--root", required=True)
    instance_inspect.set_defaults(func=command_instance_inspect)

    instance_relock = instance_commands.add_parser(
        "relock", help="accept a validated instance configuration change"
    )
    instance_relock.add_argument("--root", required=True)
    instance_relock.set_defaults(func=command_instance_relock)

    instance_upgrade = instance_commands.add_parser(
        "upgrade", help="plan or apply a versioned instance upgrade"
    )
    upgrade_commands = instance_upgrade.add_subparsers(
        dest="instance_upgrade_command", required=True
    )
    upgrade_plan = upgrade_commands.add_parser(
        "plan", help="write a digest-bound upgrade plan outside the instance"
    )
    upgrade_plan.add_argument("--root", required=True)
    upgrade_plan.add_argument("--output", required=True)
    upgrade_plan.set_defaults(func=command_instance_upgrade_plan)
    upgrade_apply = upgrade_commands.add_parser(
        "apply", help="apply a fresh plan after creating an external recovery bundle"
    )
    upgrade_apply.add_argument("--root", required=True)
    upgrade_apply.add_argument("--plan", required=True)
    upgrade_apply.add_argument("--recovery", required=True)
    upgrade_apply.set_defaults(func=command_instance_upgrade_apply)
    instance_recover = instance_commands.add_parser(
        "recover", help="restore the pre-operation release from a lifecycle journal"
    )
    instance_recover.add_argument("--root", required=True)
    instance_recover.set_defaults(func=command_instance_recover)

    instance_rollback = instance_commands.add_parser(
        "rollback", help="restore a verified recovery bundle and preserve a rescue bundle"
    )
    instance_rollback.add_argument("--root", required=True)
    instance_rollback.add_argument("--recovery", required=True)
    instance_rollback.add_argument("--rescue", required=True)
    instance_rollback.set_defaults(func=command_instance_rollback)

    instance_recovery = instance_commands.add_parser(
        "recovery-inspect", help="verify and inspect an external recovery bundle"
    )
    instance_recovery.add_argument("--bundle", required=True)
    instance_recovery.set_defaults(func=command_instance_recovery_inspect)

    team = subparsers.add_parser(
        "team", help="compile and verify a runnable cross-platform agent team"
    )
    team_commands = team.add_subparsers(dest="team_command", required=True)
    team_create = team_commands.add_parser(
        "create", help="atomically compile a strict team blueprint into a new directory"
    )
    team_create.add_argument("--blueprint", required=True)
    team_create.add_argument("--output", required=True)
    team_create.set_defaults(func=command_team_create)
    team_validate = team_commands.add_parser(
        "validate", help="verify blueprint, instance, lock, and every compiled platform file"
    )
    team_validate.add_argument("--root", required=True)
    team_validate.set_defaults(func=command_team_validate)
    team_inspect = team_commands.add_parser(
        "inspect", help="show a non-secret summary of a compiled team"
    )
    team_inspect.add_argument("--root", required=True)
    team_inspect.set_defaults(func=command_team_inspect)
    team_export = team_commands.add_parser(
        "export", help="copy one locked platform overlay to a new review directory"
    )
    team_export.add_argument("--root", required=True)
    team_export.add_argument(
        "--target", choices=("openclaw", "codex", "claude", "generic-ai"), required=True
    )
    team_export.add_argument("--output", required=True)
    team_export.set_defaults(func=command_team_export)
    team_ingest = team_commands.add_parser(
        "ingest", help="ingest one untrusted feedback event into a compiled team"
    )
    team_ingest.add_argument("--root", required=True)
    team_ingest.add_argument("--event", required=True)
    team_ingest.add_argument("--idempotency-key", required=True)
    team_ingest.set_defaults(func=command_team_ingest)
    team_run = team_commands.add_parser(
        "run", help="advance one work item to its next human or Draft PR stop"
    )
    team_run.add_argument("--root", required=True)
    team_run.add_argument("--work-item", required=True)
    team_run.add_argument("--repo", required=True)
    team_run.add_argument("--project-id")
    team_run.add_argument("--runner-profile", required=True)
    team_run.add_argument("--model-mode", choices=("reference", "live"), default="reference")
    team_run.add_argument("--provider", choices=("local", "github"), default="local")
    team_run.add_argument("--allow-host-runner", action="store_true")
    team_run.add_argument("--allow-provider-writes", action="store_true")
    team_run.set_defaults(func=command_team_run)
    team_approve = team_commands.add_parser(
        "approve-plan", help="bind a local human approval to the exact specification scope"
    )
    team_approve.add_argument("--root", required=True)
    team_approve.add_argument("--work-item", required=True)
    team_approve.add_argument("--scope-hash", required=True)
    team_approve.set_defaults(func=command_team_approve_plan)
    team_demo = team_commands.add_parser(
        "demo", help="create a no-network reference team and stop at its human plan gate"
    )
    team_demo.add_argument("--output", required=True)
    team_demo.set_defaults(func=command_team_demo)

    runtime = subparsers.add_parser("runtime", help="operate the persistent control plane")
    runtime_commands = runtime.add_subparsers(dest="runtime_command", required=True)

    runtime_init = runtime_commands.add_parser(
        "init", help="initialize the instance state database"
    )
    runtime_init.add_argument("--instance", required=True)
    runtime_init.set_defaults(func=command_runtime_init)

    runtime_status = runtime_commands.add_parser("status", help="show non-secret runtime status")
    runtime_status.add_argument("--instance", required=True)
    runtime_status.set_defaults(func=command_runtime_status)

    runtime_ingest = runtime_commands.add_parser("ingest", help="persist one feedback event")
    runtime_ingest.add_argument("--instance", required=True)
    runtime_ingest.add_argument("--event", required=True)
    runtime_ingest.add_argument("--idempotency-key", required=True)
    runtime_ingest.set_defaults(func=command_runtime_ingest)

    runtime_lease = runtime_commands.add_parser("lease", help="acquire an agent task lease")
    runtime_lease.add_argument("--instance", required=True)
    runtime_lease.add_argument("--work-item", required=True)
    runtime_lease.add_argument("--actor-id", required=True)
    runtime_lease.add_argument("--role", required=True)
    runtime_lease.add_argument("--expected-revision", required=True, type=int)
    runtime_lease.add_argument("--ttl-seconds", type=int, default=300)
    runtime_lease.add_argument("--idempotency-key", required=True)
    runtime_lease.set_defaults(func=command_runtime_lease)

    runtime_apply = runtime_commands.add_parser("apply", help="commit one authorized transition")
    runtime_apply.add_argument("--instance", required=True)
    runtime_apply.add_argument("--work-item", required=True)
    runtime_apply.add_argument("--action", required=True)
    runtime_apply.add_argument("--actor-id", required=True)
    runtime_apply.add_argument("--role", required=True)
    runtime_apply.add_argument("--actor-kind", choices=("agent", "human"), default="agent")
    runtime_apply.add_argument("--expected-revision", required=True, type=int)
    runtime_apply.add_argument("--idempotency-key", required=True)
    runtime_apply.add_argument("--evidence", required=True)
    runtime_apply.add_argument("--lease-id")
    runtime_apply.add_argument("--approval-assertion")
    runtime_apply.add_argument("--approval-key-file")
    runtime_apply.add_argument("--approval-provider")
    runtime_apply.set_defaults(func=command_runtime_apply)

    for name, paused, help_text in (
        ("pause", True, "activate the global owner stop"),
        ("resume", False, "resume work after owner review"),
    ):
        runtime_pause = runtime_commands.add_parser(name, help=help_text)
        runtime_pause.add_argument("--instance", required=True)
        runtime_pause.add_argument("--owner-id", required=True)
        runtime_pause.add_argument("--reason", required=True)
        runtime_pause.add_argument("--idempotency-key", required=True)
        runtime_pause.set_defaults(func=command_runtime_pause, paused=paused)

    runtime_reconcile = runtime_commands.add_parser(
        "reconcile", help="recover expired leases and claims"
    )
    runtime_reconcile.add_argument("--instance", required=True)
    runtime_reconcile.set_defaults(func=command_runtime_reconcile)

    runtime_verify = runtime_commands.add_parser(
        "audit-verify", help="verify the persistent audit hash chain"
    )
    runtime_verify.add_argument("--instance", required=True)
    runtime_verify.set_defaults(func=command_runtime_verify_audit)

    runtime_backup = runtime_commands.add_parser(
        "backup", help="create a verified non-overwriting SQLite backup"
    )
    runtime_backup.add_argument("--instance", required=True)
    runtime_backup.add_argument("--output", required=True)
    runtime_backup.set_defaults(func=command_runtime_backup)

    runtime_restore = runtime_commands.add_parser(
        "restore", help="restore into an absent configured state path"
    )
    runtime_restore.add_argument("--instance", required=True)
    runtime_restore.add_argument("--backup", required=True)
    runtime_restore.set_defaults(func=command_runtime_restore)

    native = subparsers.add_parser(
        "native", help="validate portable core contracts or run the no-network Native reference path"
    )
    native_commands = native.add_subparsers(dest="native_command", required=True)
    native_contract = native_commands.add_parser(
        "contract-validate", help="validate one strict portable core contract"
    )
    native_contract.add_argument("--contract", choices=tuple(sorted(CONTRACT_SCHEMAS)), required=True)
    native_contract.add_argument("--file", required=True)
    native_contract.set_defaults(func=command_native_contract_validate)
    native_writer_authority = native_commands.add_parser(
        "writer-authority-validate",
        help="validate the WriterTopology to PlanRevision to ApprovalGrant digest chain",
    )
    native_writer_authority.add_argument("--topology", required=True)
    native_writer_authority.add_argument("--plan", required=True)
    native_writer_authority.add_argument("--approval", required=True)
    native_writer_authority.set_defaults(func=command_native_writer_authority_validate)
    native_demo = native_commands.add_parser(
        "demo", help="run deterministic fakes to an independently reviewed Draft PR"
    )
    native_demo.add_argument("--database", required=True)
    native_demo.set_defaults(func=command_native_demo)
    native_status = native_commands.add_parser(
        "status", help="show secret-safe Native controller state"
    )
    native_status.add_argument("--database", required=True)
    native_status.set_defaults(func=command_native_status)
    native_verify = native_commands.add_parser(
        "verify", help="verify Native contracts, state columns, and event hash chain"
    )
    native_verify.add_argument("--database", required=True)
    native_verify.set_defaults(func=command_native_verify)
    native_recover = native_commands.add_parser(
        "recover", help="recover expired leases and effect claims"
    )
    native_recover.add_argument("--database", required=True)
    native_recover.set_defaults(func=command_native_recover)
    native_backup = native_commands.add_parser(
        "backup", help="create a new SQLite backup and report its digest"
    )
    native_backup.add_argument("--database", required=True)
    native_backup.add_argument("--output", required=True)
    native_backup.set_defaults(func=command_native_backup)

    adapter = subparsers.add_parser(
        "adapter", help="inspect versioned adapter contracts without loading plugins"
    )
    adapter_commands = adapter.add_subparsers(dest="adapter_command", required=True)
    adapter_catalog = adapter_commands.add_parser(
        "catalog", help="show the secret-safe adapter catalog"
    )
    adapter_catalog.set_defaults(func=command_adapter_catalog)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        return int(args.func(args))
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
