from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "tools" / "agent_team.py"
EXAMPLE = ROOT / "examples" / "team-instance" / "input" / "instance.json"


def run_cli(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(CLI), *arguments],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )


class FactoryCliTests(unittest.TestCase):
    def test_doctor_reports_factory_identity_without_enabling_production(self) -> None:
        result = run_cli("doctor")
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["factory_version"], (ROOT / "VERSION").read_text().strip())
        self.assertFalse(report["production_integrations_enabled"])

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
