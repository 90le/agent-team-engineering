from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from core.doctor import build_doctor_report, doctor_exit_code
from core.instance import init_instance

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "team-instance" / "input" / "instance.json"


class DoctorTests(unittest.TestCase):
    def test_factory_report_is_structured_and_production_remains_disabled(self) -> None:
        report = build_doctor_report()
        self.assertIn(report["overall"], {"PASS", "WARN"})
        self.assertEqual(report["factory_version"], "0.5.0")
        self.assertFalse(report["production_integrations_enabled"])
        self.assertTrue(any(check["id"] == "factory.contract" for check in report["checks"]))
        self.assertEqual(doctor_exit_code(report), 0)

    def test_instance_report_identifies_upgrade_and_runtime_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            instance = Path(temporary) / "instance"
            init_instance(EXAMPLE, instance)
            report = build_doctor_report(instance)
            self.assertEqual(report["instance"]["factory_version"], "0.5.0")
            self.assertFalse(report["instance"]["upgrade_available"])
            self.assertEqual(report["instance"]["runtime"]["state"], "ABSENT")
            self.assertIn(report["overall"], {"PASS", "WARN"})

    def test_interrupted_journal_is_a_failing_diagnostic(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            instance = Path(temporary) / "instance"
            init_instance(EXAMPLE, instance)
            journal = instance / "runtime" / ".factory-lifecycle-journal.json"
            journal.parent.mkdir()
            journal.write_text(json.dumps({"incomplete": True}) + "\n", encoding="utf-8")
            report = build_doctor_report(instance)
            lifecycle = next(
                check for check in report["checks"] if check["id"] == "instance.lifecycle-journal"
            )
            self.assertEqual(lifecycle["status"], "FAIL")
            self.assertEqual(report["overall"], "FAIL")
            self.assertEqual(doctor_exit_code(report), 1)


if __name__ == "__main__":
    unittest.main()
