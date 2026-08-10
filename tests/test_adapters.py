from __future__ import annotations

import json
import unittest
from pathlib import Path

from core.policy import ROLE_CAPABILITIES

ROOT = Path(__file__).resolve().parents[1]


class AdapterAndAuthorityTests(unittest.TestCase):
    def test_adapter_manifests_are_unique_replaceable_interfaces(self) -> None:
        manifests = [
            json.loads(path.read_text(encoding="utf-8"))
            for path in sorted((ROOT / "adapters").glob("*/adapter.json"))
        ]
        ids = [manifest["id"] for manifest in manifests]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertGreaterEqual(len(ids), 5)
        self.assertTrue(all(item["authority"] == "replaceable-interface" for item in manifests))

    def test_platform_entrypoints_remain_thin(self) -> None:
        for name in ("AGENTS.md", "CLAUDE.md", "AI-INSTRUCTIONS.md"):
            content = (ROOT / name).read_text(encoding="utf-8")
            self.assertIn("AI-BOOTSTRAP.md", content)
            self.assertLess(len(content), 500)

    def test_runtime_capabilities_are_loaded_from_team_pack(self) -> None:
        team = json.loads(
            (ROOT / "team-packs/software-delivery/team-pack.json").read_text(encoding="utf-8")
        )
        expected = {role["id"]: frozenset(role["capabilities"]) for role in team["roles"]}
        self.assertEqual(ROLE_CAPABILITIES, expected)

    def test_openclaw_public_intake_is_feedback_only(self) -> None:
        config = json.loads(
            (ROOT / "adapters/openclaw/public-intake-agent.json.example").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(config["allowed_tools"], ["feedback.submit"])
        self.assertIn("shell", config["denied_tools"])
        self.assertIn("deploy", config["denied_tools"])


if __name__ == "__main__":
    unittest.main()
