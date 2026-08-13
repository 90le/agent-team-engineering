"""Bound GitHub proposal writer for a disposable, repository-scoped Actions job.

The writer intentionally has no merge, release, settings, deployment or default-
branch update method.  All mutable operations are proposal-only and reconcile an
exact marker before retrying.
"""

from __future__ import annotations

import base64
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Protocol

from core.contracts import ContractViolation, approval_scope_digest, require_contract
from core.json_support import loads_strict
from core.schema_validation import validate_schema
from core.security import find_inline_secret

ROOT = Path(__file__).resolve().parents[1]
CHANGE_SCHEMA = ROOT / "schemas" / "github-change-set.schema.json"
OBJECT_ID = re.compile(r"^[a-f0-9]{40}$")
PLAN_DIGEST = re.compile(r"^sha256:[a-f0-9]{64}$")
MAX_RESPONSE_BYTES = 5_000_000
BRANCH_HEAD_CONSISTENCY_DELAYS = (0.0, 0.25, 0.5, 1.0)


class GitHubScmError(RuntimeError):
    """Fail-closed error with no provider response body or credential material."""


class GitHubScmClient(Protocol):
    def base_commit(self, branch: str) -> str: ...

    def ensure_issue(self, marker: str, title: str, body: str) -> dict[str, Any]: ...

    def ensure_branch(self, branch: str, base_commit: str) -> dict[str, Any]: ...

    def ensure_file(
        self, branch: str, path: str, content: bytes, message: str
    ) -> dict[str, Any]: ...

    def ensure_draft_pull_request(
        self, marker: str, title: str, body: str, head: str, base: str
    ) -> dict[str, Any]: ...


def verify_github_actions_identity(
    environment: Mapping[str, str],
    *,
    expected_repository: str,
    expected_actor_id: str,
    expected_plan_digest: str,
    expected_workflow_ref: str,
    expected_base_commit: str,
    expected_framework_commit: str,
    expected_framework_repository: str,
) -> dict[str, str]:
    required = {
        "CI": "true",
        "GITHUB_ACTIONS": "true",
        "RUNNER_ENVIRONMENT": "github-hosted",
        "GITHUB_EVENT_NAME": "workflow_dispatch",
        "GITHUB_REPOSITORY": expected_repository,
        "GITHUB_ACTOR_ID": expected_actor_id,
        "APPROVED_PLAN_DIGEST": expected_plan_digest,
        "APPROVED_BASE_COMMIT": expected_base_commit,
        "APPROVED_FRAMEWORK_COMMIT": expected_framework_commit,
        "APPROVED_FRAMEWORK_REPOSITORY": expected_framework_repository,
        "GITHUB_REF": "refs/heads/main",
        "GITHUB_SHA": expected_base_commit,
        "GITHUB_WORKFLOW_REF": expected_workflow_ref,
        "GITHUB_WORKFLOW_SHA": expected_base_commit,
    }
    wrong = [key for key, value in required.items() if environment.get(key) != value]
    if wrong:
        raise GitHubScmError("GitHub workflow identity/binding mismatch: " + ", ".join(wrong))
    actor = environment.get("GITHUB_ACTOR", "")
    run_id = environment.get("GITHUB_RUN_ID", "")
    attempt = environment.get("GITHUB_RUN_ATTEMPT", "")
    if (
        not actor
        or not expected_actor_id.isdigit()
        or not re.fullmatch(r"[1-9][0-9]*", run_id)
        or attempt != "1"
    ):
        raise GitHubScmError("GitHub workflow identity fields are malformed")
    if not PLAN_DIGEST.fullmatch(expected_plan_digest):
        raise GitHubScmError("approved plan digest is malformed")
    if not OBJECT_ID.fullmatch(expected_base_commit) or not OBJECT_ID.fullmatch(
        expected_framework_commit
    ):
        raise GitHubScmError("approved commit binding is malformed")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", expected_framework_repository):
        raise GitHubScmError("approved framework repository is malformed")
    expected_workflow = (
        rf"{re.escape(expected_repository)}/\.github/workflows/"
        r"[A-Za-z0-9_.-]+\.ya?ml@refs/heads/main"
    )
    if not re.fullmatch(expected_workflow, expected_workflow_ref):
        raise GitHubScmError("approved workflow reference is malformed")
    return {
        "actor_id": f"github:{expected_actor_id}",
        "actor_login": actor,
        "identity_provider": "github.actions",
        "signature_ref": (
            f"github-actions://{expected_repository}/runs/{run_id}/attempts/{attempt}"
        ),
        "repository_ref": "refs/heads/main",
        "workflow_ref": expected_workflow_ref,
        "workflow_sha": expected_base_commit,
        "framework_repository": expected_framework_repository,
        "run_id": run_id,
        "run_attempt": attempt,
    }


