"""Schema-bound Codex, Claude, and deterministic model-router implementations."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from core.adapters import (
    AdapterContext,
    AdapterContractError,
    AdapterPermanentError,
)
from core.json_support import loads_strict
from core.schema_validation import validate_schema
from core.security import find_inline_secret
from core.team_creator import (
    _canonical_json,
    _load_object,
    _role_prompt,
    validate_blueprint_document,
)

ROOT = Path(__file__).resolve().parents[1]
RESULT_SCHEMA_PATH = ROOT / "schemas" / "agent-step-result.schema.json"
MAX_DRIVER_OUTPUT_BYTES = 1_000_000


def _cli_environment() -> dict[str, str]:
    """Keep model authentication in CLI sessions, not inherited secret variables."""

    environment = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": os.environ.get("HOME", "/nonexistent"),
        "LANG": os.environ.get("LANG", "C.UTF-8"),
        "LC_ALL": os.environ.get("LC_ALL", "C.UTF-8"),
        "NO_COLOR": "1",
    }
    for name in ("SSL_CERT_FILE", "SSL_CERT_DIR"):
        value = os.environ.get(name)
        if value:
            environment[name] = value
    return environment


def _digest(value: Any) -> str:
    content = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(content).hexdigest()


def _strict_result(value: Any, task: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise AdapterContractError("agent CLI did not return a JSON object")
    try:
        encoded = json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise AdapterContractError("agent result is not strict JSON") from exc
    if len(encoded) > MAX_DRIVER_OUTPUT_BYTES:
        raise AdapterContractError("agent result exceeds 1 MiB")
    secret = find_inline_secret(value)
    if secret:
        raise AdapterContractError("agent result contains an inline credential")
    schema = _load_object(RESULT_SCHEMA_PATH)
    issues = validate_schema(value, schema)
    if issues:
        details = "; ".join(f"{issue.path}: {issue.message}" for issue in issues)
        raise AdapterContractError(f"agent result violates contract: {details}")
    for field in ("task_id", "work_item_id", "role", "action", "expected_revision"):
        if value[field] != task[field]:
            raise AdapterContractError(f"agent result {field} differs from its task")
    evidence = value["evidence"]
    if not isinstance(evidence, dict):
        raise AdapterContractError("agent evidence must be an object")
    for key, item in evidence.items():
        if not isinstance(key, str) or not isinstance(item, str):
            raise AdapterContractError("agent evidence keys and values must be strings")
        if not key or len(key) > 100 or not item or len(item) > 4000:
            raise AdapterContractError("agent evidence contains an empty or oversized field")
    return value


def _result_envelope(result: dict[str, Any], request: dict[str, Any], provider: str) -> dict[str, Any]:
    request_id = "agent-" + _digest(
        {
            "provider": provider,
            "task_id": result["task_id"],
            "work_item_id": result["work_item_id"],
            "expected_revision": result["expected_revision"],
            "request_id": request["request_id"],
        }
    )[:32]
    return {
        "schema_version": "1.0.0",
        "status": "SUCCEEDED",
        "output": result,
        "external_ref": None,
        "provider_request_id": request_id,
        "reconciled": False,
        "error_code": None,
    }


class CliModelRouterAdapter:
    """Invoke only the CLI engine assigned to the task role in a locked blueprint."""

    adapter_id = "adapter.cli-model-router"

    def __init__(
        self,
        blueprint: dict[str, Any],
        project_roots: dict[str, Path],
        artifact_root: Path,
        *,
        command_runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
        binary_resolver: Callable[[str], str | None] = shutil.which,
        generic_cli_commands: Mapping[str, Sequence[str]] | None = None,
    ) -> None:
        findings = validate_blueprint_document(blueprint)
        errors = [finding for finding in findings if finding.severity == "ERROR"]
        if errors:
            raise AdapterPermanentError("CLI model router received an invalid blueprint")
        self.blueprint = loads_strict(_canonical_json(blueprint))
        self.bindings = {
            str(binding["role"]): binding for binding in self.blueprint["role_bindings"]
        }
        self.project_roots: dict[str, Path] = {}
        for project_id, supplied in project_roots.items():
            if supplied.is_symlink():
                raise AdapterPermanentError("agent project root must not be a symbolic link")
            resolved = supplied.resolve()
            if not resolved.is_dir():
                raise AdapterPermanentError("agent project root does not exist")
            self.project_roots[str(project_id)] = resolved
        if artifact_root.is_symlink():
            raise AdapterPermanentError("agent artifact root must not be a symbolic link")
        self.artifact_root = artifact_root.resolve()
        self.artifact_root.mkdir(parents=True, exist_ok=True)
        os.chmod(self.artifact_root, 0o700)
        self.command_runner = command_runner
        self.binary_resolver = binary_resolver
        self.generic_cli_commands: dict[str, tuple[str, ...]] = {}
        for role, supplied in (generic_cli_commands or {}).items():
            arguments = tuple(str(value) for value in supplied)
            if (
                not arguments
                or len(arguments) > 32
                or any(not value or len(value) > 1000 or "\x00" in value for value in arguments)
            ):
                raise AdapterPermanentError("generic CLI command registry is invalid")
            self.generic_cli_commands[str(role)] = arguments

    def _prompt(self, task: dict[str, Any], binding: dict[str, Any]) -> str:
        return (
            _role_prompt(str(task["role"]), binding)
            + "\n\n# Current bound task\n\n"
            + task["prompt"]
            + "\n\nReturn only one JSON object that satisfies the supplied output schema. "
            "Copy task_id, work_item_id, role, action and expected_revision exactly. "
            "A BLOCKED or FAILED result is safer than inventing evidence.\n\n"
            + _canonical_json(task)
        )

    def _run_codex(
        self,
        task: dict[str, Any],
        binding: dict[str, Any],
        project_root: Path,
        prompt: str,
    ) -> dict[str, Any]:
        binary = self.binary_resolver("codex")
        if not binary:
            raise AdapterPermanentError("Codex CLI is unavailable")
        with tempfile.TemporaryDirectory(prefix="codex-result-", dir=self.artifact_root) as temp:
            output = Path(temp) / "result.json"
            arguments = [
                binary,
                "exec",
                "--ephemeral",
                "--ignore-rules",
                "--color",
                "never",
                "--sandbox",
                str(binding["sandbox_mode"]),
                "--ask-for-approval",
                "never",
                "--output-schema",
                str(RESULT_SCHEMA_PATH),
                "--output-last-message",
                str(output),
                "-C",
                str(project_root),
            ]
            if binding["model"] is not None:
                arguments.extend(["--model", str(binding["model"])])
            if binding["reasoning_effort"] != "inherit":
                effort = json.dumps(str(binding["reasoning_effort"]))
                arguments.extend(["--config", f"model_reasoning_effort={effort}"])
            arguments.append("-")
            try:
                completed = self.command_runner(
                    arguments,
                    cwd=project_root,
                    input=prompt,
                    text=True,
                    capture_output=True,
                    timeout=int(task["budget"]["max_seconds"]),
                    check=False,
                    env=_cli_environment(),
                )
            except subprocess.TimeoutExpired as exc:
                raise AdapterPermanentError("Codex task exceeded its bound timeout") from exc
            if completed.returncode != 0:
                raise AdapterPermanentError("Codex task failed without a valid bound result")
            try:
                raw = output.read_bytes()
            except FileNotFoundError as exc:
                raise AdapterContractError("Codex did not publish its structured result") from exc
            if len(raw) > MAX_DRIVER_OUTPUT_BYTES:
                raise AdapterContractError("Codex result exceeds 1 MiB")
            try:
                value = loads_strict(raw.decode("utf-8"))
            except (UnicodeDecodeError, ValueError) as exc:
                raise AdapterContractError("Codex result is not strict UTF-8 JSON") from exc
            return _strict_result(value, task)

    def _run_claude(
        self,
        task: dict[str, Any],
        binding: dict[str, Any],
        project_root: Path,
        prompt: str,
    ) -> dict[str, Any]:
        binary = self.binary_resolver("claude")
        if not binary:
            raise AdapterPermanentError("Claude Code CLI is unavailable")
        schema = RESULT_SCHEMA_PATH.read_text(encoding="utf-8")
        permission = (
            "acceptEdits" if binding["sandbox_mode"] == "workspace-write" else "plan"
        )
        tools = (
            "Read,Glob,Grep,Edit,Write,Bash"
            if binding["sandbox_mode"] == "workspace-write"
            else "Read,Glob,Grep"
        )
        arguments = [
            binary,
            "--print",
            "--output-format",
            "json",
            "--json-schema",
            schema,
            "--permission-mode",
            permission,
            "--allowedTools",
            tools,
            "--safe-mode",
            "--no-session-persistence",
        ]
        if binding["model"] is not None:
            arguments.extend(["--model", str(binding["model"])])
        if binding["reasoning_effort"] != "inherit":
            arguments.extend(["--effort", str(binding["reasoning_effort"])])
        arguments.append(prompt)
        try:
            completed = self.command_runner(
                arguments,
                cwd=project_root,
                text=True,
                capture_output=True,
                timeout=int(task["budget"]["max_seconds"]),
                check=False,
                env=_cli_environment(),
            )
        except subprocess.TimeoutExpired as exc:
            raise AdapterPermanentError("Claude task exceeded its bound timeout") from exc
        if completed.returncode != 0:
            raise AdapterPermanentError("Claude task failed without a valid bound result")
        if len(completed.stdout.encode("utf-8")) > MAX_DRIVER_OUTPUT_BYTES:
            raise AdapterContractError("Claude result exceeds 1 MiB")
        try:
            envelope = loads_strict(completed.stdout)
        except ValueError as exc:
            raise AdapterContractError("Claude result is not strict JSON") from exc
        value: Any = envelope
        if isinstance(envelope, dict) and isinstance(envelope.get("structured_output"), dict):
            value = envelope["structured_output"]
        elif isinstance(envelope, dict) and isinstance(envelope.get("result"), str):
            try:
                value = loads_strict(str(envelope["result"]))
            except ValueError as exc:
                raise AdapterContractError("Claude result field is not strict JSON") from exc
        return _strict_result(value, task)

    def _run_generic_cli(
        self,
        task: dict[str, Any],
        binding: dict[str, Any],
        project_root: Path,
        prompt: str,
    ) -> dict[str, Any]:
        if binding["sandbox_mode"] != "read-only":
            raise AdapterPermanentError(
                "the portable generic CLI protocol is read-only in the v0.8 reference"
            )
        configured = self.generic_cli_commands.get(str(task["role"]))
        if configured is None:
            raise AdapterPermanentError("generic AI role has no explicit CLI command binding")
        binary = self.binary_resolver(configured[0])
        if not binary:
            raise AdapterPermanentError("generic AI CLI is unavailable")
        arguments = [binary, *configured[1:]]
        envelope = {
            "protocol": "agent-team.generic-cli/1.0.0",
            "task": task,
            "prompt": prompt,
            "output_schema": _load_object(RESULT_SCHEMA_PATH),
        }
        try:
            completed = self.command_runner(
                arguments,
                cwd=project_root,
                input=_canonical_json(envelope),
                text=True,
                capture_output=True,
                timeout=int(task["budget"]["max_seconds"]),
                check=False,
                env=_cli_environment(),
                shell=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise AdapterPermanentError("generic AI task exceeded its bound timeout") from exc
        if completed.returncode != 0:
            raise AdapterPermanentError("generic AI CLI failed without a valid bound result")
        encoded = completed.stdout.encode("utf-8")
        if len(encoded) > MAX_DRIVER_OUTPUT_BYTES:
            raise AdapterContractError("generic AI result exceeds 1 MiB")
        try:
            value = loads_strict(completed.stdout)
        except ValueError as exc:
            raise AdapterContractError("generic AI result is not strict JSON") from exc
        return _strict_result(value, task)

    def execute(self, request: dict[str, Any], context: AdapterContext) -> dict[str, Any]:
        del context
        task = request["payload"]
        role = str(task["role"])
        binding = self.bindings.get(role)
        if binding is None:
            raise AdapterPermanentError("task role is not bound by the team blueprint")
        project_root = self.project_roots.get(str(task["project_id"]))
        if project_root is None:
            raise AdapterPermanentError("task project has no isolated local workspace")
        engine = str(binding["engine"])
        prompt = self._prompt(task, binding)
        if engine == "codex":
            result = self._run_codex(task, binding, project_root, prompt)
        elif engine == "claude":
            result = self._run_claude(task, binding, project_root, prompt)
        elif engine == "generic-ai":
            result = self._run_generic_cli(task, binding, project_root, prompt)
        else:
            raise AdapterPermanentError(
                "OpenClaw roles require their ingress runtime or a manual result adapter"
            )
        return _result_envelope(result, request, engine)

    def reconcile(self, request: dict[str, Any], context: AdapterContext) -> None:
        del request, context
        return None


class DeterministicModelRouterAdapter:
    """No-network executable reference used by acceptance tests and the local demo."""

    adapter_id = "adapter.cli-model-router"

    def __init__(self, project_roots: dict[str, Path]) -> None:
        self.project_roots = {key: value.resolve() for key, value in project_roots.items()}

    def execute(self, request: dict[str, Any], context: AdapterContext) -> dict[str, Any]:
        del context
        task = request["payload"]
        action = str(task["action"])
        evidence: dict[str, str]
        summary: str
        if action == "accept_triage":
            evidence = {"decision": "accepted-reference", "risk": "LOW"}
            summary = "Reference triage accepted the bounded demonstration work."
        elif action == "write_spec":
            evidence = {
                "specification": "Add one deterministic reference change and preserve all existing behavior.",
                "acceptance_criteria": "Reference marker exists; declared tests pass; reviewer is independent.",
            }
            summary = "Reference product agent produced a bounded specification."
        elif action == "start_implementation":
            project_root = self.project_roots[str(task["project_id"])]
            marker = project_root / "agent-team-reference-change.md"
            if marker.exists():
                if marker.read_text(encoding="utf-8") != "# Agent Team reference change\n\nPASS\n":
                    raise AdapterPermanentError("reference marker already exists with other content")
            else:
                marker.write_text("# Agent Team reference change\n\nPASS\n", encoding="utf-8")
            evidence = {"change": "agent-team-reference-change.md", "result": "implemented"}
            summary = "Reference builder created the deterministic marker in its isolated worktree."
        elif action == "record_ci_pass":
            evidence = {"assessment": "passed", "runner_evidence": "verified"}
            summary = "Reference QA agent accepted the supplied successful runner evidence."
        elif action == "approve_review":
            evidence = {"decision": "approved", "review_scope": "current-branch-vs-base"}
            summary = "Reference reviewer approved the tested change independently."
        else:
            raise AdapterPermanentError("reference model router does not implement this action")
        result = {
            "schema_version": "1.0.0",
            "task_id": task["task_id"],
            "work_item_id": task["work_item_id"],
            "role": task["role"],
            "action": task["action"],
            "expected_revision": task["expected_revision"],
            "status": "COMPLETED",
            "summary": summary,
            "evidence": evidence,
            "artifact_refs": [],
            "cost_units": 0,
        }
        result = _strict_result(result, task)
        return _result_envelope(result, request, "deterministic-reference")

    def reconcile(self, request: dict[str, Any], context: AdapterContext) -> None:
        del request, context
        return None
