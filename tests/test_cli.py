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
        self.assertEqual(report["factory_version"], "0.2.0")
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


if __name__ == "__main__":
    unittest.main()
