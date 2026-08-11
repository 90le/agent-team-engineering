from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from core.adapters import (
    AdapterContext,
    AdapterContractError,
    AdapterPermanentError,
    DenySecretResolver,
)
from core.agent_drivers import CliModelRouterAdapter, DeterministicModelRouterAdapter

ROOT = Path(__file__).resolve().parents[1]


def blueprint() -> dict:
    return json.loads(
        (ROOT / "examples/team-blueprint/input/team.json").read_text(encoding="utf-8")
    )


def task(role: str, action: str, *, revision: int = 2) -> dict:
    return {
        "schema_version": "1.0.0",
        "task_id": f"task-{role}-{action}",
        "work_item_id": "work-driver-test",
        "project_id": "project.example-product",
        "role": role,
        "action": action,
        "expected_revision": revision,
        "idempotency_key": f"driver:{role}:{action}:{revision}",
        "prompt": "Perform the bounded test task.",
        "context": {
            "framework_commit": "a" * 40,
            "project_base_commit": "c" * 40,
            "project_commit": "b" * 40,
            "paths": ["."],
        },
        "allowed_capabilities": ["work.read"],
        "budget": {"max_attempts": 1, "max_seconds": 60, "max_cost_units": 1},
    }


def result_for(value: dict, *, evidence: dict[str, str] | None = None) -> dict:
    return {
        "schema_version": "1.0.0",
        "task_id": value["task_id"],
        "work_item_id": value["work_item_id"],
        "role": value["role"],
        "action": value["action"],
        "expected_revision": value["expected_revision"],
        "status": "COMPLETED",
        "summary": "Bound test result.",
        "evidence": evidence or {"decision": "accepted"},
        "artifact_refs": [],
        "cost_units": 0,
    }


def request(value: dict) -> dict:
    return {"request_id": "request-driver-test", "payload": value}


CONTEXT = AdapterContext(
    instance_id="instance.driver-test",
    binding_config={},
    allowed_secret_refs=frozenset(),
    _resolver=DenySecretResolver(),
)


