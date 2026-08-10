from __future__ import annotations

import unittest

from tools.cross_ai_takeover import run_takeover_acceptance


class CrossAiTakeoverTests(unittest.TestCase):
    def test_clean_context_takeover_acceptance(self) -> None:
        report = run_takeover_acceptance()
        self.assertEqual(report["status"], "PASS")
        self.assertTrue(report["automated_only"])
        self.assertTrue(report["human_replay_required"])
        self.assertTrue(report["target_repository_unchanged"])
        self.assertFalse(report["external_integrations_enabled"])
        self.assertEqual(report["team_reference"]["initial_stop"], "SPEC_READY")
        self.assertEqual(report["team_reference"]["final_state"], "REVIEW_APPROVED")
        self.assertEqual(report["team_reference"]["tests"], "PASSED")
        self.assertTrue(report["team_reference"]["independent_reviewer"])
        self.assertTrue(report["team_reference"]["replay_events_unchanged"])


if __name__ == "__main__":
    unittest.main()
