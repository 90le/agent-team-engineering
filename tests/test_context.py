from __future__ import annotations

import hashlib
import unittest
from pathlib import Path

from core.context import build_context_bundle


ROOT = Path(__file__).resolve().parents[1]


class ContextBundleTests(unittest.TestCase):
    def test_role_bundle_contains_only_selected_skill_and_valid_hashes(self) -> None:
        bundle = build_context_bundle(ROOT, "reviewer")
        paths = {record["path"] for record in bundle["files"]}
        self.assertIn("skills/review-change/SKILL.md", paths)
        self.assertNotIn("skills/implement-change/SKILL.md", paths)
        for record in bundle["files"]:
            self.assertEqual(
                record["sha256"],
                hashlib.sha256(record["content"].encode("utf-8")).hexdigest(),
            )

    def test_unknown_role_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            build_context_bundle(ROOT, "all-powerful-agent")


if __name__ == "__main__":
    unittest.main()
