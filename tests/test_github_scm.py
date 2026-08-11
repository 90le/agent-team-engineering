from __future__ import annotations

import base64
import copy
import unittest
from datetime import datetime, timezone

from core.contracts import approval_scope_digest, plan_revision_digest
from core.github_scm import (
    GitHubJobClient,
    GitHubScmError,
    execute_bound_change,
    verify_github_actions_identity,
)
from tools.github_scm_conformance import build_approval, build_change, build_plan

NOW = datetime(2026, 8, 11, 8, 5, tzinfo=timezone.utc)
REPOSITORY = "example/agent-team-conformance"
REPOSITORY_ID = "repo.github-conformance"
BASE = "a" * 40


def plan() -> dict:
    value = {
        "$schema": "urn:agent-team:schema:plan-revision:1.0.0",
        "schema_version": "1.0.0",
        "plan_id": "plan-github-conformance-1",
        "work_item_id": "work-github-conformance-1",
        "revision": 1,
        "previous_plan_digest": None,
        "repository_id": REPOSITORY_ID,
        "base_commit": BASE,
        "objective": "Create one bounded proposal and a draft pull request.",
        "assumptions": ["The dedicated repository contains no production data."],
        "tasks": [
            {
                "task_id": "task-write-proposal",
                "role_id": "role.implementer",
                "objective": "Write the approved conformance artifact.",
                "depends_on": [],
                "required_capabilities": ["code.change"],
                "completion_evidence": ["change-commit"],
            }
        ],
        "allowed_paths": ["conformance/approved-change.md"],
        "allowed_actions": ["repository.read", "commit.create", "draft-pr.create"],
        "tests": ["Validate exact content digest."],
        "risk_level": "LOW",
        "rollback": "Close the draft PR and delete the proposal branch.",
        "budget_limit": 1,
        "time_limit_seconds": 600,
        "created_by": "role.planner",
        "created_at": "2026-08-11T08:00:00Z",
        "plan_digest": "sha256:" + "0" * 64,
    }
    value["plan_digest"] = plan_revision_digest(value)
    return value


def identity() -> dict[str, str]:
    return {
        "actor_id": "github:12345",
        "actor_login": "owner",
        "identity_provider": "github.actions",
        "signature_ref": f"github-actions://{REPOSITORY}/runs/99/attempts/1",
    }


def approval(value: dict) -> dict:
    document = {
        "$schema": "urn:agent-team:schema:approval-grant:1.0.0",
        "schema_version": "1.0.0",
        "approval_id": "approval-github-conformance-1",
        "actor_id": identity()["actor_id"],
        "identity_provider": identity()["identity_provider"],
        "work_item_id": value["work_item_id"],
        "plan_revision": value["revision"],
        "plan_digest": value["plan_digest"],
        "repository_id": value["repository_id"],
        "base_commit": value["base_commit"],
        "allowed_paths": value["allowed_paths"],
        "allowed_actions": value["allowed_actions"],
        "runner_profile": "runner.native-oci@1.0.0",
        "agent_capabilities": ["code.change"],
        "budget_limit": value["budget_limit"],
        "time_limit_seconds": value["time_limit_seconds"],
        "merge_allowed": False,
        "deploy_allowed": False,
        "issued_at": "2026-08-11T08:00:00Z",
        "expires_at": "2026-08-11T08:10:00Z",
        "nonce": "github-conformance-nonce-0001",
        "evidence_ref": f"github-actions://{REPOSITORY}/runs/99",
        "signature_ref": identity()["signature_ref"],
        "scope_digest": "sha256:" + "0" * 64,
    }
    document["scope_digest"] = approval_scope_digest(document)
    return document


def change() -> dict:
    return {
        "schema_version": "1.0.0",
        "repository": REPOSITORY,
        "repository_id": REPOSITORY_ID,
        "work_item_id": "work-github-conformance-1",
        "base_branch": "main",
        "proposal_branch": "agent-team/conformance-1",
        "file_path": "conformance/approved-change.md",
        "file_content": "# Approved conformance change\n",
        "issue_title": "Conformance work item",
        "issue_body": "A dedicated, non-production SCM trial.",
        "commit_message": "test: add approved conformance artifact",
        "pull_request_title": "Conformance: bounded draft proposal",
        "pull_request_body": "This PR must remain a draft and unmerged.",
        "idempotency_marker": "agent-team:" + "b" * 64,
    }