class CliModelRouterTests(unittest.TestCase):
    def test_codex_invocation_is_schema_bound_and_never_bypasses_sandbox(self) -> None:
        calls: list[list[str]] = []
        environments: list[dict[str, str]] = []

        def fake_runner(arguments: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
            calls.append(arguments)
            environments.append(dict(kwargs["env"]))
            output = Path(arguments[arguments.index("--output-last-message") + 1])
            output.write_text(json.dumps(result_for(work)), encoding="utf-8")
            return subprocess.CompletedProcess(arguments, 0, "", "")

        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            project = base / "project"
            project.mkdir()
            work = task("triage", "accept_triage")
            adapter = CliModelRouterAdapter(
                blueprint(),
                {"project.example-product": project},
                base / "artifacts",
                command_runner=fake_runner,
                binary_resolver=lambda name: f"/usr/bin/{name}",
            )
            envelope = adapter.execute(request(work), CONTEXT)
            self.assertEqual(envelope["status"], "SUCCEEDED")
            arguments = calls[0]
            self.assertIn("--output-schema", arguments)
            self.assertIn("--ignore-rules", arguments)
            self.assertEqual(arguments[arguments.index("--sandbox") + 1], "read-only")
            self.assertEqual(arguments[arguments.index("--ask-for-approval") + 1], "never")
            self.assertNotIn("--dangerously-bypass-approvals-and-sandbox", arguments)
            self.assertNotIn("OPENAI_API_KEY", environments[0])
            self.assertNotIn("ANTHROPIC_API_KEY", environments[0])

    def test_codex_builder_uses_workspace_write_with_bounded_auto_review(self) -> None:
        calls: list[list[str]] = []

        def fake_runner(arguments: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
            del kwargs
            calls.append(arguments)
            output = Path(arguments[arguments.index("--output-last-message") + 1])
            output.write_text(
                json.dumps(result_for(work, evidence={"change": "bounded"})),
                encoding="utf-8",
            )
            return subprocess.CompletedProcess(arguments, 0, "", "")

        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            project = base / "project"
            project.mkdir()
            work = task("builder", "start_implementation", revision=5)
            adapter = CliModelRouterAdapter(
                blueprint(),
                {"project.example-product": project},
                base / "artifacts",
                command_runner=fake_runner,
                binary_resolver=lambda name: f"/usr/bin/{name}",
            )
            adapter.execute(request(work), CONTEXT)
            arguments = calls[0]
            self.assertEqual(arguments[arguments.index("--sandbox") + 1], "workspace-write")
            self.assertEqual(arguments[arguments.index("--ask-for-approval") + 1], "never")
            self.assertNotIn("--dangerously-bypass-approvals-and-sandbox", arguments)

    def test_claude_read_only_role_uses_plan_mode_without_bypass(self) -> None:
        calls: list[list[str]] = []

        def fake_runner(arguments: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
            del kwargs
            calls.append(arguments)
            value = result_for(work, evidence={"decision": "approved"})
            return subprocess.CompletedProcess(
                arguments,
                0,
                json.dumps({"structured_output": value}),
                "",
            )

        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            project = base / "project"
            project.mkdir()
            work = task("reviewer", "approve_review", revision=8)
            adapter = CliModelRouterAdapter(
                blueprint(),
                {"project.example-product": project},
                base / "artifacts",
                command_runner=fake_runner,
                binary_resolver=lambda name: f"/usr/bin/{name}",
            )
            adapter.execute(request(work), CONTEXT)
            arguments = calls[0]
            self.assertEqual(arguments[arguments.index("--permission-mode") + 1], "plan")
            self.assertIn("--safe-mode", arguments)
            tools = arguments[arguments.index("--allowedTools") + 1]
            self.assertNotIn("Bash", tools)
            self.assertNotIn("--dangerously-skip-permissions", arguments)

    def test_mismatched_result_identity_and_credential_evidence_are_rejected(self) -> None:
        def mismatched(arguments: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
            del kwargs
            output = Path(arguments[arguments.index("--output-last-message") + 1])
            value = result_for(work)
            value["work_item_id"] = "work-other"
            output.write_text(json.dumps(value), encoding="utf-8")
            return subprocess.CompletedProcess(arguments, 0, "", "")

        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            project = base / "project"
            project.mkdir()
            work = task("triage", "accept_triage")
            adapter = CliModelRouterAdapter(
                blueprint(),
                {"project.example-product": project},
                base / "artifacts",
                command_runner=mismatched,
                binary_resolver=lambda name: f"/usr/bin/{name}",
            )
            with self.assertRaises(AdapterContractError):
                adapter.execute(request(work), CONTEXT)

    def test_generic_cli_uses_static_argv_stdin_protocol_and_read_only_role(self) -> None:
        calls: list[tuple[list[str], dict[str, object]]] = []

        def fake_runner(arguments: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
            calls.append((arguments, kwargs))
            return subprocess.CompletedProcess(
                arguments,
                0,
                json.dumps(result_for(work, evidence={"assessment": "bounded"})),
                "",
            )

        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            project = base / "project"
            project.mkdir()
            work = task("operations", "verify_operation", revision=9)
            adapter = CliModelRouterAdapter(
                blueprint(),
                {"project.example-product": project},
                base / "artifacts",
                command_runner=fake_runner,
                binary_resolver=lambda name: f"/opt/bin/{name}",
                generic_cli_commands={"operations": ("portable-agent", "--json-stdio")},
            )
            envelope = adapter.execute(request(work), CONTEXT)
            self.assertEqual(envelope["status"], "SUCCEEDED")
            arguments, kwargs = calls[0]
            self.assertEqual(arguments, ["/opt/bin/portable-agent", "--json-stdio"])
            self.assertFalse(kwargs["shell"])
            supplied = json.loads(str(kwargs["input"]))
            self.assertEqual(supplied["protocol"], "agent-team.generic-cli/1.0.0")
            self.assertEqual(supplied["task"]["task_id"], work["task_id"])
            environment = dict(kwargs["env"])
            self.assertNotIn("OPENAI_API_KEY", environment)
            self.assertNotIn("ANTHROPIC_API_KEY", environment)

    def test_generic_cli_requires_explicit_binding_and_rejects_workspace_write(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            project = base / "project"
            project.mkdir()
            work = task("operations", "verify_operation", revision=9)
            adapter = CliModelRouterAdapter(
                blueprint(),
                {"project.example-product": project},
                base / "artifacts",
            )
            with self.assertRaises(AdapterPermanentError):
                adapter.execute(request(work), CONTEXT)

            unsafe_blueprint = blueprint()
            for binding in unsafe_blueprint["role_bindings"]:
                if binding["role"] == "operations":
                    binding["sandbox_mode"] = "workspace-write"
            with self.assertRaises(AdapterPermanentError):
                CliModelRouterAdapter(
                    unsafe_blueprint,
                    {"project.example-product": project},
                    base / "other-artifacts",
                    generic_cli_commands={"operations": ("portable-agent",)},
                )


class DeterministicRouterTests(unittest.TestCase):
    def test_only_builder_action_changes_the_project(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            adapter = DeterministicModelRouterAdapter(
                {"project.example-product": project}
            )
            triage = task("triage", "accept_triage")
            adapter.execute(request(triage), CONTEXT)
            self.assertEqual(list(project.iterdir()), [])
            builder = task("builder", "start_implementation", revision=5)
            adapter.execute(request(builder), CONTEXT)
            self.assertTrue((project / "agent-team-reference-change.md").is_file())


if __name__ == "__main__":
    unittest.main()
