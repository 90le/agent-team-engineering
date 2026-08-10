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


if __name__ == "__main__":
    unittest.main()
