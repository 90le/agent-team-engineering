#!/usr/bin/env python3
"""Create or reconcile one exactly approved proposal in a dedicated GitHub repo."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.contracts import approval_scope_digest, plan_revision_digest  # noqa: E402
from core.github_scm import (  # noqa: E402
    GitHubJobClient,
    GitHubScmError,
    execute_bound_change,
    verify_github_actions_identity,
)
from core.json_support import loads_strict  # noqa: E402
from core.schema_validation import validate_schema  # noqa: E402
from core.security import find_inline_secret  # noqa: E402

REPORT_SCHEMA = ROOT / "schemas" / "github-scm-conformance-report.schema.json"


def build_plan(
    *, repository_id: str, base_commit: str, framework_commit: str
) -> dict:
    plan = {
        "$schema": "urn:agent-team:schema:plan-revision:1.0.0",
        "schema_version": "1.0.0",
        "plan_id": "plan-github-scm-conformance-v08",
        "work_item_id": "work-github-scm-conformance-v08",
        "revision": 1,
        "previous_plan_digest": None,
        "repository_id": repository_id,
        "base_commit": base_commit,
        "objective": "Create one bounded file commit and an unmerged draft pull request.",
        "assumptions": [
            "The repository is dedicated to disposable conformance evidence.",
            f"The reviewed Factory implementation commit is {framework_commit}.",
        ],
        "tasks": [
            {
                "task_id": "task-create-proposal",
                "role_id": "role.implementer",
                "objective": "Write the exact approved evidence file and open a draft PR.",
                "depends_on": [],
                "required_capabilities": ["code.change"],
                "completion_evidence": ["change-commit", "draft-pr"],
            }
        ],
        "allowed_paths": ["conformance/v08-approved-change.md"],
        "allowed_actions": ["repository.read", "commit.create", "draft-pr.create"],
        "tests": ["Reconcile the workflow and prove object counts do not increase."],
        "risk_level": "LOW",
        "rollback": "Close the draft PR and delete its proposal branch; do not merge.",
        "budget_limit": 1,
        "time_limit_seconds": 600,
        "created_by": "role.planner",
        "created_at": "2026-08-11T08:00:00Z",
        "plan_digest": "sha256:" + "0" * 64,
    }
    plan["plan_digest"] = plan_revision_digest(plan)
    return plan


def build_change(plan: dict, repository: str) -> dict:
    digest_hex = plan["plan_digest"].removeprefix("sha256:")
    return {
        "schema_version": "1.0.0",
        "repository": repository,
        "repository_id": plan["repository_id"],
        "work_item_id": plan["work_item_id"],
        "base_branch": "main",
        "proposal_branch": f"agent-team/conformance-{plan['base_commit'][:12]}",
        "file_path": "conformance/v08-approved-change.md",
        "file_content": (
            "# Agent Team v0.8 SCM conformance\n\n"
            f"Approved plan: `{plan['plan_digest']}`\n\n"
            "This repository contains no production code or data. This change must remain unmerged.\n"
        ),
        "issue_title": "v0.8 bounded SCM conformance work item",
        "issue_body": f"Exact approved plan: `{plan['plan_digest']}`.",
        "commit_message": "test: add approved v0.8 SCM evidence",
        "pull_request_title": "Conformance: v0.8 approved proposal",
        "pull_request_body": (
            f"Exact approved plan: `{plan['plan_digest']}`. "
            "This pull request is conformance evidence and must remain a draft."
        ),
        "idempotency_marker": f"agent-team:{digest_hex}",
    }


def build_approval(
    plan: dict,
    verified: dict[str, str],
    environment: dict[str, str],
    now: datetime,
) -> dict:
    run_id = environment["GITHUB_RUN_ID"]
    attempt = environment["GITHUB_RUN_ATTEMPT"]
    issued = now.replace(microsecond=0)
    expires = issued + timedelta(minutes=10)
    grant = {
        "$schema": "urn:agent-team:schema:approval-grant:1.0.0",
        "schema_version": "1.0.0",
        "approval_id": f"approval-github-run-{run_id}-attempt-{attempt}",
        "actor_id": verified["actor_id"],
        "identity_provider": verified["identity_provider"],
        "work_item_id": plan["work_item_id"],
        "plan_revision": plan["revision"],
        "plan_digest": plan["plan_digest"],
        "repository_id": plan["repository_id"],
        "base_commit": plan["base_commit"],
        "allowed_paths": plan["allowed_paths"],
        "allowed_actions": plan["allowed_actions"],
        "runner_profile": "runner.native-oci@1.0.0",
        "agent_capabilities": ["code.change"],
        "budget_limit": plan["budget_limit"],
        "time_limit_seconds": plan["time_limit_seconds"],
        "merge_allowed": False,
        "deploy_allowed": False,
        "issued_at": issued.isoformat().replace("+00:00", "Z"),
        "expires_at": expires.isoformat().replace("+00:00", "Z"),
        "nonce": f"github-run-{run_id}-attempt-{attempt}-nonce",
        "evidence_ref": f"github-actions://{environment['GITHUB_REPOSITORY']}/runs/{run_id}",
        "signature_ref": verified["signature_ref"],
        "scope_digest": "sha256:" + "0" * 64,
    }
    grant["scope_digest"] = approval_scope_digest(grant)
    return grant


def _verify_framework_checkout(expected: str) -> None:
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
            shell=False,
        )
    except (OSError, subprocess.SubprocessError):
        raise GitHubScmError("cannot verify the checked-out Factory commit") from None
    if completed.stdout.strip() != expected:
        raise GitHubScmError("checked-out Factory commit differs from the approved input")


def _write_report(path: Path, report: dict) -> None:
    schema = loads_strict(REPORT_SCHEMA.read_text(encoding="utf-8"))
    issues = validate_schema(report, schema)
    if issues:
        raise GitHubScmError("sanitized report violates its schema")
    secret = find_inline_secret(report)
    if secret is not None:
        raise GitHubScmError(f"sanitized report contains secret-like data at {secret}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", required=True)
    parser.add_argument("--repository-id", required=True)
    parser.add_argument("--base-commit", required=True)
    parser.add_argument("--framework-commit", required=True)
    parser.add_argument("--expected-actor-id")
    parser.add_argument("--print-plan-digest", action="store_true")
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()
    plan = build_plan(
        repository_id=arguments.repository_id,
        base_commit=arguments.base_commit,
        framework_commit=arguments.framework_commit,
    )
    if arguments.print_plan_digest:
        print(plan["plan_digest"])
        return 0
    if arguments.output is None or arguments.expected_actor_id is None:
        parser.error("execution requires --output and --expected-actor-id")
    try:
        _verify_framework_checkout(arguments.framework_commit)
        verified = verify_github_actions_identity(
            os.environ,
            expected_repository=arguments.repository,
            expected_actor_id=arguments.expected_actor_id,
            expected_plan_digest=plan["plan_digest"],
        )
        approval = build_approval(
            plan,
            verified,
            dict(os.environ),
            datetime.now(timezone.utc),
        )
        token = os.environ.get("GITHUB_TOKEN", "")
        client = GitHubJobClient(arguments.repository, token)
        report = execute_bound_change(
            client,
            plan,
            approval,
            build_change(plan, arguments.repository),
            expected_repository=arguments.repository,
            expected_repository_id=arguments.repository_id,
            verified_identity=verified,
        )
        report["framework_commit"] = arguments.framework_commit
        _write_report(arguments.output.resolve(), report)
    except (GitHubScmError, OSError, ValueError) as error:
        print(f"GitHub SCM conformance refused or failed: {error}", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "repository": report["repository"],
                "plan_digest": report["plan_digest"],
                "objects_created": {
                    key: report[key]["created"]
                    for key in ("issue", "branch", "commit", "draft_pull_request")
                },
                "merge_performed": False,
                "deployment_performed": False,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
