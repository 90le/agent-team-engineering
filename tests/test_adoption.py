from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from core.adoption import (
    AdoptionError,
    compose_instance_candidate,
    scan_project,
    verify_adoption_proposal,
    write_adoption_proposal,
)

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "team-instance" / "input" / "instance.json"


def tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


class AdoptionTests(unittest.TestCase):
    def test_git_discovery_does_not_refresh_the_target_index(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "app"
            source.mkdir()
            (source / "README.md").write_text("project\n", encoding="utf-8")
            subprocess.run(["git", "init", "-q", str(source)], check=True)
            subprocess.run(["git", "-C", str(source), "config", "user.name", "Test"], check=True)
            subprocess.run(
                ["git", "-C", str(source), "config", "user.email", "test@example.invalid"],
                check=True,
            )
            subprocess.run(["git", "-C", str(source), "add", "README.md"], check=True)
            subprocess.run(
                ["git", "-C", str(source), "commit", "-q", "-m", "initial"], check=True
            )
            index = source / ".git" / "index"
            before = index.read_bytes()

            report = scan_project(source)

            self.assertEqual(report["source_dirty"], False)
            self.assertEqual(index.read_bytes(), before)

    def test_scan_detects_project_without_modifying_it(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            source = base / "existing-app"
            source.mkdir()
            (source / "package.json").write_text(
                '{"scripts":{"test":"node --test"}}\n', encoding="utf-8"
            )
            (source / "pyproject.toml").write_text(
                '[project]\nname="mixed-app"\n', encoding="utf-8"
            )
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

    def test_proposal_refuses_nonempty_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            source = base / "app"
            output = base / "proposal"
            source.mkdir()
            output.mkdir()
            (output / "owned-by-user.txt").write_text("preserve\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                write_adoption_proposal(source, output)
            self.assertEqual(
                (output / "owned-by-user.txt").read_text(encoding="utf-8"), "preserve\n"
            )

    def test_missing_project_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaises(ValueError):
                scan_project(Path(temporary) / "missing")

    def test_proposal_is_digest_bound_and_rejects_tampering(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            source = base / "app"
            proposal = base / "proposal"
            source.mkdir()
            (source / "go.mod").write_text("module example.test/app\n", encoding="utf-8")
            write_adoption_proposal(source, proposal)
            package = verify_adoption_proposal(proposal)
            self.assertEqual(package["mode"], "proposal-only")
            self.assertFalse(package["target_repository_mutated"])

            (proposal / "AI-BOOTSTRAP.md").write_text("tampered\n", encoding="utf-8")
            with self.assertRaisesRegex(AdoptionError, "digest differs"):
                verify_adoption_proposal(proposal)

    def test_candidate_adds_only_the_reviewed_proposal_project(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            source = base / "app"
            proposal = base / "proposal"
            candidate_path = base / "candidate.json"
            source.mkdir()
            before = tree_digest(source)
            write_adoption_proposal(
                source,
                proposal,
                provider="github",
                locator="owner/application",
                default_branch="main",
                project_id="application",
            )
            candidate = compose_instance_candidate(EXAMPLE, proposal, candidate_path)
            original = json.loads(EXAMPLE.read_text(encoding="utf-8"))

            self.assertEqual(before, tree_digest(source))
            self.assertEqual(candidate["autonomy"], original["autonomy"])
            self.assertEqual(candidate["adapters"], original["adapters"])
            self.assertEqual(
                candidate["projects"],
                [
                    {
                        "id": "project.application",
                        "provider": "github",
                        "locator": "owner/application",
                        "default_branch": "main",
                        "mode": "proposal-only",
                    }
                ],
            )
            self.assertTrue(candidate_path.is_file())

            with self.assertRaisesRegex(AdoptionError, "analyzed repository"):
                compose_instance_candidate(
                    EXAMPLE,
                    proposal,
                    source / "candidate-instance.json",
                )

    def test_provider_binding_requires_an_explicit_locator(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            source = base / "app"
            source.mkdir()
            with self.assertRaisesRegex(AdoptionError, "explicit repository locator"):
                write_adoption_proposal(
                    source,
                    base / "proposal",
                    provider="github",
                )

    def test_unsafe_default_branch_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            source = base / "app"
            source.mkdir()
            with self.assertRaisesRegex(AdoptionError, "safe Git branch"):
                write_adoption_proposal(
                    source,
                    base / "proposal",
                    default_branch="release/../production",
                )


if __name__ == "__main__":
    unittest.main()
