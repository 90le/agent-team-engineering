from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from core.team_creator import (
    TeamCreatorError,
    create_team,
    export_team_target,
    inspect_team,
    validate_blueprint_document,
    validate_team_directory,
)

ROOT = Path(__file__).resolve().parents[1]
BLUEPRINT = ROOT / "examples" / "team-blueprint" / "input" / "team.json"


def load_blueprint() -> dict:
    return json.loads(BLUEPRINT.read_text(encoding="utf-8"))


def write_json(path: Path, value: dict) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


class TeamBlueprintTests(unittest.TestCase):
    def test_example_covers_every_non_human_team_pack_role(self) -> None:
        document = load_blueprint()
        self.assertEqual(validate_blueprint_document(document), [])
        self.assertEqual(
            {binding["role"] for binding in document["role_bindings"]},
            {
                "public-intake",
                "triage",
                "product",
                "builder",
                "qa",
                "reviewer",
                "release",
                "operations",
            },
        )

    def test_missing_role_duplicate_role_and_human_role_are_rejected(self) -> None:
        document = load_blueprint()
        document["role_bindings"].pop()
        findings = validate_blueprint_document(document)
        self.assertTrue(any("roles are missing" in finding.message for finding in findings))

        document = load_blueprint()
        document["role_bindings"].append(copy.deepcopy(document["role_bindings"][0]))
        findings = validate_blueprint_document(document)
        self.assertTrue(any("bound once" in finding.message for finding in findings))

        document = load_blueprint()
        document["role_bindings"][0]["role"] = "owner"
        findings = validate_blueprint_document(document)
        self.assertTrue(any("human roles" in finding.message for finding in findings))

    def test_engine_target_and_sandbox_boundaries_are_enforced(self) -> None:
        document = load_blueprint()
        document["platform_targets"].remove("claude")
        findings = validate_blueprint_document(document)
        self.assertTrue(any("platform target" in finding.message for finding in findings))

        document = load_blueprint()
        builder = next(item for item in document["role_bindings"] if item["role"] == "builder")
        builder["sandbox_mode"] = "read-only"
        findings = validate_blueprint_document(document)
        self.assertTrue(any("builder requires" in finding.message for finding in findings))

        document = load_blueprint()
        reviewer = next(item for item in document["role_bindings"] if item["role"] == "reviewer")
        reviewer["sandbox_mode"] = "workspace-write"
        findings = validate_blueprint_document(document)
        self.assertTrue(any("reviewer must remain" in finding.message for finding in findings))

    def test_blueprint_requires_project_and_rejects_inline_credentials(self) -> None:
        document = load_blueprint()
        document["instance"]["projects"] = []
        findings = validate_blueprint_document(document)
        self.assertTrue(any("at least one target project" in finding.message for finding in findings))

        document = load_blueprint()
        document["role_bindings"][0]["model"] = "ghp_" + ("A" * 24)
        findings = validate_blueprint_document(document)
        self.assertTrue(any("inline secret" in finding.message for finding in findings))


