from __future__ import annotations

import json
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

    def test_invalid_adapter_and_missing_authority_grant_are_reported(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            copied = Path(temporary) / "repository"
            shutil.copytree(
                ROOT,
                copied,
                ignore=shutil.ignore_patterns(".git", "__pycache__", "*.pyc"),
            )
            manifest_path = copied / "adapters/github/adapter.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["implementation"]["entrypoint"] = "os:system"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            findings = validate_repository(copied)
            self.assertTrue(
                any(
                    finding.path == "adapters/github/adapter.json"
                    and "does not match pattern" in finding.message
                    for finding in findings
                )
            )

            manifest["implementation"]["entrypoint"] = (
                "core.reference_adapters:GitHubReferenceAdapter"
            )
            manifest["operations"][0]["project_scope"]["payload_field"] = (
                "field_not_in_input_schema"
            )
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            findings = validate_repository(copied)
            self.assertTrue(
                any("project scope field is absent" in finding.message for finding in findings)
            )

            manifest["operations"][0]["project_scope"]["payload_field"] = "repository"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            policy_path = copied / "policies/adapter-authority.json"
            policy = json.loads(policy_path.read_text(encoding="utf-8"))
            policy["grants"] = [
                grant for grant in policy["grants"] if grant["operation"] != "issue.create"
            ]
            policy_path.write_text(json.dumps(policy), encoding="utf-8")
            findings = validate_repository(copied)
            self.assertTrue(
                any("operation has no authority grant" in finding.message for finding in findings)
            )

    def test_cross_ai_acceptance_profile_is_schema_validated(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            copied = Path(temporary) / "repository"
            shutil.copytree(
                ROOT,
                copied,
                ignore=shutil.ignore_patterns(".git", "__pycache__", "*.pyc"),
            )
            profile_path = copied / "acceptance/cross-ai-takeover.json"
            profile = json.loads(profile_path.read_text(encoding="utf-8"))
            profile["human_replay_required"] = False
            profile_path.write_text(json.dumps(profile), encoding="utf-8")

            findings = validate_repository(copied)

            self.assertTrue(
                any(
                    finding.path == "acceptance/cross-ai-takeover.json"
                    and "must equal True" in finding.message
                    for finding in findings
                )
            )


if __name__ == "__main__":
    unittest.main()
