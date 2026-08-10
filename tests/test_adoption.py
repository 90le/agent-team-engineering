from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from core.adoption import scan_project, write_adoption_proposal


def tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


class AdoptionTests(unittest.TestCase):
    def test_scan_detects_project_without_modifying_it(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            source = base / "existing-app"
            source.mkdir()
            (source / "package.json").write_text('{"scripts":{"test":"node --test"}}\n', encoding="utf-8")
            (source / "pyproject.toml").write_text('[project]\nname="mixed-app"\n', encoding="utf-8")
            (source / ".env").write_text("TEST_ONLY_SECRET=not-copied\n", encoding="utf-8")
            workflow = source / ".github" / "workflows"
            workflow.mkdir(parents=True)
            (workflow / "ci.yml").write_text("name: ci\n", encoding="utf-8")
            before = tree_digest(source)

            output = base / "proposal"
            report = write_adoption_proposal(source, output)

            self.assertEqual(before, tree_digest(source))
            self.assertEqual(report["technologies"], ["node", "python"])
            self.assertEqual(report["github_workflows"], ["ci.yml"])
            self.assertTrue((output / "AI-BOOTSTRAP.md").is_file())
            self.assertTrue((output / ".agent-team" / "project.json").is_file())
            serialized = json.dumps(report)
            self.assertNotIn("not-copied", serialized)

    def test_proposal_cannot_write_inside_target_project(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "app"
            source.mkdir()
            with self.assertRaises(ValueError):
                write_adoption_proposal(source, source / ".agent-team-proposal")

    def test_missing_project_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaises(ValueError):
                scan_project(Path(temporary) / "missing")


if __name__ == "__main__":
    unittest.main()
