#!/usr/bin/env python3
"""Portable command line entrypoint for the reference engineering repository."""

from __future__ import annotations

import argparse
import json
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
    build_design,
    create_context_team,
    export_context_target,
    inspect_context_team,
    list_presets,
    validate_context_team,
    validate_design_document,
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
from core.lifecycle import (  # noqa: E402
    apply_instance_upgrade,
    inspect_recovery_bundle,
    recover_interrupted_lifecycle,
    rollback_instance,
    write_instance_upgrade_plan,
)
from core.models import Actor, FeedbackEvent  # noqa: E402
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
    preset = args.preset
    if args.guided:
        preset = _interactive_value(preset, "Preset", "software-lite")
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
        choices=("openclaw", "codex", "claude", "generic-ai"),
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
        "--target", choices=("openclaw", "codex", "claude", "generic-ai"), required=True
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