class FakeClient:
    def __init__(self, base: str = BASE) -> None:
        self.actual_base = base
        self.calls: list[str] = []
        self.seen: set[str] = set()

    def base_commit(self, branch: str) -> str:
        self.calls.append(f"base:{branch}")
        return self.actual_base

    def _ensure(self, kind: str) -> dict:
        self.calls.append(kind)
        created = kind not in self.seen
        self.seen.add(kind)
        return {
            "external_ref": f"https://example.invalid/{kind}",
            "provider_id": kind,
            "created": created,
        }

    def ensure_issue(self, marker: str, title: str, body: str) -> dict:
        del marker, title, body
        return self._ensure("issue")

    def ensure_branch(self, branch: str, base_commit: str) -> dict:
        del branch, base_commit
        return self._ensure("branch")

    def ensure_file(self, branch: str, path: str, content: bytes, message: str) -> dict:
        del branch, path, content, message
        return self._ensure("file")

    def ensure_draft_pull_request(
        self, marker: str, title: str, body: str, head: str, base: str
    ) -> dict:
        del marker, title, body, head, base
        return self._ensure("pull-request")


class GitHubIdentityTests(unittest.TestCase):
    def test_workflow_dispatch_identity_binds_actor_repository_and_plan(self) -> None:
        digest = plan()["plan_digest"]
        environment = {
            "CI": "true",
            "GITHUB_ACTIONS": "true",
            "RUNNER_ENVIRONMENT": "github-hosted",
            "GITHUB_EVENT_NAME": "workflow_dispatch",
            "GITHUB_REPOSITORY": REPOSITORY,
            "GITHUB_ACTOR": "owner",
            "GITHUB_ACTOR_ID": "12345",
            "GITHUB_RUN_ID": "99",
            "GITHUB_RUN_ATTEMPT": "1",
            "APPROVED_PLAN_DIGEST": digest,
        }
        verified = verify_github_actions_identity(
            environment,
            expected_repository=REPOSITORY,
            expected_actor_id="12345",
            expected_plan_digest=digest,
        )
        self.assertEqual(verified, identity())

        for key in ("GITHUB_REPOSITORY", "GITHUB_ACTOR_ID", "APPROVED_PLAN_DIGEST"):
            invalid = copy.deepcopy(environment)
            invalid[key] = "wrong"
            with self.subTest(key=key), self.assertRaises(GitHubScmError):
                verify_github_actions_identity(
                    invalid,
                    expected_repository=REPOSITORY,
                    expected_actor_id="12345",
                    expected_plan_digest=digest,
                )

    def test_conformance_documents_are_deterministic_and_exactly_bound(self) -> None:
        value = build_plan(
            repository_id=REPOSITORY_ID,
            base_commit=BASE,
            framework_commit="f" * 40,
        )
        same = build_plan(
            repository_id=REPOSITORY_ID,
            base_commit=BASE,
            framework_commit="f" * 40,
        )
        self.assertEqual(value["plan_digest"], same["plan_digest"])
        self.assertIn(value["plan_digest"], build_change(value, REPOSITORY)["file_content"])
        environment = {
            "GITHUB_RUN_ID": "99",
            "GITHUB_RUN_ATTEMPT": "1",
            "GITHUB_REPOSITORY": REPOSITORY,
        }
        grant = build_approval(value, identity(), environment, NOW)
        self.assertEqual(grant["plan_digest"], value["plan_digest"])
        self.assertEqual(grant["scope_digest"], approval_scope_digest(grant))


