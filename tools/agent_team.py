#!/usr/bin/env python3
"""Portable command line entrypoint for the reference engineering repository."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.adapters import load_adapter_catalog  # noqa: E402
from core.adoption import write_adoption_proposal  # noqa: E402
from core.approval import HMACApprovalVerifier  # noqa: E402
from core.context import write_context_bundle  # noqa: E402
from core.control_plane import ControlPlane  # noqa: E402
from core.instance import (  # noqa: E402
    factory_contract_digest,
    init_instance,
    instance_summary,
    relock_instance,
    validate_instance_directory,
)
from core.json_support import loads_strict  # noqa: E402
from core.models import Actor, FeedbackEvent  # noqa: E402
from core.simulation import run_feedback_to_release  # noqa: E402
from core.validation import validate_repository  # noqa: E402


def command_doctor(_: argparse.Namespace) -> int:
    factory = loads_strict((ROOT / "factory-package.json").read_text(encoding="utf-8"))
    report = {
        "python": sys.version.split()[0],
        "git": shutil.which("git"),
        "docker": shutil.which("docker"),
        "gh": shutil.which("gh"),
        "root": str(ROOT),
        "factory_id": factory["id"],
        "factory_version": factory["version"],
        "factory_contract_digest": factory_contract_digest(),
        "production_integrations_enabled": False,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["git"] else 1


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
    report = write_adoption_proposal(Path(args.repo), Path(args.output))
    print(json.dumps(report, ensure_ascii=False, indent=2))
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
    root = Path(args.root).resolve()
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


def _load_json_object(path: str) -> dict:
    target = Path(path).resolve()
    value = loads_strict(target.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON root must be an object: {target}")
    return value


def _runtime_database(instance: str) -> tuple[Path, Path]:
    instance_root = Path(instance).resolve()
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
    subparsers = parser.add_subparsers(dest="command", required=True)

    doctor = subparsers.add_parser("doctor", help="report portable runtime prerequisites")
    doctor.set_defaults(func=command_doctor)

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
    adopt.set_defaults(func=command_adopt)

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
