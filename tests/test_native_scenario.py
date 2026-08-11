from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.json_support import loads_strict
from core.native_scenario import run_native_reference_scenario
from core.schema_validation import validate_schema

ROOT = Path(__file__).resolve().parents[1]


class FixedClock:
    def __init__(self, value: float = 1_786_425_600.0) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value


class NativeScenarioTests(unittest.TestCase):
    def test_machine_conformance_profile_is_strict_and_keeps_production_closed(self) -> None:
        schema = loads_strict(
            (ROOT / "schemas/native-conformance-profile.schema.json").read_text(
                encoding="utf-8"
            )
        )
        profile = loads_strict(
            (ROOT / "acceptance/v08-native-conformance.json").read_text(encoding="utf-8")
        )
        self.assertEqual(validate_schema(profile, schema), [])
        self.assertEqual(profile["scenario"]["final_state"], "DRAFT_PR_READY")
        self.assertFalse(profile["authority_boundaries"]["production_integrations"])
        self.assertEqual(
            profile["authority_boundaries"]["gate_b_runner"],
            "GRANTED_DISPOSABLE_ONLY",
        )
        self.assertIn(
            profile["authority_boundaries"]["gate_c_external_write"],
            {"AUTHORIZED_EVIDENCE_PENDING", "GRANTED_DEDICATED_TEST_ONLY"},
        )
        self.assertEqual(
            profile["authority_boundaries"]["gate_d_release"],
            "GRANTED_V080_ONLY",
        )
        self.assertFalse(profile["scenario"]["real_scm_write"])
        self.assertFalse(profile["scenario"]["merge"])
        self.assertFalse(profile["scenario"]["deploy"])

    def test_no_network_reference_loop_stops_at_reviewed_draft_pr(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "native.sqlite3"
            result = run_native_reference_scenario(database, clock=FixedClock())
            self.assertEqual(result["status"], "REFERENCE_SCENARIO_PASSED")
            self.assertEqual(result["work_item"]["state"], "DRAFT_PR_READY")
            self.assertEqual(result["run"]["state"], "DRAFT_PR_READY")
            self.assertEqual(result["independent_review"]["changes_requested_rounds"], 1)
            self.assertTrue(
                set(result["independent_review"]["author_sessions"]).isdisjoint(
                    result["independent_review"]["reviewer_sessions"]
                )
            )
            self.assertEqual(result["draft_pr_ref"], "mock://draft-pr/1")
            self.assertEqual(result["invariants"]["status"], "VALID")
            self.assertEqual(result["invariants"]["effects"], 10)
            self.assertEqual(result["notification_status"], "SUCCEEDED")
            self.assertFalse(result["safety"]["external_network_used"])
            self.assertFalse(result["safety"]["untrusted_code_executed"])
            self.assertFalse(result["safety"]["real_scm_write_used"])
            self.assertFalse(result["safety"]["merge_enabled"])
            self.assertFalse(result["safety"]["deploy_enabled"])

    def test_replaying_the_complete_scenario_has_no_duplicate_events_or_effects(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "native.sqlite3"
            clock = FixedClock()
            first = run_native_reference_scenario(database, clock=clock)
            second = run_native_reference_scenario(database, clock=clock)
            self.assertEqual(first["work_item"], second["work_item"])
            self.assertEqual(first["run"], second["run"])
            self.assertEqual(
                first["invariants"]["audit"]["events"],
                second["invariants"]["audit"]["events"],
            )
            self.assertEqual(first["invariants"]["effects"], second["invariants"]["effects"])
            self.assertEqual(first["draft_pr_ref"], second["draft_pr_ref"])


if __name__ == "__main__":
    unittest.main()
