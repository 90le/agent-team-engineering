from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from core.context_team import create_context_team, validate_context_team, validate_design_document
from core.validation import validate_repository

ROOT = Path(__file__).resolve().parents[1]
PLUGIN_ROOT = ROOT / ".agents/plugins/plugins/agent-team"


class PublicDistributionTests(unittest.TestCase):
    def test_checked_in_context_example_is_semantic_and_compilable(self) -> None:
        design_path = ROOT / "examples/context-first/team-design.json"
        design = json.loads(design_path.read_text(encoding="utf-8"))
        self.assertEqual(validate_design_document(design), [])
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "team"
            report = create_context_team(design_path, output)
            self.assertEqual(report["status"], "VALID")
            self.assertEqual(report["roles"], ["researcher", "reviewer", "curator"])
            self.assertEqual(validate_context_team(output), [])

    def test_plugin_manifests_and_marketplaces_share_release_identity(self) -> None:
        version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
        codex = json.loads(
            (PLUGIN_ROOT / ".codex-plugin/plugin.json").read_text(encoding="utf-8")
        )
        claude = json.loads(
            (PLUGIN_ROOT / ".claude-plugin/plugin.json").read_text(encoding="utf-8")
        )
        self.assertEqual(codex["name"], "agent-team")
        self.assertEqual(claude["name"], "agent-team")
        self.assertEqual(codex["version"], version)
        self.assertEqual(claude["version"], version)
        self.assertEqual(codex["license"], "Apache-2.0")
        self.assertEqual(claude["license"], "Apache-2.0")

        codex_marketplace = json.loads(
            (ROOT / ".agents/plugins/marketplace.json").read_text(encoding="utf-8")
        )
        source = codex_marketplace["plugins"][0]["source"]
        self.assertEqual(source, {"source": "local", "path": "./plugins/agent-team"})
        self.assertEqual(
            (ROOT / ".agents/plugins" / source["path"]).resolve(), PLUGIN_ROOT.resolve()
        )

        claude_marketplace = json.loads(
            (ROOT / ".claude-plugin/marketplace.json").read_text(encoding="utf-8")
        )
        record = claude_marketplace["plugins"][0]
        self.assertEqual(record["version"], version)
        self.assertEqual((ROOT / record["source"]).resolve(), PLUGIN_ROOT.resolve())

    def test_discovery_bundle_is_self_contained_and_has_no_runtime_hooks(self) -> None:
        files = [path for path in PLUGIN_ROOT.rglob("*") if path.is_file()]
        self.assertTrue(files)
        self.assertFalse(any(path.is_symlink() for path in files))
        skill = PLUGIN_ROOT / "skills/bootstrap-agent-team/SKILL.md"
        content = skill.read_text(encoding="utf-8")
        self.assertTrue(content.startswith("---\nname: bootstrap-agent-team\n"))
        self.assertNotIn("TODO", content)
        for manifest_path in (
            PLUGIN_ROOT / ".codex-plugin/plugin.json",
            PLUGIN_ROOT / ".claude-plugin/plugin.json",
        ):
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertFalse({"mcpServers", "hooks", "commands"} & set(manifest))

    def test_validator_rejects_distribution_version_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            copied = Path(temporary) / "repository"
            shutil.copytree(
                ROOT,
                copied,
                ignore=shutil.ignore_patterns(".git", "__pycache__", "*.pyc"),
            )
            manifest_path = (
                copied / ".agents/plugins/plugins/agent-team/.codex-plugin/plugin.json"
            )
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["version"] = "9.9.9"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            findings = validate_repository(copied)
            self.assertTrue(
                any(
                    finding.path.endswith(".codex-plugin/plugin.json")
                    and "version must match" in finding.message
                    for finding in findings
                )
            )


if __name__ == "__main__":
    unittest.main()