def _safe_relative_path(value: str) -> PurePosixPath:
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise GitHubScmError("change path must be repository-relative without traversal")
    return path


def _path_allowed(path: PurePosixPath, allowed: list[str]) -> bool:
    for raw in allowed:
        candidate = _safe_relative_path(raw.rstrip("/"))
        if path == candidate or candidate in path.parents:
            return True
    return False


def validate_bound_change(
    plan: dict[str, Any],
    approval: dict[str, Any],
    change: dict[str, Any],
    *,
    expected_repository: str,
    expected_repository_id: str,
    verified_identity: Mapping[str, str],
    now: datetime | None = None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    try:
        plan = require_contract("plan_revision", plan)
        approval = require_contract("approval_grant", approval)
    except ContractViolation as error:
        raise GitHubScmError(str(error)) from error
    schema = loads_strict(CHANGE_SCHEMA.read_text(encoding="utf-8"))
    issues = validate_schema(change, schema)
    if issues:
        details = "; ".join(f"{issue.path}: {issue.message}" for issue in issues)
        raise GitHubScmError(f"GitHub change set violates schema: {details}")
    secret = find_inline_secret(change)
    if secret is not None:
        raise GitHubScmError(f"GitHub change set contains inline secret-like data at {secret}")
    if change["repository"] != expected_repository:
        raise GitHubScmError("change targets a repository outside the job scope")
    if change["repository_id"] != expected_repository_id:
        raise GitHubScmError("change repository_id differs from the configured project")
    if plan["repository_id"] != expected_repository_id:
        raise GitHubScmError("plan targets a different repository_id")
    if change["work_item_id"] != plan["work_item_id"]:
        raise GitHubScmError("change belongs to another work item")
    comparisons = {
        "work_item_id": plan["work_item_id"],
        "plan_revision": plan["revision"],
        "plan_digest": plan["plan_digest"],
        "repository_id": plan["repository_id"],
        "base_commit": plan["base_commit"],
        "allowed_paths": plan["allowed_paths"],
        "allowed_actions": plan["allowed_actions"],
        "budget_limit": plan["budget_limit"],
        "time_limit_seconds": plan["time_limit_seconds"],
    }
    for field, expected in comparisons.items():
        if approval[field] != expected:
            raise GitHubScmError(f"approval differs from plan: {field}")
    if approval.get("writer_topology") != plan.get("writer_topology"):
        raise GitHubScmError("approval differs from plan: writer_topology")
    if approval_scope_digest(approval) != approval["scope_digest"]:
        raise GitHubScmError("approval scope digest is invalid")
    if approval["actor_id"] != verified_identity.get("actor_id"):
        raise GitHubScmError("approval actor differs from authenticated workflow actor")
    if approval["identity_provider"] != verified_identity.get("identity_provider"):
        raise GitHubScmError("approval provider differs from workflow identity provider")
    if approval["signature_ref"] != verified_identity.get("signature_ref"):
        raise GitHubScmError("approval signature reference differs from this workflow run")
    current = now or datetime.now(timezone.utc)
    issued = datetime.fromisoformat(approval["issued_at"].replace("Z", "+00:00"))
    expires = datetime.fromisoformat(approval["expires_at"].replace("Z", "+00:00"))
    if issued > current or expires <= current or (expires - issued).total_seconds() > 900:
        raise GitHubScmError("approval is not active under the 15 minute workflow policy")
    if approval["merge_allowed"] or approval["deploy_allowed"]:
        raise GitHubScmError("v1 GitHub execution cannot merge or deploy")
    required_actions = {"repository.read", "commit.create", "draft-pr.create"}
    if not required_actions <= set(approval["allowed_actions"]):
        raise GitHubScmError("approval lacks proposal SCM actions")
    change_path = _safe_relative_path(change["file_path"])
    if not _path_allowed(change_path, plan["allowed_paths"]):
        raise GitHubScmError("change path is outside the approved path set")
    if change["base_branch"] == change["proposal_branch"]:
        raise GitHubScmError("proposal branch cannot equal the base branch")
    return plan, approval, loads_strict(json.dumps(change, sort_keys=True))


def execute_bound_change(
    client: GitHubScmClient,
    plan: dict[str, Any],
    approval: dict[str, Any],
    change: dict[str, Any],
    *,
    expected_repository: str,
    expected_repository_id: str,
    verified_identity: Mapping[str, str],
    now: datetime | None = None,
) -> dict[str, Any]:
    plan, approval, change = validate_bound_change(
        plan,
        approval,
        change,
        expected_repository=expected_repository,
        expected_repository_id=expected_repository_id,
        verified_identity=verified_identity,
        now=now,
    )
    actual_base = client.base_commit(change["base_branch"])
    if actual_base != plan["base_commit"]:
        raise GitHubScmError("repository base commit differs from the approved plan")
    marker = f"<!-- {change['idempotency_marker']} -->"
    issue = client.ensure_issue(
        marker,
        change["issue_title"],
        f"{change['issue_body'].rstrip()}\n\n{marker}\n",
    )
    branch = client.ensure_branch(change["proposal_branch"], actual_base)
    committed = client.ensure_file(
        change["proposal_branch"],
        change["file_path"],
        change["file_content"].encode("utf-8"),
        change["commit_message"],
    )
    pull_request = client.ensure_draft_pull_request(
        marker,
        change["pull_request_title"],
        f"{change['pull_request_body'].rstrip()}\n\n{marker}\n",
        change["proposal_branch"],
        change["base_branch"],
    )
    return {
        "schema_version": "1.1.0",
        "repository": expected_repository,
        "repository_id": expected_repository_id,
        "base_commit": plan["base_commit"],
        "plan_digest": plan["plan_digest"],
        "approval_scope_digest": approval["scope_digest"],
        "actor_id": verified_identity["actor_id"],
        "identity_provider": verified_identity["identity_provider"],
        "identity_ref": verified_identity["signature_ref"],
        "issue": issue,
        "branch": branch,
        "commit": committed,
        "draft_pull_request": pull_request,
        "merge_performed": False,
        "deployment_performed": False,
    }


class GitHubJobClient:
    """Small REST client bound to one repository and a job-scoped token."""

    def __init__(self, repository: str, token: str) -> None:
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
            raise GitHubScmError("repository locator is malformed")
        if len(token) < 20:
            raise GitHubScmError("job token is unavailable")
        self.repository = repository
        self.owner, self.name = repository.split("/", 1)
        self._token = token

    def _request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        *,
        allow_missing: bool = False,
    ) -> Any:
        repository_root = f"/repos/{self.repository}"
        if path != repository_root and not path.startswith(repository_root + "/"):
            raise GitHubScmError("provider path escapes the repository scope")
        body = None
        if payload is not None:
            body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
        request = urllib.request.Request(
            "https://api.github.com" + path,
            data=body,
            method=method,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self._token}",
                "Content-Type": "application/json",
                "User-Agent": "agent-team-engineering-v1-conformance",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                encoded = response.read(MAX_RESPONSE_BYTES + 1)
        except urllib.error.HTTPError as error:
            if allow_missing and error.code == 404:
                return None
            raise GitHubScmError(f"GitHub API returned HTTP {error.code}") from None
        except (urllib.error.URLError, TimeoutError):
            raise GitHubScmError("GitHub API request failed") from None
        if len(encoded) > MAX_RESPONSE_BYTES:
            raise GitHubScmError("GitHub API response exceeds 5 MiB")
        try:
            return loads_strict(encoded)
        except ValueError:
            raise GitHubScmError("GitHub API response is not strict JSON") from None

    def _summary(
        self, record: dict[str, Any], *, created: bool, object_type: str
    ) -> dict[str, Any]:
        root = f"https://github.com/{self.repository}"
        api_root = f"https://api.github.com/repos/{self.repository}"
        if object_type in {"issue", "draft_pull_request"}:
            number = record.get("number")
            provider_id = record.get("node_id")
            external_ref = record.get("html_url")
            expected_segment = "issues" if object_type == "issue" else "pull"
            expected_prefix = "I_" if object_type == "issue" else "PR_"
            if (
                not isinstance(number, int)
                or isinstance(number, bool)
                or number < 1
                or not isinstance(provider_id, str)
                or not provider_id.startswith(expected_prefix)
                or external_ref != f"{root}/{expected_segment}/{number}"
            ):
                raise GitHubScmError(f"GitHub {object_type} response has the wrong identity type")
            if object_type == "issue" and "pull_request" in record:
                raise GitHubScmError("GitHub issue response is a pull request")
            if object_type == "draft_pull_request" and record.get("draft") is not True:
                raise GitHubScmError("GitHub pull request is not a draft")
        elif object_type == "branch":
            ref = record.get("ref")
            provider_id = record.get("node_id")
            external_ref = record.get("url")
            if (
                not isinstance(ref, str)
                or not ref.startswith("refs/heads/")
                or not isinstance(provider_id, str)
                or not provider_id.startswith("REF_")
                or external_ref != f"{api_root}/git/{ref}"
            ):
                raise GitHubScmError("GitHub branch response has the wrong identity type")
        elif object_type == "commit":
            provider_id = record.get("sha")
            external_ref = record.get("url")
            if (
                not isinstance(provider_id, str)
                or not OBJECT_ID.fullmatch(provider_id)
                or external_ref != f"{api_root}/git/commits/{provider_id}"
            ):
                raise GitHubScmError("GitHub commit response has the wrong identity type")
        else:
            raise GitHubScmError("GitHub object type is unsupported")
        return {
            "object_type": object_type,
            "external_ref": external_ref,
            "provider_id": provider_id,
            "created": created,
        }

    def base_commit(self, branch: str) -> str:
        encoded = urllib.parse.quote(branch, safe="")
        value = self._request("GET", f"/repos/{self.repository}/git/ref/heads/{encoded}")
        try:
            commit = str(value["object"]["sha"])
        except (KeyError, TypeError):
            raise GitHubScmError("GitHub branch response lacks a commit") from None
        if not OBJECT_ID.fullmatch(commit):
            raise GitHubScmError("GitHub branch commit is malformed")
        return commit

    def require_private_repository(self) -> None:
        value = self._request("GET", f"/repos/{self.repository}")
        if not isinstance(value, dict):
            raise GitHubScmError("GitHub repository metadata is malformed")
        if value.get("private") is not True:
            raise GitHubScmError("SCM conformance repository must be Private")
        if value.get("fork") is True or value.get("archived") is True:
            raise GitHubScmError("SCM conformance repository cannot be a fork or archive")

    def _all(self, path: str) -> list[dict[str, Any]]:
        value = self._request("GET", path)
        if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
            raise GitHubScmError("GitHub list response is malformed")
        return value

    def ensure_issue(self, marker: str, title: str, body: str) -> dict[str, Any]:
        for record in self._all(f"/repos/{self.repository}/issues?state=all&per_page=100"):
            if "pull_request" not in record and marker in str(record.get("body", "")):
                return self._summary(record, created=False, object_type="issue")
        value = self._request(
            "POST", f"/repos/{self.repository}/issues", {"title": title, "body": body}
        )
        return self._summary(value, created=True, object_type="issue")

    def ensure_branch(self, branch: str, base_commit: str) -> dict[str, Any]:
        encoded = urllib.parse.quote(branch, safe="")
        existing = self._request(
            "GET", f"/repos/{self.repository}/git/ref/heads/{encoded}", allow_missing=True
        )
        if existing is not None:
            return self._summary(existing, created=False, object_type="branch")
        value = self._request(
            "POST",
            f"/repos/{self.repository}/git/refs",
            {"ref": f"refs/heads/{branch}", "sha": base_commit},
        )
        return self._summary(value, created=True, object_type="branch")

    def _branch_head_commit(self, branch: str, *, created: bool) -> dict[str, Any]:
        encoded = urllib.parse.quote(branch, safe="")
        value = self._request("GET", f"/repos/{self.repository}/git/ref/heads/{encoded}")
        try:
            target = value["object"]
            commit = str(target["sha"])
            kind = target["type"]
        except (KeyError, TypeError):
            raise GitHubScmError("GitHub branch response lacks a commit identity") from None
        if kind != "commit" or not OBJECT_ID.fullmatch(commit):
            raise GitHubScmError("GitHub branch target is not a commit")
        return self._summary(target, created=created, object_type="commit")

    def ensure_file(
        self, branch: str, path: str, content: bytes, message: str
    ) -> dict[str, Any]:
        encoded_path = urllib.parse.quote(path, safe="/")
        encoded_branch = urllib.parse.quote(branch, safe="")
        endpoint = f"/repos/{self.repository}/contents/{encoded_path}"
        existing = self._request(
            "GET", f"{endpoint}?ref={encoded_branch}", allow_missing=True
        )
        if existing is not None:
            try:
                current = base64.b64decode(str(existing["content"]), validate=False)
            except (KeyError, ValueError, TypeError):
                raise GitHubScmError("GitHub file response is malformed") from None
            if current != content:
                raise GitHubScmError("proposal path already exists with different content")
            return self._branch_head_commit(branch, created=False)
        value = self._request(
            "PUT",
            endpoint,
            {
                "message": message,
                "content": base64.b64encode(content).decode("ascii"),
                "branch": branch,
            },
        )
        if not isinstance(value, dict) or not isinstance(value.get("commit"), dict):
            raise GitHubScmError("GitHub commit response is malformed")
        created_commit = value["commit"].get("sha")
        if not isinstance(created_commit, str) or not OBJECT_ID.fullmatch(created_commit):
            raise GitHubScmError("GitHub created commit identity is malformed")
        for delay in BRANCH_HEAD_CONSISTENCY_DELAYS:
            if delay:
                time.sleep(delay)
            summary = self._branch_head_commit(branch, created=True)
            if created_commit == summary["provider_id"]:
                return summary
        raise GitHubScmError("GitHub branch head differs from the created commit")

    def ensure_draft_pull_request(
        self, marker: str, title: str, body: str, head: str, base: str
    ) -> dict[str, Any]:
        query = urllib.parse.urlencode(
            {"state": "all", "head": f"{self.owner}:{head}", "base": base, "per_page": 100}
        )
        for record in self._all(f"/repos/{self.repository}/pulls?{query}"):
            if marker in str(record.get("body", "")):
                if record.get("draft") is not True or record.get("merged_at") is not None:
                    raise GitHubScmError("reconciled pull request is not an unmerged draft")
                return self._summary(
                    record, created=False, object_type="draft_pull_request"
                )
        value = self._request(
            "POST",
            f"/repos/{self.repository}/pulls",
            {"title": title, "body": body, "head": head, "base": base, "draft": True},
        )
        if not isinstance(value, dict) or value.get("draft") is not True:
            raise GitHubScmError("GitHub did not create a draft pull request")
        return self._summary(value, created=True, object_type="draft_pull_request")
