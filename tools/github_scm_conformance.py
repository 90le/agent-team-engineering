#!/usr/bin/env python3
"""Create or reconcile one exactly approved proposal in a dedicated GitHub repo."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.contracts import approval_scope_digest, digest_value, plan_revision_digest  # noqa: E402
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
SCM_REPOSITORY = "90le/agent-team-v10-conformance-private"
SCM_REPOSITORY_ID = "repo.conformance.github.v10"
SCM_BASE_BRANCH = "main"
SCM_WORKFLOW_PATH = ".github/workflows/agent-team-v10-conformance.yml"
SCM_WORKFLOW_REF = f"{SCM_REPOSITORY}/{SCM_WORKFLOW_PATH}@refs/heads/{SCM_BASE_BRANCH}"
FRAMEWORK_REPOSITORY = "90le/agent-team-engineering"
COMMIT_ID = re.compile(r"^[a-f0-9]{40}$")


def build_plan(
    *,
    repository_id: str,
    base_commit: str,
    framework_commit: str,
) -> dict:
    if repository_id != SCM_REPOSITORY_ID:
        raise GitHubScmError("SCM conformance repository_id is not the fixed v1 identity")
    if not COMMIT_ID.fullmatch(base_commit) or not COMMIT_ID.fullmatch(framework_commit):
        raise GitHubScmError("SCM conformance commits must be exact 40-character object IDs")
    plan = {
        "$schema": "urn:agent-team:schema:plan-revision:1.1.0",
        "schema_version": "1.1.0",
        "plan_id": "plan-github-scm-conformance-v10",
        "work_item_id": "work-github-scm-conformance-v10",
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
        "allowed_paths": ["conformance/v10-approved-change.md"],
        "allowed_actions": ["repository.read", "commit.create", "draft-pr.create"],
        "tests": ["Reconcile the workflow and prove object counts do not increase."],
        "risk_level": "LOW",
        "rollback": "Close the draft PR and delete its proposal branch; do not merge.",
        "budget_limit": 1,
        "time_limit_seconds": 600,
        "writer_topology": None,
        "created_by": "role.planner",
        "created_at": "2026-08-11T08:00:00Z",
        "plan_digest": "sha256:" + "0" * 64,
    }
    plan["plan_digest"] = plan_revision_digest(plan)
    return plan


def build_change(plan: dict, repository: str) -> dict:
    if repository != SCM_REPOSITORY:
        raise GitHubScmError("SCM conformance repository is not the fixed v1 repository")
    digest_hex = plan["plan_digest"].removeprefix("sha256:")
    return {
        "schema_version": "1.0.0",
        "repository": repository,
        "repository_id": plan["repository_id"],
        "work_item_id": plan["work_item_id"],
        "base_branch": SCM_BASE_BRANCH,
        "proposal_branch": f"agent-team/v10-conformance-{plan['base_commit'][:12]}",
        "file_path": "conformance/v10-approved-change.md",
        "file_content": (
            "# Agent Team v1.0 SCM conformance\n\n"
            f"Approved plan: `{plan['plan_digest']}`\n\n"
            "This repository contains no production code or data. This change must remain unmerged.\n"
        ),
        "issue_title": "v1.0 bounded SCM conformance work item",
        "issue_body": f"Exact approved plan: `{plan['plan_digest']}`.",
        "commit_message": "test: add approved v1.0 SCM evidence",
        "pull_request_title": "Conformance: v1.0 approved proposal",
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
        "$schema": "urn:agent-team:schema:approval-grant:1.1.0",
        "schema_version": "1.1.0",
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
        "writer_topology": plan["writer_topology"],
        "issued_at": issued.isoformat().replace("+00:00", "Z"),
        "expires_at": expires.isoformat().replace("+00:00", "Z"),
        "nonce": f"github-run-{run_id}-attempt-{attempt}-nonce",
        "evidence_ref": f"github-actions://{environment['GITHUB_REPOSITORY']}/runs/{run_id}",
        "signature_ref": verified["signature_ref"],
        "scope_digest": "sha256:" + "0" * 64,
    }
    grant["scope_digest"] = approval_scope_digest(grant)
    return grant


def build_report(
    execution: dict,
    *,
    plan: dict,
    approval: dict,
    change: dict,
    verified: dict[str, str],
    framework_commit: str,
) -> dict:
    """Complete the sanitized report from canonical, already-authorized documents."""

    return {
        "$schema": "urn:agent-team:schema:github-scm-conformance-report:1.1.0",
        "schema_version": "1.1.0",
        "evidence_kind": "github-scm-conformance-v1",
        "repository": execution["repository"],
        "repository_id": execution["repository_id"],
        "repository_private": True,
        "base_branch": change["base_branch"],
        "proposal_branch": change["proposal_branch"],
        "base_commit": execution["base_commit"],
        "framework_commit": framework_commit,
        "framework_repository": verified["framework_repository"],
        "workflow": {
            "path": SCM_WORKFLOW_PATH,
            "ref": verified["workflow_ref"],
            "sha": verified["workflow_sha"],
            "repository_ref": verified["repository_ref"],
            "run_id": verified["run_id"],
            "run_attempt": verified["run_attempt"],
            "run_url": (
                f"https://github.com/{SCM_REPOSITORY}/actions/runs/{verified['run_id']}"
            ),
        },
        "plan_schema_version": plan["schema_version"],
        "plan_digest": plan["plan_digest"],
        "writer_topology": plan["writer_topology"],
        "change_digest": digest_value(change),
        "approval_schema_version": approval["schema_version"],
        "approval_id": approval["approval_id"],
        "approval_scope_digest": approval["scope_digest"],
        "approval_issued_at": approval["issued_at"],
        "approval_expires_at": approval["expires_at"],
        "approval_nonce": approval["nonce"],
        "approval_evidence_ref": approval["evidence_ref"],
        "actor_id": execution["actor_id"],
        "identity_provider": execution["identity_provider"],
        "identity_ref": execution["identity_ref"],
        "issue": execution["issue"],
        "branch": execution["branch"],
        "commit": execution["commit"],
        "draft_pull_request": execution["draft_pull_request"],
        "merge_performed": False,
        "deployment_performed": False,
    }


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
    if arguments.repository != SCM_REPOSITORY:
        parser.error(f"--repository must be {SCM_REPOSITORY}")
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
            expected_workflow_ref=SCM_WORKFLOW_REF,
            expected_base_commit=arguments.base_commit,
            expected_framework_commit=arguments.framework_commit,
            expected_framework_repository=FRAMEWORK_REPOSITORY,
        )
        approval = build_approval(
            plan,
            verified,
            dict(os.environ),
            datetime.now(timezone.utc),
        )
        token = os.environ.get("GITHUB_TOKEN", "")
        client = GitHubJobClient(arguments.repository, token)
        client.require_private_repository()
        change = build_change(plan, arguments.repository)
        execution = execute_bound_change(
            client,
            plan,
            approval,
            change,
            expected_repository=arguments.repository,
            expected_repository_id=arguments.repository_id,
            verified_identity=verified,
        )
        report = build_report(
            execution,
            plan=plan,
            approval=approval,
            change=change,
            verified=verified,
            framework_commit=arguments.framework_commit,
        )
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