class BoundedGitHubChangeTests(unittest.TestCase):
    def test_exact_approval_creates_only_proposal_objects_and_replays(self) -> None:
        client = FakeClient()
        value = plan()
        grant = approval(value)
        first = execute_bound_change(
            client,
            value,
            grant,
            change(),
            expected_repository=REPOSITORY,
            expected_repository_id=REPOSITORY_ID,
            verified_identity=identity(),
            now=NOW,
        )
        second = execute_bound_change(
            client,
            value,
            grant,
            change(),
            expected_repository=REPOSITORY,
            expected_repository_id=REPOSITORY_ID,
            verified_identity=identity(),
            now=NOW,
        )
        self.assertTrue(first["issue"]["created"])
        self.assertTrue(first["draft_pull_request"]["created"])
        self.assertFalse(second["issue"]["created"])
        self.assertFalse(second["draft_pull_request"]["created"])
        self.assertFalse(first["merge_performed"])
        self.assertFalse(first["deployment_performed"])
        self.assertEqual(first["repository_id"], REPOSITORY_ID)
        self.assertEqual(first["base_commit"], BASE)
        self.assertEqual(first["identity_provider"], "github.actions")
        self.assertEqual(first["identity_ref"], identity()["signature_ref"])

    def test_wrong_digest_repository_actor_path_and_expiry_make_no_provider_call(self) -> None:
        base_plan = plan()
        cases: list[tuple[dict, dict, dict, dict[str, str], datetime]] = []

        tampered_plan = copy.deepcopy(base_plan)
        tampered_plan["objective"] = "Changed after digest"
        cases.append((tampered_plan, approval(base_plan), change(), identity(), NOW))

        wrong_repo = change()
        wrong_repo["repository"] = "other/repository"
        cases.append((base_plan, approval(base_plan), wrong_repo, identity(), NOW))

        wrong_actor = identity()
        wrong_actor["actor_id"] = "github:999"
        cases.append((base_plan, approval(base_plan), change(), wrong_actor, NOW))

        wrong_path = change()
        wrong_path["file_path"] = "outside/not-approved.md"
        cases.append((base_plan, approval(base_plan), wrong_path, identity(), NOW))

        expired = datetime(2026, 8, 11, 8, 11, tzinfo=timezone.utc)
        cases.append((base_plan, approval(base_plan), change(), identity(), expired))

        wrong_base_grant = approval(base_plan)
        wrong_base_grant["base_commit"] = "c" * 40
        wrong_base_grant["scope_digest"] = approval_scope_digest(wrong_base_grant)
        cases.append((base_plan, wrong_base_grant, change(), identity(), NOW))

        for index, (value, grant, change_set, verified, current) in enumerate(cases):
            client = FakeClient()
            with self.subTest(case=index), self.assertRaises(GitHubScmError):
                execute_bound_change(
                    client,
                    value,
                    grant,
                    change_set,
                    expected_repository=REPOSITORY,
                    expected_repository_id=REPOSITORY_ID,
                    verified_identity=verified,
                    now=current,
                )
            self.assertEqual(client.calls, [])

    def test_changed_base_is_rejected_before_any_write(self) -> None:
        client = FakeClient(base="d" * 40)
        value = plan()
        with self.assertRaises(GitHubScmError):
            execute_bound_change(
                client,
                value,
                approval(value),
                change(),
                expected_repository=REPOSITORY,
                expected_repository_id=REPOSITORY_ID,
                verified_identity=identity(),
                now=NOW,
            )
        self.assertEqual(client.calls, ["base:main"])

    def test_job_client_exposes_no_merge_release_settings_or_deploy_method(self) -> None:
        for method in ("merge", "release", "settings", "deploy", "delete_repository"):
            self.assertFalse(hasattr(GitHubJobClient, method))

    def test_job_client_requires_a_private_nonfork_evidence_repository(self) -> None:
        client = GitHubJobClient(REPOSITORY, "x" * 20)
        client._request = lambda *args, **kwargs: {  # type: ignore[method-assign]
            "private": True,
            "fork": False,
            "archived": False,
        }
        client.require_private_repository()

        for metadata in (
            {"private": False, "fork": False, "archived": False},
            {"private": True, "fork": True, "archived": False},
            {"private": True, "fork": False, "archived": True},
        ):
            client._request = lambda *args, value=metadata, **kwargs: value  # type: ignore[method-assign]
            with self.subTest(metadata=metadata), self.assertRaises(GitHubScmError):
                client.require_private_repository()

    def test_job_client_file_identity_is_stable_across_create_and_replay(self) -> None:
        client = GitHubJobClient(REPOSITORY, "x" * 20)
        content = b"# approved\n"
        commit = "c" * 40
        file_exists = False

        def request(method: str, path: str, payload=None, *, allow_missing=False):
            nonlocal file_exists
            del allow_missing
            if method == "GET" and "/contents/" in path:
                if not file_exists:
                    return None
                return {"content": base64.b64encode(content).decode("ascii")}
            if method == "PUT" and "/contents/" in path:
                self.assertEqual(payload["branch"], "agent-team/conformance-1")
                file_exists = True
                return {"commit": {"sha": commit}}
            if method == "GET" and "/git/ref/heads/" in path:
                return {
                    "object": {
                        "sha": commit,
                        "type": "commit",
                        "url": f"https://api.github.com/repos/{REPOSITORY}/git/commits/{commit}",
                    }
                }
            self.fail(f"unexpected request: {method} {path}")

        client._request = request  # type: ignore[method-assign]
        first = client.ensure_file(
            "agent-team/conformance-1", "conformance/approved.md", content, "test: approved"
        )
        replay = client.ensure_file(
            "agent-team/conformance-1", "conformance/approved.md", content, "test: approved"
        )
        self.assertTrue(first.pop("created"))
        self.assertFalse(replay.pop("created"))
        self.assertEqual(first, replay)


if __name__ == "__main__":
    unittest.main()
