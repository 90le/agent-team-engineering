from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from core.validation import validate_repository

ROOT = Path(__file__).resolve().parents[1]


class ValidationTests(unittest.TestCase):
    def test_repository_passes_reference_validator(self) -> None:
        errors = [finding for finding in validate_repository(ROOT) if finding.severity == "ERROR"]
        self.assertEqual(errors, [], "\n".join(f"{e.path}: {e.message}" for e in errors))

    def test_secret_pattern_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "leak.txt").write_text("ghp_" + ("A" * 24), encoding="utf-8")
            findings = validate_repository(root)
            self.assertTrue(any("credential pattern" in finding.message for finding in findings))

    def test_malformed_required_json_is_reported_without_crashing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            copied = Path(temporary) / "repository"
            shutil.copytree(
                ROOT,
                copied,
                ignore=shutil.ignore_patterns(".git", "__pycache__", "*.pyc"),
            )
            (copied / "team-packs/software-delivery/team-pack.json").write_text(
                "{not-json\n", encoding="utf-8"
            )
            findings = validate_repository(copied)
            self.assertTrue(any("invalid JSON" in finding.message for finding in findings))


if __name__ == "__main__":
    unittest.main()
