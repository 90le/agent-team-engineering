"""Restart-safe coordinator for a compiled Agent Team.

The reference path is intentionally local and deterministic. The live path may
invoke Codex/Claude CLIs and, only with a separate opt-in, create GitHub objects.
Neither path can merge a pull request or deploy production.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import shutil
import subprocess
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any, Callable

from core.adapters import AdapterHost, AdapterWorker, MappingSecretResolver
from core.agent_drivers import CliModelRouterAdapter, DeterministicModelRouterAdapter
from core.approval import HMACApprovalVerifier, issue_hmac_assertion
from core.control_plane import ControlPlane
from core.github_transport import GitHubCliTransport
from core.instance import is_safe_git_branch
from core.json_support import loads_strict
from core.models import Actor, FeedbackEvent, WorkflowState
from core.reference_adapters import GitHubReferenceAdapter
from core.schema_validation import validate_schema
from core.security import contains_credential_like, find_inline_secret, redact_credential_like
from core.team_creator import (
    BLUEPRINT_RELATIVE,
    ROOT,
    TEAM_LOCK_RELATIVE,
    _canonical_json,
    _load_object,
    validate_team_directory,
)

RUNNER_SCHEMA = ROOT / "schemas" / "runner-profile.schema.json"
SAFE_COMPONENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,199}$")
GIT_OBJECT_ID = re.compile(r"^[0-9a-f]{40}(?:[0-9a-f]{24})?$")
MAX_PROCESS_OUTPUT_BYTES = 1_000_000
TERMINAL_STATES = {
    WorkflowState.REJECTED,
    WorkflowState.BLOCKED,
    WorkflowState.ROLLED_BACK,
    WorkflowState.CLOSED,
}


class TeamRuntimeError(RuntimeError):
    """Raised when the coordinator must stop without widening authority."""


def _digest(value: Any) -> str:
    content = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(content).hexdigest()


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    if path.is_symlink():
        raise TeamRuntimeError(f"runtime artifact must not be a symbolic link: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(_canonical_json(value))
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _read_json(path: Path) -> dict[str, Any]:
    if path.is_symlink():
        raise TeamRuntimeError(f"runtime authority must not be a symbolic link: {path}")
    try:
        value = loads_strict(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise TeamRuntimeError(f"required runtime artifact is missing: {path}") from exc
    except ValueError as exc:
        raise TeamRuntimeError(f"runtime artifact is invalid JSON: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise TeamRuntimeError(f"runtime artifact root must be an object: {path}")
    return value


def _bounded_process(
    arguments: list[str],
    *,
    cwd: Path,
    timeout: int = 120,
    environment: dict[str, str] | None = None,
    input_value: str | None = None,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> subprocess.CompletedProcess[str]:
    if not arguments or any(not isinstance(value, str) or not value for value in arguments):
        raise TeamRuntimeError("process argv must contain non-empty strings")
    try:
        completed = runner(
            arguments,
            cwd=cwd,
            input=input_value,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
            env=environment,
        )
    except subprocess.TimeoutExpired as exc:
        raise TeamRuntimeError(f"bounded process timed out: {arguments[0]}") from exc
    size = len(completed.stdout.encode("utf-8")) + len(completed.stderr.encode("utf-8"))
    if size > MAX_PROCESS_OUTPUT_BYTES:
        raise TeamRuntimeError(f"bounded process output exceeded 1 MiB: {arguments[0]}")
    return completed


def _git(repo: Path, *arguments: str, timeout: int = 120) -> str:
    completed = _bounded_process(["git", *arguments], cwd=repo, timeout=timeout)
    if completed.returncode != 0:
        detail = redact_credential_like(completed.stderr.strip())[:1000]
        suffix = f": {detail}" if detail else ""
        raise TeamRuntimeError(f"git {' '.join(arguments[:2])} failed{suffix}")
    return completed.stdout


def _team_context(team_root: Path) -> tuple[Path, dict[str, Any], dict[str, Any], Path]:
    if team_root.is_symlink():
        raise TeamRuntimeError("team root must not be a symbolic link")
    root = team_root.resolve()
    findings = validate_team_directory(root)
    errors = [finding for finding in findings if finding.severity == "ERROR"]
    if errors:
        details = "; ".join(f"{finding.path}: {finding.message}" for finding in errors)
        raise TeamRuntimeError(f"compiled team is invalid: {details}")
    blueprint = _load_object(root / BLUEPRINT_RELATIVE)
    lock = _load_object(root / TEAM_LOCK_RELATIVE)
    instance = blueprint["instance"]
    database = (root / instance["runtime"]["state_location"]).resolve()
    if root not in database.parents:
        raise TeamRuntimeError("runtime database escaped the compiled team root")
    return root, blueprint, lock, database


def _project(blueprint: dict[str, Any], project_id: str) -> dict[str, Any]:
    for project in blueprint["instance"]["projects"]:
        if project["id"] == project_id:
            return project
    raise TeamRuntimeError(f"project is not declared by the team: {project_id}")


def _validate_repo(repo: Path, project: dict[str, Any], *, require_clean: bool) -> Path:
    if repo.is_symlink():
        raise TeamRuntimeError("project repository must not be a symbolic link")
    root = repo.resolve()
    if not root.is_dir():
        raise TeamRuntimeError("project repository does not exist")
    if _git(root, "rev-parse", "--is-inside-work-tree").strip() != "true":
        raise TeamRuntimeError("project path is not a Git work tree")
    default_ref = f"refs/heads/{project['default_branch']}"
    _git(root, "rev-parse", "--verify", default_ref)
    if require_clean and _git(root, "status", "--porcelain=v1", "--untracked-files=all").strip():
        raise TeamRuntimeError("source repository must be clean before creating an agent worktree")
    return root


def _artifact_directory(root: Path, blueprint: dict[str, Any], work_item_id: str) -> Path:
    if not SAFE_COMPONENT.fullmatch(work_item_id):
        raise TeamRuntimeError("work item id is unsafe for runtime artifact paths")
    artifact_root = (root / blueprint["instance"]["runtime"]["artifact_root"]).resolve()
    if root not in artifact_root.parents:
        raise TeamRuntimeError("artifact root escaped the compiled team")
    target = artifact_root / work_item_id
    target.mkdir(parents=True, exist_ok=True)
    os.chmod(target, 0o700)
    return target


def validate_runner_profile(document: dict[str, Any]) -> None:
    schema = _load_object(RUNNER_SCHEMA)
    issues = validate_schema(document, schema)
    if issues:
        details = "; ".join(f"{issue.path}: {issue.message}" for issue in issues)
        raise TeamRuntimeError(f"runner profile violates contract: {details}")
    if find_inline_secret(document):
        raise TeamRuntimeError("runner profile contains a credential-like value")
    working = Path(str(document["working_directory"]))
    if working.is_absolute() or ".." in working.parts:
        raise TeamRuntimeError("runner working directory must remain within the worktree")
    command_ids = [str(command["id"]) for command in document["commands"]]
    if len(command_ids) != len(set(command_ids)):
        raise TeamRuntimeError("runner command ids must be unique")
    for command in document["commands"]:
        for value in command["argv"]:
            if "\0" in value or "\n" in value or "\r" in value:
                raise TeamRuntimeError("runner argv contains a forbidden control character")


def _runtime_binding(instance: dict[str, Any], slot: str, adapter_id: str) -> None:
    for binding in instance["adapters"]:
        if binding["slot"] != slot:
            continue
        if not binding["enabled"] or binding["adapter_id"] != adapter_id:
            raise TeamRuntimeError(
                f"team must explicitly enable {adapter_id} in the {slot} slot"
            )
        return
    raise TeamRuntimeError(f"team has no {slot} adapter binding")


def _agent_identity(blueprint: dict[str, Any], role: str, mode: str) -> str:
    binding = next(item for item in blueprint["role_bindings"] if item["role"] == role)
    engine = "reference" if mode == "reference" else str(binding["engine"])
    return f"agent.{role}.{engine}"


def _role_capabilities(role: str) -> list[str]:
    team_pack = _load_object(ROOT / "team-packs/software-delivery/team-pack.json")
    for record in team_pack["roles"]:
        if record["id"] == role:
            return [str(value) for value in record["capabilities"]]
    raise TeamRuntimeError(f"role is not present in the team pack: {role}")


def _task_prompt(item: Any, action: str, artifact_dir: Path) -> str:
    specification = artifact_dir / "specification.json"
    spec_text = ""
    if specification.is_file():
        spec = _read_json(specification)
        spec_text = (
            f"\nApproved specification: {spec.get('specification')}\n"
            f"Acceptance criteria: {spec.get('acceptance_criteria')}\n"
            f"Scope hash: {spec.get('scope_hash')}\n"
        )
    runner_text = ""
    runner_path = artifact_dir / "runner-evidence.json"
    if runner_path.is_file():
        runner = _read_json(runner_path)
        runner_text = (
            f"\nRunner result: {runner.get('result')}\n"
            f"Runner evidence digest: {runner.get('evidence_digest')}\n"
            f"Tested commit: {runner.get('commit')}\n"
            f"Declared command results: "
            f"{[(record.get('id'), record.get('passed')) for record in runner.get('commands', [])]}\n"
        )
    instructions = {
        "accept_triage": "Assess whether this feedback is a bounded, reasonable project change.",
        "write_spec": (
            "Produce evidence fields specification and acceptance_criteria. Keep the scope "
            "specific enough for an owner to approve and a runner to verify."
        ),
        "start_implementation": (
            "Implement only the approved specification in this isolated Git worktree. Do not "
            "commit, push, merge, deploy, read credentials, or change the approval scope."
        ),
        "record_ci_pass": (
            "Review the durable local runner evidence. Return COMPLETED only when every declared "
            "command passed and the tested worktree remains clean."
        ),
        "approve_review": (
            "Independently review the current branch against its base and the approved scope. "
            "Return evidence decision=approved only when the implementation is safe and complete."
        ),
    }
    return (
        f"Action: {action}\nWork item: {item.id}\nTitle: {item.title}\n"
        f"Summary: {item.summary}\nRisk: {item.risk.value}\n"
        f"Untrusted directive detected: {item.untrusted_directive_detected}\n"
        f"{instructions[action]}{spec_text}{runner_text}"
    )


def _agent_result(
    control: ControlPlane,
    *,
    blueprint: dict[str, Any],
    lock: dict[str, Any],
    project: dict[str, Any],
    repo: Path,
    artifact_dir: Path,
    item: Any,
    role: str,
    action: str,
    mode: str,
    base_commit: str,
) -> dict[str, Any]:
    instance = blueprint["instance"]
    _runtime_binding(instance, "model", "adapter.cli-model-router")
    project_id = str(project["id"])
    project_commit = _git(repo, "rev-parse", "HEAD").strip()
    stable = hashlib.sha256(
        f"{item.id}\0{item.revision}\0{role}\0{action}".encode("utf-8")
    ).hexdigest()[:24]
    idempotency_key = f"team-runtime:agent:{stable}"
    prompt = _task_prompt(item, action, artifact_dir)
    if action == "approve_review":
        change = _git(
            repo,
            "diff",
            "--no-ext-diff",
            "--unified=3",
            "--no-color",
            f"{base_commit}...HEAD",
        )
        if contains_credential_like(change):
            raise TeamRuntimeError("review diff contains a credential-like value")
        prompt += "\nBound branch diff against the declared base:\n\n" + change[:40_000]
    task = {
        "schema_version": "1.0.0",
        "task_id": f"task-{stable}",
        "work_item_id": item.id,
        "project_id": project_id,
        "role": role,
        "action": action,
        "expected_revision": item.revision,
        "idempotency_key": idempotency_key,
        "prompt": prompt,
        "context": {
            "framework_commit": str(lock["factory"]["source_revision"]),
            "project_base_commit": base_commit,
            "project_commit": project_commit,
            "paths": ["."],
        },
        "allowed_capabilities": _role_capabilities(role),
        "budget": {
            "max_attempts": 1,
            "max_seconds": min(int(instance["limits"]["max_task_seconds"]), 3300),
            "max_cost_units": int(instance["limits"]["max_budget_units"]),
        },
    }
    authority = control.latest_authorization_event(item.id)
    queued = control.queue_effect(
        item.id,
        authorization_event_sequence=int(authority["sequence"]),
        adapter_slot="model",
        operation="agent.invoke",
        payload=task,
        idempotency_key=idempotency_key,
        max_attempts=1,
    )["effect"]
    if mode == "reference":
        implementation = DeterministicModelRouterAdapter({project_id: repo})
    elif mode == "live":
        implementation = CliModelRouterAdapter(
            blueprint,
            {project_id: repo},
            artifact_dir / "model-cli",
        )
    else:
        raise TeamRuntimeError(f"unsupported model mode: {mode}")
    host = AdapterHost(
        instance,
        [implementation],
        secret_resolver=MappingSecretResolver({}),
    )
    if queued["state"] == "COMPLETED":
        completed = queued
    elif queued["state"] in {"PENDING", "FAILED"}:
        lease_seconds = min(int(task["budget"]["max_seconds"]) + 60, 3600)
        result = AdapterWorker(
            control,
            host,
            f"worker.model.{stable}",
            lease_seconds=lease_seconds,
        ).run_effect(str(queued["effect_id"]))
        if result is None:
            raise TeamRuntimeError("model effect could not be claimed")
        completed = result["effect"]
    else:
        completed = queued
    if completed["state"] != "COMPLETED" or not isinstance(completed["result"], dict):
        raise TeamRuntimeError(
            f"model effect stopped in {completed['state']}: {completed.get('last_error')}"
        )
    output = completed["result"].get("output")
    if not isinstance(output, dict):
        raise TeamRuntimeError("model effect completed without a structured agent result")
    return output


def _lease_and_transition(
    control: ControlPlane,
    item: Any,
    action: str,
    actor: Actor,
    evidence: dict[str, str],
) -> dict[str, Any]:
    active = control.active_lease(item.id)
    if active is not None:
        if (
            active["actor_id"] != actor.id
            or active["actor_role"] != actor.role
            or active["revision"] != item.revision
        ):
            raise TeamRuntimeError("work item has an active lease owned by another task")
        lease = active
    else:
        lease = control.acquire_lease(
            item.id,
            actor,
            expected_revision=item.revision,
            ttl_seconds=3600,
            idempotency_key=f"team-runtime:lease:{uuid.uuid4()}",
        )["lease"]
    stable = hashlib.sha256(
        f"{item.id}\0{item.revision}\0{action}".encode("utf-8")
    ).hexdigest()[:32]
    return control.apply_transition(
        item.id,
        action,
        actor,
        evidence,
        expected_revision=item.revision,
        idempotency_key=f"team-runtime:transition:{stable}",
        lease_id=str(lease["lease_id"]),
    )


def _local_issue(artifact_dir: Path, item: Any) -> str:
    path = artifact_dir / "issue.json"
    if not path.exists():
        _atomic_json(
            path,
            {
                "schema_version": "1.0.0",
                "kind": "local-reference-issue",
                "work_item_id": item.id,
                "title": item.title,
                "body": item.summary,
                "external_ref": f"local-issue://{item.id}",
            },
        )
    return str(_read_json(path)["external_ref"])


def _github_host(instance: dict[str, Any]) -> AdapterHost:
    _runtime_binding(instance, "code-hosting", "adapter.github")
    return AdapterHost(
        instance,
        [GitHubReferenceAdapter(GitHubCliTransport())],
        secret_resolver=MappingSecretResolver({}),
    )


def _github_effect(
    control: ControlPlane,
    *,
    instance: dict[str, Any],
    item: Any,
    operation: str,
    payload: dict[str, Any],
    idempotency_suffix: str,
    authorization_sequence: int,
) -> str:
    key = f"team-runtime:github:{idempotency_suffix}:{item.id}"
    effect = control.queue_effect(
        item.id,
        authorization_event_sequence=authorization_sequence,
        adapter_slot="code-hosting",
        operation=operation,
        payload=payload,
        idempotency_key=key,
        max_attempts=int(instance["limits"]["max_attempts"]),
    )["effect"]
    if effect["state"] == "COMPLETED":
        completed = effect
    elif effect["state"] in {"PENDING", "FAILED"}:
        result = AdapterWorker(
            control,
            _github_host(instance),
            f"worker.github.{idempotency_suffix}",
            lease_seconds=120,
        ).run_effect(str(effect["effect_id"]))
        if result is None:
            raise TeamRuntimeError("GitHub effect could not be claimed")
        completed = result["effect"]
    else:
        completed = effect
    if completed["state"] != "COMPLETED" or not isinstance(completed["result"], dict):
        raise TeamRuntimeError(
            f"GitHub effect stopped in {completed['state']}: {completed.get('last_error')}"
        )
    external_ref = completed["result"].get("external_ref")
    if not isinstance(external_ref, str) or not external_ref:
        raise TeamRuntimeError("GitHub effect lacks an external reference")
    return external_ref


def _ensure_issue(
    control: ControlPlane,
    *,
    blueprint: dict[str, Any],
    project: dict[str, Any],
    artifact_dir: Path,
    item: Any,
    provider: str,
    allow_provider_writes: bool,
) -> str | None:
    if not blueprint["delivery"]["create_issue"]:
        return None
    artifact = artifact_dir / "issue.json"
    if artifact.is_file():
        return str(_read_json(artifact)["external_ref"])
    if provider == "local":
        return _local_issue(artifact_dir, item)
    if provider != "github":
        raise TeamRuntimeError(f"unsupported delivery provider: {provider}")
    if not allow_provider_writes:
        raise TeamRuntimeError("GitHub writes require --allow-provider-writes")
    if project["provider"] != "github":
        raise TeamRuntimeError("GitHub delivery requires a GitHub project binding")
    authority = control.latest_authorization_event(item.id)
    if authority["event"]["event_kind"] != "work.created":
        raise TeamRuntimeError("GitHub Issue creation lost its work.created authorization event")
    external_ref = _github_effect(
        control,
        instance=blueprint["instance"],
        item=item,
        operation="issue.create",
        payload={
            "repository": project["locator"],
            "work_item_id": item.id,
            "title": item.title,
            "body": (
                f"{item.summary}\n\n"
                "Created by Agent Team Engineering. Feedback remains untrusted input; "
                "implementation cannot start before the bound human plan approval."
            ),
        },
        idempotency_suffix="issue",
        authorization_sequence=int(authority["sequence"]),
    )
    _atomic_json(
        artifact,
        {
            "schema_version": "1.0.0",
            "kind": "github-issue",
            "work_item_id": item.id,
            "external_ref": external_ref,
        },
    )
    return external_ref


def _write_specification(
    artifact_dir: Path,
    item: Any,
    result: dict[str, Any],
    runner_profile: dict[str, Any],
    runtime_binding: dict[str, Any],
) -> dict[str, Any]:
    if result["status"] != "COMPLETED":
        raise TeamRuntimeError(f"product agent returned {result['status']}: {result['summary']}")
    evidence = result["evidence"]
    specification = str(evidence.get("specification", "")).strip()
    criteria = str(evidence.get("acceptance_criteria", "")).strip()
    if not specification or not criteria:
        raise TeamRuntimeError("product agent omitted specification or acceptance criteria")
    scope = {
        "work_item_id": item.id,
        "work_item_revision": item.revision,
        "specification": specification,
        "acceptance_criteria": criteria,
        "runner_profile_digest": _digest(runner_profile),
        "runner_command_ids": [str(command["id"]) for command in runner_profile["commands"]],
        "execution_binding": {
            key: runtime_binding[key]
            for key in (
                "project_id",
                "project_provider",
                "project_locator",
                "project_default_branch",
                "project_mode",
                "source_repo",
                "base_commit",
                "model_mode",
                "delivery_provider",
            )
        },
    }
    document = {"schema_version": "1.0.0", **scope, "scope_hash": _digest(scope)}
    _atomic_json(artifact_dir / "specification.json", document)
    return document


def _specification_scope(document: dict[str, Any]) -> dict[str, Any]:
    if document.get("schema_version") != "1.0.0":
        raise TeamRuntimeError("specification schema version is unsupported")
    scope = dict(document)
    scope.pop("schema_version", None)
    supplied_hash = str(scope.pop("scope_hash", ""))
    if not secrets.compare_digest(supplied_hash, _digest(scope)):
        raise TeamRuntimeError("specification scope hash differs from its contents")
    return scope


def _validate_bound_specification(
    artifact_dir: Path,
    item: Any,
    runner_profile: dict[str, Any],
    runtime_binding: dict[str, Any],
) -> dict[str, Any]:
    document = _read_json(artifact_dir / "specification.json")
    scope = _specification_scope(document)
    if scope.get("work_item_id") != item.id:
        raise TeamRuntimeError("specification belongs to another work item")
    if scope.get("runner_profile_digest") != _digest(runner_profile):
        raise TeamRuntimeError("specification Runner Profile binding changed")
    command_ids = [str(command["id"]) for command in runner_profile["commands"]]
    if scope.get("runner_command_ids") != command_ids:
        raise TeamRuntimeError("specification runner commands changed")
    expected_execution = {
        key: runtime_binding[key]
        for key in (
            "project_id",
            "project_provider",
            "project_locator",
            "project_default_branch",
            "project_mode",
            "source_repo",
            "base_commit",
            "model_mode",
            "delivery_provider",
        )
    }
    if scope.get("execution_binding") != expected_execution:
        raise TeamRuntimeError("specification execution binding changed")
    post_plan_states = {
        WorkflowState.PLAN_APPROVED,
        WorkflowState.IMPLEMENTING,
        WorkflowState.PR_OPEN,
        WorkflowState.CI_PASSED,
        WorkflowState.REVIEW_APPROVED,
    }
    if item.state in post_plan_states or item.plan_approved_by is not None:
        approved_hash = str(document["scope_hash"])
        approvals = [event for event in item.audit if event.action == "approve_plan"]
        if (
            len(approvals) != 1
            or item.plan_approved_by is None
            or approvals[0].actor_id != item.plan_approved_by
            or approvals[0].evidence.get("scope_hash") != approved_hash
        ):
            raise TeamRuntimeError("approved specification differs from the owner audit event")
    return document


def approve_team_plan(team_root: Path, work_item_id: str, scope_hash: str) -> dict[str, Any]:
    root, blueprint, _, database = _team_context(team_root)
    artifact_dir = _artifact_directory(root, blueprint, work_item_id)
    specification = _read_json(artifact_dir / "specification.json")
    _specification_scope(specification)
    if not secrets.compare_digest(str(specification.get("scope_hash", "")), scope_hash):
        raise TeamRuntimeError("supplied scope hash does not match the generated specification")
    owner_id = str(blueprint["instance"]["owner"]["id"])
    owner = Actor(owner_id, "owner", kind="human")
    key = secrets.token_bytes(32)
    provider = "approval-provider.local-owner-cli"
    now = time.time()
    approval_id = "approval-plan-" + scope_hash.removeprefix("sha256:")[:24]
    evidence = {"approval_id": approval_id, "scope_hash": scope_hash}
    with ControlPlane(
        database,
        create=False,
        approval_verifier=HMACApprovalVerifier(provider, key),
    ) as control:
        item = control.get_work_item(work_item_id)
        if item.state == WorkflowState.PLAN_APPROVED:
            return {
                "status": "ALREADY_APPROVED",
                "work_item": item.to_dict(),
                "scope_hash": scope_hash,
            }
        if item.state != WorkflowState.SPEC_READY:
            raise TeamRuntimeError(
                f"plan approval requires SPEC_READY, current state is {item.state.value}"
            )
        assertion = issue_hmac_assertion(
            key=key,
            provider=provider,
            assertion_id=approval_id,
            subject=owner.id,
            action="approve_plan",
            work_item_id=item.id,
            expected_revision=item.revision,
            evidence=evidence,
            issued_at_epoch=now,
            expires_at_epoch=now + 60,
            nonce=f"nonce-{uuid.uuid4()}",
            evidence_ref=f"local-owner-cli://{owner.id}/{approval_id}",
        )
        result = control.apply_transition(
            item.id,
            "approve_plan",
            owner,
            evidence,
            expected_revision=item.revision,
            idempotency_key=f"team-runtime:approval:{approval_id}",
            approval_assertion=assertion,
        )
        audit = control.verify_audit()
    return {
        "status": "PLAN_APPROVED",
        "work_item": result["work_item"],
        "scope_hash": scope_hash,
        "approval_provider": provider,
        "audit": audit,
        "trust_boundary": (
            "The local CLI binds the exact scope but relies on the operating-system user as the "
            "human identity boundary. Remote use requires an authenticated identity adapter."
        ),
    }


def _workspace(
    root: Path,
    blueprint: dict[str, Any],
    artifact_dir: Path,
    source_repo: Path,
    project: dict[str, Any],
    item: Any,
    base_commit: str,
) -> tuple[Path, str]:
    def validate_worktree(workspace: Path, branch: str) -> None:
        if not workspace.is_dir() or workspace.is_symlink():
            raise TeamRuntimeError("governed worktree path is not a safe directory")
        if _git(workspace, "rev-parse", "--show-toplevel").strip() != str(workspace):
            raise TeamRuntimeError("governed worktree path is not a Git worktree root")
        source_common = Path(
            _git(source_repo, "rev-parse", "--path-format=absolute", "--git-common-dir").strip()
        ).resolve()
        workspace_common = Path(
            _git(workspace, "rev-parse", "--path-format=absolute", "--git-common-dir").strip()
        ).resolve()
        if workspace_common != source_common:
            raise TeamRuntimeError("governed worktree belongs to another repository")
        if _git(workspace, "branch", "--show-current").strip() != branch:
            raise TeamRuntimeError("governed worktree uses an unexpected branch")
        completed = _bounded_process(
            [
                "git",
                "merge-base",
                "--is-ancestor",
                base_commit,
                "HEAD",
            ],
            cwd=workspace,
        )
        if completed.returncode != 0:
            raise TeamRuntimeError("governed worktree is not based on the declared branch")

    record_path = artifact_dir / "workspace.json"
    if record_path.is_file():
        record = _read_json(record_path)
        workspace = Path(str(record["path"]))
        branch = str(record["branch"])
        expected = (
            root / blueprint["instance"]["runtime"]["workspace_root"] / item.id
        ).resolve()
        if workspace.resolve() != expected or not workspace.is_dir() or workspace.is_symlink():
            raise TeamRuntimeError("recorded worktree is missing or outside its governed path")
        expected_record = {
            "schema_version": "1.0.0",
            "work_item_id": item.id,
            "source_repo": str(source_repo),
            "path": str(expected),
            "branch": f"agent-team/{item.id}",
            "base": str(project["default_branch"]),
            "base_commit": base_commit,
        }
        if record != expected_record:
            raise TeamRuntimeError("recorded worktree binding differs from the selected project")
        validate_worktree(workspace, branch)
        return workspace, branch

    workspace = (
        root / blueprint["instance"]["runtime"]["workspace_root"] / item.id
    ).resolve()
    if root not in workspace.parents:
        raise TeamRuntimeError("new worktree path escaped the governed team root")
    workspace.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(workspace.parent, 0o700)
    branch = f"agent-team/{item.id}"
    if not is_safe_git_branch(branch):
        raise TeamRuntimeError("generated agent branch is unsafe")
    if workspace.exists():
        validate_worktree(workspace, branch)
    else:
        current_base = _git(
            source_repo,
            "rev-parse",
            f"refs/heads/{project['default_branch']}",
        ).strip()
        if current_base != base_commit:
            raise TeamRuntimeError(
                "default branch moved after scope binding; create and approve a fresh work item"
            )
        _git(
            source_repo,
            "worktree",
            "add",
            "-b",
            branch,
            str(workspace),
            base_commit,
        )
        validate_worktree(workspace, branch)
    _atomic_json(
        record_path,
        {
            "schema_version": "1.0.0",
            "work_item_id": item.id,
            "source_repo": str(source_repo),
            "path": str(workspace),
            "branch": branch,
            "base": str(project["default_branch"]),
            "base_commit": base_commit,
        },
    )
    return workspace, branch


def _scan_staged_change(workspace: Path) -> None:
    names = _git(workspace, "diff", "--cached", "--name-only", "-z").split("\0")
    for name in (value for value in names if value):
        path = Path(name)
        if path.name in {".env", "id_rsa", "id_ed25519"} or path.suffix.casefold() in {
            ".key",
            ".pem",
        }:
            raise TeamRuntimeError(f"staged change contains a forbidden credential path: {name}")
        stages = _git(workspace, "ls-files", "--stage", "--", name)
        if any(line.startswith("120000 ") for line in stages.splitlines()):
            raise TeamRuntimeError(f"staged change contains a symbolic link: {name}")
    diff = _git(workspace, "diff", "--cached", "--no-ext-diff", "--unified=0", "--no-color")
    if contains_credential_like(diff):
        raise TeamRuntimeError("staged change contains a credential-like value")


def _commit_implementation(
    workspace: Path, artifact_dir: Path, item: Any, base_commit: str
) -> str:
    artifact = artifact_dir / "implementation.json"
    if artifact.is_file():
        record = _read_json(artifact)
        commit = str(record["commit"])
        if _git(workspace, "rev-parse", "HEAD").strip() != commit:
            raise TeamRuntimeError("implementation commit differs from its runtime artifact")
        if record.get("work_item_id") != item.id:
            raise TeamRuntimeError("implementation evidence belongs to another work item")
        if record.get("tree") != _git(workspace, "rev-parse", "HEAD^{tree}").strip():
            raise TeamRuntimeError("implementation tree differs from its runtime artifact")
        if _git(workspace, "rev-parse", "HEAD^").strip() != base_commit:
            raise TeamRuntimeError("implementation parent differs from the approved base commit")
        return commit
    intent_path = artifact_dir / "implementation-intent.json"
    dirty = _git(workspace, "status", "--porcelain=v1", "--untracked-files=all").strip()
    if not dirty:
        if not intent_path.is_file():
            raise TeamRuntimeError("builder completed without producing a repository change")
        intent = _read_json(intent_path)
        commit = _git(workspace, "rev-parse", "HEAD").strip()
        try:
            parent = _git(workspace, "rev-parse", "HEAD^").strip()
        except TeamRuntimeError as exc:
            raise TeamRuntimeError("interrupted implementation commit has no parent") from exc
        tree = _git(workspace, "rev-parse", "HEAD^{tree}").strip()
        expected = {
            "schema_version": "1.0.0",
            "work_item_id": item.id,
            "parent": parent,
            "tree": tree,
        }
        if intent != expected:
            raise TeamRuntimeError("interrupted implementation commit differs from its intent")
        if parent != base_commit:
            raise TeamRuntimeError("interrupted commit parent differs from the approved base")
        _atomic_json(
            artifact,
            {
                "schema_version": "1.0.0",
                "work_item_id": item.id,
                "commit": commit,
                "tree": tree,
            },
        )
        return commit

    _git(workspace, "add", "-A")
    _scan_staged_change(workspace)
    parent = _git(workspace, "rev-parse", "HEAD").strip()
    if parent != base_commit:
        raise TeamRuntimeError("builder changed commits outside the approved implementation")
    tree = _git(workspace, "write-tree").strip()
    intent = {
        "schema_version": "1.0.0",
        "work_item_id": item.id,
        "parent": parent,
        "tree": tree,
    }
    if intent_path.is_file():
        if _read_json(intent_path) != intent:
            raise TeamRuntimeError("staged implementation differs from its recorded intent")
    else:
        _atomic_json(intent_path, intent)
    _git(
        workspace,
        "-c",
        "user.name=Agent Team Builder",
        "-c",
        "user.email=agent-team@localhost",
        "commit",
        "-m",
        f"agent-team: {item.title[:60]}",
    )
    commit = _git(workspace, "rev-parse", "HEAD").strip()
    if _git(workspace, "rev-parse", "HEAD^").strip() != parent:
        raise TeamRuntimeError("implementation commit parent differs from its recorded intent")
    if _git(workspace, "rev-parse", "HEAD^{tree}").strip() != tree:
        raise TeamRuntimeError("implementation commit tree differs from its recorded intent")
    _atomic_json(
        artifact,
        {
            "schema_version": "1.0.0",
            "work_item_id": item.id,
            "commit": commit,
            "tree": tree,
        },
    )
    return commit


def _verify_github_remote(
    repo: Path, locator: str, default_branch: str, base_commit: str
) -> None:
    remote = _git(repo, "remote", "get-url", "origin").strip()
    normalized = remote.removesuffix(".git").removesuffix("/")
    accepted = {
        f"https://github.com/{locator}",
        f"ssh://git@github.com/{locator}",
        f"git@github.com:{locator}",
    }
    if normalized not in accepted:
        raise TeamRuntimeError("Git origin does not match the blueprint GitHub repository")
    remote_ref = _git(
        repo,
        "ls-remote",
        "--exit-code",
        "origin",
        f"refs/heads/{default_branch}",
        timeout=60,
    ).strip()
    remote_commit = remote_ref.split(maxsplit=1)[0] if remote_ref else ""
    if remote_commit != base_commit:
        raise TeamRuntimeError(
            "GitHub default branch differs from the human-approved base commit"
        )


def _open_draft_pr(
    control: ControlPlane,
    *,
    blueprint: dict[str, Any],
    project: dict[str, Any],
    artifact_dir: Path,
    workspace: Path,
    item: Any,
    branch: str,
    commit: str,
    base_commit: str,
    provider: str,
    allow_provider_writes: bool,
) -> str:
    artifact = artifact_dir / "pull-request.json"
    if artifact.is_file():
        return str(_read_json(artifact)["external_ref"])
    if provider == "local":
        external_ref = f"local-draft-pr://{item.id}/{commit[:12]}"
        kind = "local-draft-pr"
    elif provider == "github":
        if not allow_provider_writes:
            raise TeamRuntimeError("GitHub writes require --allow-provider-writes")
        if project["provider"] != "github":
            raise TeamRuntimeError("GitHub delivery requires a GitHub project binding")
        _verify_github_remote(
            workspace,
            str(project["locator"]),
            str(project["default_branch"]),
            base_commit,
        )
        _git(workspace, "push", "--set-upstream", "origin", branch, timeout=300)
        authority = control.latest_authorization_event(item.id)
        event = authority["event"]
        action = event.get("data", {}).get("transition", {}).get("action")
        if action != "start_implementation":
            raise TeamRuntimeError("Draft PR creation lacks start_implementation authority")
        external_ref = _github_effect(
            control,
            instance=blueprint["instance"],
            item=item,
            operation="pull-request.create",
            payload={
                "repository": project["locator"],
                "work_item_id": item.id,
                "title": item.title,
                "body": (
                    f"Automated proposal for `{item.id}`.\n\n"
                    "Human plan approval is recorded in the local audit chain. This pull request "
                    "is intentionally Draft and the Factory has no merge or deployment operation."
                ),
                "head": branch,
                "base": project["default_branch"],
                "draft": True,
            },
            idempotency_suffix="draft-pr",
            authorization_sequence=int(authority["sequence"]),
        )
        kind = "github-draft-pr"
    else:
        raise TeamRuntimeError(f"unsupported delivery provider: {provider}")
    _atomic_json(
        artifact,
        {
            "schema_version": "1.0.0",
            "kind": kind,
            "work_item_id": item.id,
            "external_ref": external_ref,
            "draft": True,
            "branch": branch,
            "base": project["default_branch"],
            "base_commit": base_commit,
            "commit": commit,
        },
    )
    return external_ref


def _run_profile(
    profile: dict[str, Any],
    *,
    workspace: Path,
    artifact_dir: Path,
    work_item_id: str,
    commit: str,
    allow_host_runner: bool,
) -> dict[str, Any]:
    if not allow_host_runner:
        raise TeamRuntimeError("host test execution requires --allow-host-runner")
    validate_runner_profile(profile)
    working = (workspace / str(profile["working_directory"])).resolve()
    if working != workspace and workspace not in working.parents:
        raise TeamRuntimeError("runner working directory escaped the agent worktree")
    if not working.is_dir() or working.is_symlink():
        raise TeamRuntimeError("runner working directory is missing or a symbolic link")
    evidence_path = artifact_dir / "runner-evidence.json"
    if evidence_path.is_file():
        evidence = _validate_runner_evidence(
            profile, artifact_dir, work_item_id, commit
        )
        if evidence["result"] != "PASSED":
            raise TeamRuntimeError("previous runner evidence records a failed command")
        return evidence
    home = artifact_dir / "runner-home"
    home.mkdir(parents=True, exist_ok=True)
    os.chmod(home, 0o700)
    environment = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": str(home),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "TZ": "UTC",
        "CI": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    results: list[dict[str, Any]] = []
    for command in profile["commands"]:
        started = time.monotonic()
        try:
            completed = _bounded_process(
                [str(value) for value in command["argv"]],
                cwd=working,
                timeout=int(command["timeout_seconds"]),
                environment=environment,
            )
            timed_out = False
        except TeamRuntimeError as exc:
            if "timed out" not in str(exc):
                raise
            completed = None
            timed_out = True
        duration_ms = int((time.monotonic() - started) * 1000)
        if completed is None:
            exit_code = None
            stdout = ""
            stderr = "timed out"
            passed = False
        else:
            exit_code = completed.returncode
            stdout = redact_credential_like(completed.stdout)[-20_000:]
            stderr = redact_credential_like(completed.stderr)[-20_000:]
            passed = completed.returncode == 0
        results.append(
            {
                "id": command["id"],
                "argv": command["argv"],
                "exit_code": exit_code,
                "timed_out": timed_out,
                "duration_ms": duration_ms,
                "stdout": stdout,
                "stderr": stderr,
                "passed": passed,
            }
        )
        if not passed:
            break
    if _git(workspace, "status", "--porcelain=v1", "--untracked-files=all").strip():
        raise TeamRuntimeError("test commands changed the committed agent worktree")
    evidence = {
        "schema_version": "1.0.0",
        "work_item_id": work_item_id,
        "commit": commit,
        "profile_digest": _digest(profile),
        "result": "PASSED" if len(results) == len(profile["commands"]) and all(
            result["passed"] for result in results
        ) else "FAILED",
        "commands": results,
    }
    evidence["evidence_digest"] = _digest(evidence)
    _atomic_json(evidence_path, evidence)
    if evidence["result"] != "PASSED":
        raise TeamRuntimeError("one or more declared test commands failed")
    return evidence


def _validate_runner_evidence(
    profile: dict[str, Any], artifact_dir: Path, work_item_id: str, commit: str
) -> dict[str, Any]:
    evidence = _read_json(artifact_dir / "runner-evidence.json")
    supplied_digest = str(evidence.get("evidence_digest", ""))
    digest_material = dict(evidence)
    digest_material.pop("evidence_digest", None)
    if not secrets.compare_digest(supplied_digest, _digest(digest_material)):
        raise TeamRuntimeError("runner evidence digest differs from its contents")
    if evidence.get("schema_version") != "1.0.0":
        raise TeamRuntimeError("runner evidence schema version is unsupported")
    if evidence.get("work_item_id") != work_item_id:
        raise TeamRuntimeError("runner evidence belongs to another work item")
    if evidence.get("commit") != commit:
        raise TeamRuntimeError("runner evidence commit differs from the Draft PR")
    if evidence.get("profile_digest") != _digest(profile):
        raise TeamRuntimeError("runner evidence profile differs from the approved profile")
    if evidence.get("result") not in {"PASSED", "FAILED"}:
        raise TeamRuntimeError("runner evidence has an invalid result")
    records = evidence.get("commands")
    if not isinstance(records, list) or len(records) > len(profile["commands"]):
        raise TeamRuntimeError("runner evidence command count is invalid")
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            raise TeamRuntimeError("runner evidence command is not an object")
        expected = profile["commands"][index]
        if record.get("id") != expected["id"] or record.get("argv") != expected["argv"]:
            raise TeamRuntimeError("runner evidence command differs from the approved profile")
        if record.get("passed") is True:
            if record.get("exit_code") != 0 or record.get("timed_out") is not False:
                raise TeamRuntimeError("runner evidence has inconsistent passing fields")
    passed = (
        len(records) == len(profile["commands"])
        and all(record.get("passed") is True for record in records)
    )
    if (evidence["result"] == "PASSED") != passed:
        raise TeamRuntimeError("runner evidence result differs from its command records")
    if find_inline_secret(evidence):
        raise TeamRuntimeError("runner evidence contains a credential-like value")
    return evidence


def _require_runner_audit(item: Any, evidence: dict[str, Any]) -> None:
    expected = (
        "local-runner://"
        + str(evidence["evidence_digest"]).removeprefix("sha256:")
    )
    events = [event for event in item.audit if event.action == "record_ci_pass"]
    if len(events) != 1 or events[0].evidence.get("check_run") != expected:
        raise TeamRuntimeError("Runner Evidence differs from the durable CI audit event")


def _require_draft_commit(
    workspace: Path,
    artifact_dir: Path,
    item: Any,
    project: dict[str, Any],
    base_commit: str,
) -> str:
    pull_request = _read_json(artifact_dir / "pull-request.json")
    if pull_request.get("draft") is not True:
        raise TeamRuntimeError("pull request evidence is not Draft")
    expected_branch = f"agent-team/{item.id}"
    if (
        pull_request.get("work_item_id") != item.id
        or pull_request.get("branch") != expected_branch
        or pull_request.get("base") != project["default_branch"]
        or pull_request.get("base_commit") != base_commit
        or _git(workspace, "branch", "--show-current").strip() != expected_branch
    ):
        raise TeamRuntimeError("Draft PR evidence differs from the work-item project binding")
    commit = str(pull_request.get("commit", ""))
    if not commit or _git(workspace, "rev-parse", "HEAD").strip() != commit:
        raise TeamRuntimeError("worktree HEAD differs from the recorded Draft PR commit")
    if _git(workspace, "status", "--porcelain=v1", "--untracked-files=all").strip():
        raise TeamRuntimeError("agent worktree changed after the recorded Draft PR")
    implementation = _read_json(artifact_dir / "implementation.json")
    if implementation.get("work_item_id") != item.id or implementation.get("commit") != commit:
        raise TeamRuntimeError("implementation evidence differs from the Draft PR commit")
    if _git(workspace, "rev-parse", "HEAD^").strip() != base_commit:
        raise TeamRuntimeError("Draft PR commit parent differs from the approved base commit")
    tree = _git(workspace, "rev-parse", "HEAD^{tree}").strip()
    if implementation.get("tree") != tree:
        raise TeamRuntimeError("implementation evidence differs from the Draft PR tree")
    return commit


def _status_report(
    control: ControlPlane,
    item: Any,
    artifact_dir: Path,
    *,
    status: str,
    next_action: str,
) -> dict[str, Any]:
    report: dict[str, Any] = {
        "status": status,
        "next_action": next_action,
        "work_item": item.to_dict(),
        "audit": control.verify_audit(),
        "hard_stops": ["human-plan-approval", "draft-pr", "no-merge", "no-production"],
    }
    for name, key in (
        ("issue.json", "issue"),
        ("specification.json", "specification"),
        ("pull-request.json", "pull_request"),
        ("runner-evidence.json", "runner_evidence"),
    ):
        path = artifact_dir / name
        if path.is_file():
            report[key] = _read_json(path)
    return report


def run_team(
    team_root: Path,
    work_item_id: str,
    repo: Path,
    runner_profile_path: Path,
    *,
    project_id: str | None = None,
    model_mode: str = "reference",
    provider: str = "local",
    allow_host_runner: bool = False,
    allow_provider_writes: bool = False,
) -> dict[str, Any]:
    """Advance one work item until a human gate, safe stop, or reviewed Draft PR."""

    root, blueprint, lock, database = _team_context(team_root)
    instance = blueprint["instance"]
    projects = instance["projects"]
    if project_id is None:
        if len(projects) != 1:
            raise TeamRuntimeError("multi-project teams require an explicit --project-id")
        project = projects[0]
    else:
        project = _project(blueprint, project_id)
    artifact_dir = _artifact_directory(root, blueprint, work_item_id)
    source_repo = _validate_repo(repo, project, require_clean=True)
    binding_path = artifact_dir / "project-binding.json"
    binding_base = {
        "schema_version": "1.0.0",
        "work_item_id": work_item_id,
        "project_id": project["id"],
        "project_provider": project["provider"],
        "project_locator": project["locator"],
        "project_default_branch": project["default_branch"],
        "project_mode": project["mode"],
        "source_repo": str(source_repo),
        "model_mode": model_mode,
        "delivery_provider": provider,
    }
    if binding_path.is_file():
        binding = _read_json(binding_path)
        base_commit = str(binding.get("base_commit", ""))
        if not GIT_OBJECT_ID.fullmatch(base_commit):
            raise TeamRuntimeError("work item has an invalid bound base commit")
        expected_binding = {**binding_base, "base_commit": base_commit}
        if binding != expected_binding:
            raise TeamRuntimeError("work item is already bound to a different project")
        resolved_base = _git(
            source_repo, "rev-parse", "--verify", f"{base_commit}^{{commit}}"
        ).strip()
        if resolved_base != base_commit:
            raise TeamRuntimeError("bound project base commit is unavailable")
    else:
        base_commit = _git(
            source_repo,
            "rev-parse",
            f"refs/heads/{project['default_branch']}",
        ).strip()
        if not GIT_OBJECT_ID.fullmatch(base_commit):
            raise TeamRuntimeError("project uses an unsupported Git object id")
        binding = {**binding_base, "base_commit": base_commit}
        _atomic_json(binding_path, binding)
    workspace_candidate = (
        root / instance["runtime"]["workspace_root"] / work_item_id
    ).resolve()
    if not (artifact_dir / "workspace.json").is_file() and not workspace_candidate.exists():
        current_base = _git(
            source_repo,
            "rev-parse",
            f"refs/heads/{project['default_branch']}",
        ).strip()
        if current_base != base_commit:
            raise TeamRuntimeError(
                "default branch moved after scope binding; create and approve a fresh work item"
            )
    if runner_profile_path.is_symlink():
        raise TeamRuntimeError("Runner Profile must not be a symbolic link")
    profile = _read_json(runner_profile_path.resolve())
    validate_runner_profile(profile)
    if profile["project_id"] != project["id"]:
        raise TeamRuntimeError("runner profile project differs from the team project")
    profile_binding_path = artifact_dir / "runner-profile-binding.json"
    profile_binding = {
        "schema_version": "1.0.0",
        "work_item_id": work_item_id,
        "project_id": project["id"],
        "profile_digest": _digest(profile),
    }
    if profile_binding_path.is_file():
        if _read_json(profile_binding_path) != profile_binding:
            raise TeamRuntimeError("runner profile changed after work-item binding")
    else:
        _atomic_json(profile_binding_path, profile_binding)

    database.parent.mkdir(parents=True, exist_ok=True)
    with ControlPlane(database, create=not database.exists()) as control:
        control.reconcile()
        for _ in range(16):
            item = control.get_work_item(work_item_id)
            specification_path = artifact_dir / "specification.json"
            if specification_path.is_file():
                _validate_bound_specification(
                    artifact_dir, item, profile, binding
                )
            if item.state in TERMINAL_STATES:
                return _status_report(
                    control,
                    item,
                    artifact_dir,
                    status="STOPPED",
                    next_action="human-inspection",
                )
            if item.state == WorkflowState.REVIEW_APPROVED:
                workspace, _ = _workspace(
                    root, blueprint, artifact_dir, source_repo, project, item, base_commit
                )
                commit = _require_draft_commit(
                    workspace, artifact_dir, item, project, base_commit
                )
                runner = _validate_runner_evidence(
                    profile, artifact_dir, item.id, commit
                )
                if runner["result"] != "PASSED":
                    raise TeamRuntimeError("final Runner Evidence did not pass")
                _require_runner_audit(item, runner)
                return _status_report(
                    control,
                    item,
                    artifact_dir,
                    status="DRAFT_PR_READY",
                    next_action="human-review-and-merge-outside-factory",
                )

            _ensure_issue(
                control,
                blueprint=blueprint,
                project=project,
                artifact_dir=artifact_dir,
                item=item,
                provider=provider,
                allow_provider_writes=allow_provider_writes,
            )

            if item.state == WorkflowState.RECEIVED:
                actor = Actor("agent.public-intake.control", "public-intake")
                _lease_and_transition(
                    control,
                    item,
                    "normalize",
                    actor,
                    {"source": item.source_event_id, "content_mode": "untrusted-data"},
                )
                continue
            if item.state == WorkflowState.NORMALIZED:
                actor = Actor("agent.public-intake.control", "public-intake")
                _lease_and_transition(
                    control,
                    item,
                    "queue_triage",
                    actor,
                    {"queue": "software-delivery", "idempotency_key": item.id},
                )
                continue
            if item.state == WorkflowState.TRIAGE_PENDING:
                result = _agent_result(
                    control,
                    blueprint=blueprint,
                    lock=lock,
                    project=project,
                    repo=source_repo,
                    artifact_dir=artifact_dir,
                    item=item,
                    role="triage",
                    action="accept_triage",
                    mode=model_mode,
                    base_commit=base_commit,
                )
                if result["status"] != "COMPLETED":
                    return _status_report(
                        control,
                        item,
                        artifact_dir,
                        status="BLOCKED",
                        next_action="human-triage",
                    )
                actor = Actor(_agent_identity(blueprint, "triage", model_mode), "triage")
                evidence = {
                    "decision": str(result["evidence"].get("decision", "accepted")),
                    "risk": str(result["evidence"].get("risk", item.risk.value)),
                }
                _lease_and_transition(control, item, "accept_triage", actor, evidence)
                continue
            if item.state == WorkflowState.ACCEPTED:
                result = _agent_result(
                    control,
                    blueprint=blueprint,
                    lock=lock,
                    project=project,
                    repo=source_repo,
                    artifact_dir=artifact_dir,
                    item=item,
                    role="product",
                    action="write_spec",
                    mode=model_mode,
                    base_commit=base_commit,
                )
                _write_specification(artifact_dir, item, result, profile, binding)
                actor = Actor(_agent_identity(blueprint, "product", model_mode), "product")
                _lease_and_transition(
                    control,
                    item,
                    "write_spec",
                    actor,
                    {
                        "spec_id": f"artifact://{item.id}/specification.json",
                        "acceptance_count": str(len(profile["commands"])),
                    },
                )
                continue
            if item.state == WorkflowState.SPEC_READY:
                return _status_report(
                    control,
                    item,
                    artifact_dir,
                    status="WAITING_FOR_HUMAN",
                    next_action=(
                        "team approve-plan --root TEAM --work-item WORK --scope-hash "
                        + str(_read_json(artifact_dir / "specification.json")["scope_hash"])
                    ),
                )
            if item.state == WorkflowState.PLAN_APPROVED:
                workspace, branch = _workspace(
                    root, blueprint, artifact_dir, source_repo, project, item, base_commit
                )
                result = _agent_result(
                    control,
                    blueprint=blueprint,
                    lock=lock,
                    project=project,
                    repo=workspace,
                    artifact_dir=artifact_dir,
                    item=item,
                    role="builder",
                    action="start_implementation",
                    mode=model_mode,
                    base_commit=base_commit,
                )
                if result["status"] != "COMPLETED":
                    return _status_report(
                        control,
                        item,
                        artifact_dir,
                        status="BLOCKED",
                        next_action="human-builder-inspection",
                    )
                actor = Actor(_agent_identity(blueprint, "builder", model_mode), "builder")
                _lease_and_transition(
                    control,
                    item,
                    "start_implementation",
                    actor,
                    {"workspace": str(workspace), "branch": branch},
                )
                continue
            if item.state == WorkflowState.IMPLEMENTING:
                workspace, branch = _workspace(
                    root, blueprint, artifact_dir, source_repo, project, item, base_commit
                )
                commit = _commit_implementation(
                    workspace, artifact_dir, item, base_commit
                )
                pull_request = _open_draft_pr(
                    control,
                    blueprint=blueprint,
                    project=project,
                    artifact_dir=artifact_dir,
                    workspace=workspace,
                    item=item,
                    branch=branch,
                    commit=commit,
                    base_commit=base_commit,
                    provider=provider,
                    allow_provider_writes=allow_provider_writes,
                )
                actor = Actor(_agent_identity(blueprint, "builder", model_mode), "builder")
                _lease_and_transition(
                    control,
                    item,
                    "open_pr",
                    actor,
                    {"pull_request": pull_request, "commit": commit},
                )
                continue
            if item.state == WorkflowState.PR_OPEN:
                if not allow_host_runner:
                    return _status_report(
                        control,
                        item,
                        artifact_dir,
                        status="WAITING_FOR_RUNNER",
                        next_action="supply --runner-profile and explicitly allow the runner",
                    )
                workspace, _ = _workspace(
                    root, blueprint, artifact_dir, source_repo, project, item, base_commit
                )
                commit = _require_draft_commit(
                    workspace, artifact_dir, item, project, base_commit
                )
                runner_evidence = _run_profile(
                    profile,
                    workspace=workspace,
                    artifact_dir=artifact_dir,
                    work_item_id=item.id,
                    commit=commit,
                    allow_host_runner=allow_host_runner,
                )
                result = _agent_result(
                    control,
                    blueprint=blueprint,
                    lock=lock,
                    project=project,
                    repo=workspace,
                    artifact_dir=artifact_dir,
                    item=item,
                    role="qa",
                    action="record_ci_pass",
                    mode=model_mode,
                    base_commit=base_commit,
                )
                runner_evidence = _validate_runner_evidence(
                    profile, artifact_dir, item.id, commit
                )
                if runner_evidence["result"] != "PASSED":
                    raise TeamRuntimeError("QA cannot accept failing Runner Evidence")
                if result["status"] != "COMPLETED":
                    return _status_report(
                        control,
                        item,
                        artifact_dir,
                        status="BLOCKED",
                        next_action="human-test-evidence-inspection",
                    )
                actor = Actor(_agent_identity(blueprint, "qa", model_mode), "qa")
                _lease_and_transition(
                    control,
                    item,
                    "record_ci_pass",
                    actor,
                    {
                        "check_run": (
                            "local-runner://"
                            + str(runner_evidence["evidence_digest"]).removeprefix("sha256:")
                        ),
                        "result": "passed",
                    },
                )
                continue
            if item.state == WorkflowState.CI_PASSED:
                workspace, _ = _workspace(
                    root, blueprint, artifact_dir, source_repo, project, item, base_commit
                )
                commit = _require_draft_commit(
                    workspace, artifact_dir, item, project, base_commit
                )
                runner = _validate_runner_evidence(
                    profile, artifact_dir, item.id, commit
                )
                if runner["result"] != "PASSED":
                    raise TeamRuntimeError("review input contains failing Runner Evidence")
                _require_runner_audit(item, runner)
                result = _agent_result(
                    control,
                    blueprint=blueprint,
                    lock=lock,
                    project=project,
                    repo=workspace,
                    artifact_dir=artifact_dir,
                    item=item,
                    role="reviewer",
                    action="approve_review",
                    mode=model_mode,
                    base_commit=base_commit,
                )
                if result["status"] != "COMPLETED" or result["evidence"].get(
                    "decision"
                ) != "approved":
                    return _status_report(
                        control,
                        item,
                        artifact_dir,
                        status="BLOCKED",
                        next_action="human-review-inspection",
                    )
                actor = Actor(
                    _agent_identity(blueprint, "reviewer", model_mode), "reviewer"
                )
                _lease_and_transition(
                    control,
                    item,
                    "approve_review",
                    actor,
                    {
                        "review_id": f"agent-review://{item.id}/{item.revision}",
                        "decision": "approved",
                    },
                )
                continue
            raise TeamRuntimeError(
                f"runtime refuses to advance unsupported state {item.state.value}"
            )
    raise TeamRuntimeError("coordinator exceeded its bounded transition count")


def ingest_team_feedback(
    team_root: Path,
    event_path: Path,
    *,
    idempotency_key: str,
) -> dict[str, Any]:
    root, blueprint, _, database = _team_context(team_root)
    del root, blueprint
    if event_path.is_symlink():
        raise TeamRuntimeError("feedback event must not be a symbolic link")
    event = FeedbackEvent.from_dict(_read_json(event_path.resolve()))
    database.parent.mkdir(parents=True, exist_ok=True)
    with ControlPlane(database, create=not database.exists()) as control:
        result = control.ingest_feedback(event, idempotency_key=idempotency_key)
        result["audit"] = control.verify_audit()
        return result


def create_reference_demo(output: Path) -> dict[str, Any]:
    """Create a portable no-network team, project, feedback item, and approval gate."""

    destination = output.resolve()
    if output.is_symlink() or destination.exists():
        raise TeamRuntimeError("demo output already exists; creation never overwrites")
    destination.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=f".{destination.name}.demo-", dir=destination.parent))
    try:
        project = stage / "project"
        project.mkdir()
        (project / "tests").mkdir()
        (project / "README.md").write_text("# Agent Team reference project\n", encoding="utf-8")
        (project / "tests/test_reference.py").write_text(
            "from pathlib import Path\n"
            "import unittest\n\n"
            "class ReferenceTest(unittest.TestCase):\n"
            "    def test_marker(self):\n"
            "        marker = Path(__file__).resolve().parents[1] / "
            "'agent-team-reference-change.md'\n"
            "        self.assertEqual(marker.read_text(encoding='utf-8'), "
            "'# Agent Team reference change\\n\\nPASS\\n')\n",
            encoding="utf-8",
        )
        _git(project, "init", "-b", "main")
        _git(project, "add", "-A")
        _git(
            project,
            "-c",
            "user.name=Reference Owner",
            "-c",
            "user.email=owner@localhost",
            "commit",
            "-m",
            "reference baseline",
        )

        blueprint = _load_object(ROOT / "examples/team-blueprint/input/team.json")
        blueprint["team_id"] = "team.reference-demo"
        blueprint["instance"]["instance_id"] = "instance.reference-demo"
        blueprint["instance"]["display_name"] = "Reference Demo Delivery Team"
        blueprint["instance"]["projects"] = [
            {
                "id": "project.reference-demo",
                "provider": "generic-git",
                "locator": "local/reference-demo",
                "default_branch": "main",
                "mode": "proposal-only",
            }
        ]
        for binding in blueprint["instance"]["adapters"]:
            binding["enabled"] = binding["slot"] == "model"
            binding["secret_refs"] = (
                ["secret.local-agent-session"] if binding["slot"] == "model" else []
            )
        blueprint_path = stage / "team-blueprint.json"
        _atomic_json(blueprint_path, blueprint)

        from core.team_creator import create_team

        team = stage / "team"
        create_team(blueprint_path, team)
        runner_profile = {
            "schema_version": "1.0.0",
            "project_id": "project.reference-demo",
            "working_directory": ".",
            "commands": [
                {
                    "id": "unit-tests",
                    "argv": ["python3", "-m", "unittest", "discover", "-s", "tests", "-v"],
                    "timeout_seconds": 120,
                }
            ],
        }
        _atomic_json(stage / "runner-profile.json", runner_profile)
        event = {
            "event_id": "feedback-reference-demo-1",
            "channel": "reference-im",
            "message_id": "reference-message-1",
            "received_at": "2026-08-10T00:00:00Z",
            "sender_ref": "reference-user",
            "content": "Please add the bounded reference marker while preserving existing behavior.",
        }
        _atomic_json(stage / "feedback.json", event)
        os.replace(stage, destination)
    except Exception:
        if stage.exists():
            shutil.rmtree(stage)
        raise

    team = destination / "team"
    project = destination / "project"
    ingested = ingest_team_feedback(
        team,
        destination / "feedback.json",
        idempotency_key="reference-demo:feedback:1",
    )
    work_item_id = str(ingested["work_item"]["id"])
    report = run_team(
        team,
        work_item_id,
        project,
        destination / "runner-profile.json",
        model_mode="reference",
        provider="local",
        allow_host_runner=True,
    )
    report.update(
        {
            "demo_root": str(destination),
            "team_root": str(team),
            "project_root": str(project),
            "runner_profile": str(destination / "runner-profile.json"),
            "work_item_id": work_item_id,
        }
    )
    return report
