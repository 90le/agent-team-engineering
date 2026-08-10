from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "tools" / "agent_team.py"
ROOT_CLI = ROOT / "agent-team"
EXAMPLE = ROOT / "examples" / "team-instance" / "input" / "instance.json"


def run_cli(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(CLI), *arguments],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )


def run_root_cli(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(ROOT_CLI), *arguments],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )


class FactoryCliTests(unittest.TestCase):
    def test_root_cli_reports_release_version(self) -> None:
        result = run_root_cli("--version")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), (ROOT / "VERSION").read_text().strip())

    def test_root_cli_lists_context_first_presets(self) -> None:
        result = run_root_cli("presets")
        self.assertEqual(result.returncode, 0, result.stderr)
        records = {record["id"]: record for record in json.loads(result.stdout)["presets"]}
        self.assertEqual(records["software-lite"]["mode"], "lite")
        self.assertEqual(records["software-managed"]["mode"], "managed")

    def test_root_cli_creates_valid_lite_team_for_ordinary_user(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "team"
            created = run_root_cli(
                "create",
                "--preset",
                "software-lite",
                "--name",
                "CLI Product Team",
                "--project",
                "CLI Product",
                "--repo",
                "example/cli-product",
                "--provider",
                "github",
                "--platform",
                "codex",
                "--output",
                str(output),
            )
            self.assertEqual(created.returncode, 0, created.stderr)
            report = json.loads(created.stdout)
            self.assertEqual(report["mode"], "lite")
            self.assertFalse(report["managed_runtime_available"])
            validated = run_root_cli("context", "validate", "--root", str(output))
            self.assertEqual(validated.returncode, 0, validated.stdout + validated.stderr)
            self.assertTrue((output / "AI-START.md").is_file())
            self.assertFalse((output / ".codex-placeholder").exists())

    def test_root_cli_creates_arbitrary_custom_roles(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "team"
            created = run_root_cli(
                "create",
                "--preset",
                "custom",
                "--name",
                "Research Team",
                "--project",
                "Research Project",
                "--repo",
                "local/research",
                "--provider",
                "generic-git",
                "--platform",
                "generic-ai",
                "--role",
                "researcher:Researcher",
                "--role",
                "editor:Editor",
                "--output",
                str(output),
            )
            self.assertEqual(created.returncode, 0, created.stderr)
            self.assertEqual(json.loads(created.stdout)["roles"], ["researcher", "editor"])
            self.assertTrue((output / "ROLES/researcher.md").is_file())
            self.assertTrue((output / "SKILLS/perform-editor-work/SKILL.md").is_file())

    def test_local_locator_does_not_infer_github(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "team"
            created = run_root_cli(
                "create",
                "--preset",
                "software-lite",
                "--name",
                "Local Team",
                "--project",
                "Local Project",
                "--repo",
                "local/local-project",
                "--output",
                str(output),
            )
            self.assertEqual(created.returncode, 0, created.stderr)
            design = json.loads(
                (output / ".agent-team/team-design.json").read_text(encoding="utf-8")
            )
            self.assertEqual(design["project"]["provider"], "generic-git")
            self.assertEqual(design["project"]["repository"], "local/local-project")

    def test_doctor_reports_factory_identity_without_enabling_production(self) -> None:
        result = run_cli("doctor")
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["factory_version"], (ROOT / "VERSION").read_text().strip())
        self.assertFalse(report["production_integrations_enabled"])

    def test_adapter_catalog_is_secret_safe_and_does_not_load_plugins(self) -> None:
        result = run_cli("adapter", "catalog")
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertGreaterEqual(len(report["adapters"]), 9)
        self.assertFalse(report["dynamic_loading_enabled"])
        self.assertFalse(report["production_integrations_enabled"])
        self.assertNotIn("secret_refs", result.stdout)
        github = next(item for item in report["adapters"] if item["id"] == "adapter.github")
        issue = next(item for item in github["operations"] if item["name"] == "issue.create")
        self.assertEqual(issue["delivery"], "reconcile-before-retry")
        self.assertTrue(issue["project_scoped"])

    def test_instance_cli_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "instance"
            created = run_cli("instance", "init", "--config", str(EXAMPLE), "--output", str(output))
            self.assertEqual(created.returncode, 0, created.stderr)
            validated = run_cli("instance", "validate", "--root", str(output))
            self.assertEqual(validated.returncode, 0, validated.stdout + validated.stderr)
            inspected = run_cli("instance", "inspect", "--root", str(output))
            self.assertEqual(inspected.returncode, 0, inspected.stderr)
            summary = json.loads(inspected.stdout)
            self.assertEqual(summary["instance_id"], "instance.example-software-team")
            self.assertEqual(summary["errors"], 0)

            diagnosed = run_cli("doctor", "--instance", str(output))
            self.assertEqual(diagnosed.returncode, 0, diagnosed.stderr)
            doctor_report = json.loads(diagnosed.stdout)
            self.assertEqual(
                doctor_report["instance"]["instance_id"], "instance.example-software-team"
            )

    def test_invalid_configuration_fails_without_creating_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            config = base / "invalid.json"
            document = json.loads(EXAMPLE.read_text(encoding="utf-8"))
            document["autonomy"]["maximum"] = "A5"
            config.write_text(json.dumps(document), encoding="utf-8")
            output = base / "must-not-exist"
            result = run_cli("instance", "init", "--config", str(config), "--output", str(output))
            self.assertEqual(result.returncode, 2)
            self.assertIn("cannot exceed A2", result.stderr)
            self.assertFalse(output.exists())

    def test_adoption_cli_prepares_verifies_and_composes_without_target_write(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            target = base / "target"
            proposal = base / "proposal"
            candidate = base / "candidate.json"
            target.mkdir()
            marker = target / "package.json"
            marker.write_text('{"name":"demo"}\n', encoding="utf-8")
            before = marker.read_bytes()
            prepared = run_cli(
                "adopt-project",
                "--repo",
                str(target),
                "--output",
                str(proposal),
                "--provider",
                "github",
                "--locator",
                "owner/demo",
                "--default-branch",
                "main",
                "--project-id",
                "demo",
            )
            self.assertEqual(prepared.returncode, 0, prepared.stderr)
            verified = run_cli("adoption", "verify", "--root", str(proposal))
            self.assertEqual(verified.returncode, 0, verified.stderr)
            composed = run_cli(
                "adoption",
                "compose",
                "--base-config",
                str(EXAMPLE),
                "--proposal",
                str(proposal),
                "--output",
                str(candidate),
            )
            self.assertEqual(composed.returncode, 0, composed.stderr)
            self.assertEqual(marker.read_bytes(), before)
            self.assertEqual(json.loads(composed.stdout)["projects"][0]["id"], "project.demo")

    def test_approval_key_file_with_group_or_other_access_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            instance = base / "instance"
            evidence = base / "evidence.json"
            assertion = base / "assertion.json"
            key = base / "approval.key"
            evidence.write_text("{}\n", encoding="utf-8")
            assertion.write_text("{}\n", encoding="utf-8")
            key.write_bytes(b"local-cli-approval-key-material-32-bytes")
            key.chmod(0o644)
            self.assertEqual(
                run_cli(
                    "instance", "init", "--config", str(EXAMPLE), "--output", str(instance)
                ).returncode,
                0,
            )
            self.assertEqual(
                run_cli("runtime", "init", "--instance", str(instance)).returncode,
                0,
            )
            result = run_cli(
                "runtime",
                "apply",
                "--instance",
                str(instance),
                "--work-item",
                "work-does-not-matter",
                "--action",
                "approve_plan",
                "--actor-id",
                "human.project-owner",
                "--role",
                "owner",
                "--actor-kind",
                "human",
                "--expected-revision",
                "0",
                "--idempotency-key",
                "cli:approval:key-permissions",
                "--evidence",
                str(evidence),
                "--approval-assertion",
                str(assertion),
                "--approval-key-file",
                str(key),
                "--approval-provider",
                "approval-provider.cli-test",
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("deny group and other access", result.stderr)

    def test_persistent_runtime_cli_survives_commands_and_verified_restore(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            instance = base / "instance"
            restored_instance = base / "restored-instance"
            backup = base / "state-backup.sqlite3"
            evidence = base / "evidence.json"
            evidence.write_text('{"source":"feedback-example-001"}\n', encoding="utf-8")

            self.assertEqual(
                run_cli(
                    "instance", "init", "--config", str(EXAMPLE), "--output", str(instance)
                ).returncode,
                0,
            )
            self.assertEqual(
                run_cli("runtime", "init", "--instance", str(instance)).returncode,
                0,
            )
            ingested = run_cli(
                "runtime",
                "ingest",
                "--instance",
                str(instance),
                "--event",
                str(ROOT / "examples/feedback-to-release/input/feedback.json"),
                "--idempotency-key",
                "cli:feedback:1",
            )
            self.assertEqual(ingested.returncode, 0, ingested.stderr)
            work_id = json.loads(ingested.stdout)["work_item"]["id"]
            leased = run_cli(
                "runtime",
                "lease",
                "--instance",
                str(instance),
                "--work-item",
                work_id,
                "--actor-id",
                "agent-intake-cli",
                "--role",
                "public-intake",
                "--expected-revision",
                "0",
                "--idempotency-key",
                "cli:lease:1",
            )
            self.assertEqual(leased.returncode, 0, leased.stderr)
            lease_id = json.loads(leased.stdout)["lease"]["lease_id"]
            applied = run_cli(
                "runtime",
                "apply",
                "--instance",
                str(instance),
                "--work-item",
                work_id,
                "--action",
                "normalize",
                "--actor-id",
                "agent-intake-cli",
                "--role",
                "public-intake",
                "--expected-revision",
                "0",
                "--idempotency-key",
                "cli:transition:1",
                "--evidence",
                str(evidence),
                "--lease-id",
                lease_id,
            )
            self.assertEqual(applied.returncode, 0, applied.stderr)
            self.assertEqual(json.loads(applied.stdout)["work_item"]["state"], "NORMALIZED")
            verified = run_cli("runtime", "audit-verify", "--instance", str(instance))
            self.assertEqual(verified.returncode, 0, verified.stderr)
            self.assertTrue(json.loads(verified.stdout)["valid"])
            backed_up = run_cli(
                "runtime", "backup", "--instance", str(instance), "--output", str(backup)
            )
            self.assertEqual(backed_up.returncode, 0, backed_up.stderr)

            self.assertEqual(
                run_cli(
                    "instance", "init", "--config", str(EXAMPLE), "--output", str(restored_instance)
                ).returncode,
                0,
            )
            restored = run_cli(
                "runtime",
                "restore",
                "--instance",
                str(restored_instance),
                "--backup",
                str(backup),
            )
            self.assertEqual(restored.returncode, 0, restored.stderr)
            restored_status = run_cli("runtime", "status", "--instance", str(restored_instance))
            self.assertEqual(json.loads(restored_status.stdout)["work_items"], {"NORMALIZED": 1})


if __name__ == "__main__":
    unittest.main()
