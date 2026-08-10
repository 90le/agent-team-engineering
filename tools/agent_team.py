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

from core.adoption import write_adoption_proposal  # noqa: E402
from core.context import write_context_bundle  # noqa: E402
from core.models import FeedbackEvent  # noqa: E402
from core.simulation import run_feedback_to_release  # noqa: E402
from core.validation import validate_repository  # noqa: E402


def command_doctor(_: argparse.Namespace) -> int:
    report = {
        "python": sys.version.split()[0],
        "git": shutil.which("git"),
        "docker": shutil.which("docker"),
        "gh": shutil.which("gh"),
        "root": str(ROOT),
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
    input_path = Path(args.input).resolve() if args.input else ROOT / "examples/feedback-to-release/input/feedback.json"
    event = FeedbackEvent.from_dict(json.loads(input_path.read_text(encoding="utf-8")))
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
    print(json.dumps({"role": args.role, "output": str(Path(args.output).resolve())}, ensure_ascii=False))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agent-team", description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    doctor = subparsers.add_parser("doctor", help="report portable runtime prerequisites")
    doctor.set_defaults(func=command_doctor)

    validate = subparsers.add_parser("validate", help="validate repository contracts and safety gates")
    validate.add_argument("--root")
    validate.set_defaults(func=command_validate)

    simulate = subparsers.add_parser("simulate", help="run the side-effect-free feedback-to-release scenario")
    simulate.add_argument("--input")
    simulate.add_argument("--output")
    simulate.add_argument("--approve-production", action="store_true")
    simulate.set_defaults(func=command_simulate)

    adopt = subparsers.add_parser("adopt-project", help="create a proposal outside an existing project")
    adopt.add_argument("--repo", required=True)
    adopt.add_argument("--output", required=True)
    adopt.set_defaults(func=command_adopt)

    export_context = subparsers.add_parser("export-context", help="export a bounded role context bundle")
    export_context.add_argument("--role", required=True)
    export_context.add_argument("--output", required=True)
    export_context.set_defaults(func=command_export_context)
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