class TeamCompilerTests(unittest.TestCase):
    def test_creation_produces_all_native_targets_and_a_valid_lock(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            team = Path(temporary) / "team"
            summary = create_team(BLUEPRINT, team)
            self.assertEqual(summary["status"], "VALID")
            self.assertEqual(summary["compiled_files"], 52)
            self.assertFalse(summary["external_integrations_enabled"])
            self.assertEqual(validate_team_directory(team), [])
            self.assertTrue((team / "platforms/openclaw/openclaw.fragment.json").is_file())
            self.assertTrue((team / "platforms/codex/.codex/agents/builder.toml").is_file())
            self.assertTrue((team / "platforms/claude/.claude/agents/reviewer.md").is_file())
            self.assertTrue((team / "platforms/generic-ai/roles/qa.md").is_file())

            fragment = json.loads(
                (team / "platforms/openclaw/openclaw.fragment.json").read_text(
                    encoding="utf-8"
                )
            )
            agents = fragment["agents"]["list"]
            self.assertEqual(len(agents), 9)
            intake = next(item for item in agents if item["id"].endswith("public-intake"))
            qa = next(item for item in agents if item["id"].endswith("-qa"))
            relay = next(item for item in agents if item["id"].endswith("approval-relay"))
            self.assertNotEqual(intake["workspace"], relay["workspace"])
            for agent in agents:
                self.assertEqual(agent["sandbox"], {"mode": "all", "scope": "agent"})
                self.assertNotIn("sandbox", agent["tools"])
                self.assertFalse(agent["tools"]["elevated"]["enabled"])
                self.assertIn("browser", agent["tools"]["deny"])
            self.assertIn("exec", qa["tools"]["deny"])
            self.assertIn("group:runtime", qa["tools"]["deny"])
            for agent in agents:
                for denied_group in (
                    "group:automation",
                    "group:messaging",
                    "group:nodes",
                    "group:sessions",
                    "group:agents",
                    "group:media",
                    "group:plugins",
                    "group:ui",
                ):
                    self.assertIn(denied_group, agent["tools"]["deny"])
            self.assertEqual(fragment["bindings"], [])
            claude_qa = (
                team / "platforms/claude/.claude/agents/qa.md"
            ).read_text(encoding="utf-8")
            self.assertIn("tools: Read, Glob, Grep\n", claude_qa)
            self.assertNotIn("tools: Read, Glob, Grep, Bash", claude_qa)

    def test_same_blueprint_generates_same_compiled_content(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            first = base / "first"
            second = base / "second"
            create_team(BLUEPRINT, first)
            create_team(BLUEPRINT, second)
            first_lock = json.loads(
                (first / ".agent-team/team.lock.json").read_text(encoding="utf-8")
            )
            second_lock = json.loads(
                (second / ".agent-team/team.lock.json").read_text(encoding="utf-8")
            )
            self.assertEqual(first_lock, second_lock)

    def test_creation_never_overwrites_or_writes_inside_factory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            existing = Path(temporary) / "existing"
            existing.mkdir()
            marker = existing / "owner.txt"
            marker.write_text("preserve\n", encoding="utf-8")
            with self.assertRaisesRegex(TeamCreatorError, "never overwrites"):
                create_team(BLUEPRINT, existing)
            self.assertEqual(marker.read_text(encoding="utf-8"), "preserve\n")

        with self.assertRaisesRegex(TeamCreatorError, "outside the Factory"):
            create_team(BLUEPRINT, ROOT / "must-not-be-created")

    def test_blueprint_and_compiled_file_drift_fail_validation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            team = base / "team"
            create_team(BLUEPRINT, team)
            blueprint_path = team / ".agent-team/team-blueprint.json"
            document = json.loads(blueprint_path.read_text(encoding="utf-8"))
            document["instance"]["display_name"] = "Changed without recompilation"
            write_json(blueprint_path, document)
            findings = validate_team_directory(team)
            self.assertTrue(any("blueprint changed" in finding.message for finding in findings))

            second = base / "second"
            create_team(BLUEPRINT, second)
            (second / "platforms/codex/AGENTS.md").write_text("tampered\n", encoding="utf-8")
            findings = validate_team_directory(second)
            self.assertTrue(any("digest differs" in finding.message for finding in findings))

    def test_compiled_symbolic_link_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            team = Path(temporary) / "team"
            create_team(BLUEPRINT, team)
            target = team / "platforms/generic-ai/README.md"
            original = target.with_name("README.original")
            target.rename(original)
            target.symlink_to(original.name)
            findings = validate_team_directory(team)
            self.assertTrue(any("symbolic link" in finding.message for finding in findings))

    def test_platform_export_is_non_overwriting_and_hash_manifested(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            team = base / "team"
            exported = base / "codex-overlay"
            create_team(BLUEPRINT, team)
            report = export_team_target(team, "codex", exported)
            self.assertEqual(report["status"], "EXPORTED")
            self.assertTrue((exported / ".codex/agents/builder.toml").is_file())
            manifest = json.loads(
                (exported / "agent-team-export.json").read_text(encoding="utf-8")
            )
            self.assertEqual(manifest["platform"], "codex")
            self.assertGreater(len(manifest["files"]), 1)
            with self.assertRaisesRegex(TeamCreatorError, "already exists"):
                export_team_target(team, "codex", exported)

    def test_inspection_rejects_invalid_team_instead_of_reporting_success(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            team = Path(temporary) / "team"
            create_team(BLUEPRINT, team)
            (team / "platforms/claude/CLAUDE.md").unlink()
            with self.assertRaisesRegex(TeamCreatorError, "compiled file is missing"):
                inspect_team(team)


if __name__ == "__main__":
    unittest.main()
