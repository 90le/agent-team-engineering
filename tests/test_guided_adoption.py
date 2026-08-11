from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from core.guided_adoption import (
    GuidedAdoptionError,
    apply_plan,
    build_plan,
    confirm_plan,
    load_plan,
    preview_plan,
    validate_plan,
    write_plan,
)


def make_project(base: Path, *, git: bool = False) -> Path:
    project = base / "product"
    project.mkdir()
    (project / "pyproject.toml").write_text(
        "[project]\nname = \"guided-example\"\nversion = \"0.1.0\"\n",
        encoding="utf-8",
    )
    (project / "README.md").write_text("# Guided example\n", encoding="utf-8")
    (project / "tests").mkdir()
    if git:
        for arguments in (
            ("init", "-b", "main"),
            ("config", "user.name", "Guided Test"),
            ("config", "user.email", "guided@example.invalid"),
            ("add", "."),
            ("commit", "-m", "initial"),
        ):
            subprocess.run(
                ["git", "-C", str(project), *arguments],
                check=True,
                capture_output=True,
                text=True,
            )
    return project


def software_plan(base: Path, project: Path, *, automation: str = "assisted") -> dict:
    return build_plan(
        project,
        purpose="software",
        goals=["Turn product requests into independently reviewed changes."],
        automation=automation,
        platforms=["codex", "claude"],
        team_name="Guided Product Team",
        project_name="Guided Product",
        owner="Product Owner",
        provider="github",
        repository="example/guided-product",
        default_branch="main",
        output_path=base / "team",
    )


class GuidedAdoptionPlanTests(unittest.TestCase):
    def test_software_intent_maps_to_plain_language_recommendation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            project = make_project(base)
            plan = software_plan(base, project)
            self.assertEqual(plan["state"], "DRAFT")
            self.assertEqual(plan["proposal"]["recommendation"]["preset"], "software-lite")
            self.assertEqual(plan["proposal"]["recommendation"]["mode"], "lite")
            self.assertEqual(plan["proposal"]["discovery"]["technologies"], ["python"])
            self.assertFalse(plan["proposal"]["effects"]["target_project_mutated"])
            self.assertFalse(plan["proposal"]["effects"]["external_writes"])
            self.assertIn("Why this fits", preview_plan(plan))

    def test_nonsoftware_scenarios_get_rich_roles_but_not_managed_authority(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            project = make_project(base)
            research = build_plan(
                project,
                purpose="research-knowledge",
                goals=["Build a durable, source-checked knowledge library."],
                automation="assisted",
                platforms=["generic-ai"],
                team_name="Knowledge Team",
                project_name="Knowledge Library",
                owner="Library Owner",
                provider="generic-git",
                repository="local/knowledge-library",
                default_branch="main",
                output_path=base / "research-team",
            )
            self.assertEqual(research["proposal"]["recommendation"]["preset"], "custom")
            self.assertGreaterEqual(len(research["proposal"]["intent"]["custom_roles"]), 5)
            with self.assertRaisesRegex(GuidedAdoptionError, "managed automation currently supports"):
                build_plan(
                    project,
                    purpose="content",
                    goals=["Publish content."],
                    automation="managed",
                    platforms=["generic-ai"],
                    team_name="Content Team",
                    project_name=None,
                    owner="Owner",
                    provider="generic-git",
                    repository=None,
                    default_branch="main",
                    output_path=base / "content-team",
                )
            with self.assertRaisesRegex(GuidedAdoptionError, "requires at least one"):
                build_plan(
                    project,
                    purpose="custom",
                    goals=["Perform a custom workflow."],
                    automation="files",
                    platforms=["generic-ai"],
                    team_name="Custom Team",
                    project_name=None,
                    owner="Owner",
                    provider="generic-git",
                    repository=None,
                    default_branch="main",
                    output_path=base / "custom-team",
                )

    def test_confirmation_is_digest_bound_and_tampering_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            project = make_project(base)
            plan_path = base / "plan.json"
            plan = software_plan(base, project)
            write_plan(plan, plan_path)
            with self.assertRaisesRegex(GuidedAdoptionError, "confirm"):
                apply_plan(plan_path)
            with self.assertRaisesRegex(GuidedAdoptionError, "does not match"):
                confirm_plan(plan_path, digest="sha256:" + ("0" * 64), approved_by="Owner")
            confirmed = confirm_plan(
                plan_path,
                digest=plan["proposal_digest"],
                approved_by="Product Owner",
            )
            self.assertEqual(confirmed["state"], "CONFIRMED")
            document = json.loads(plan_path.read_text(encoding="utf-8"))
            document["proposal"]["team"]["summary"] = "Changed after confirmation"
            plan_path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(GuidedAdoptionError, "digest"):
                load_plan(plan_path)

    def test_end_to_end_apply_creates_guided_team_without_touching_project(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            project = make_project(base)
            before = {
                path.relative_to(project).as_posix(): path.read_bytes()
                for path in project.rglob("*")
                if path.is_file()
            }
            plan_path = base / "plan.json"
            plan = software_plan(base, project)
            write_plan(plan, plan_path)
            confirm_plan(
                plan_path,
                digest=plan["proposal_digest"],
                approved_by="Product Owner",
            )
            report = apply_plan(plan_path)
            team = base / "team"
            self.assertEqual(report["status"], "VALID")
            self.assertFalse(report["target_project_mutated"])
            self.assertFalse(report["external_integrations_enabled"])
            self.assertTrue((team / "GETTING-STARTED.md").is_file())
            self.assertIn("You do not need to memorize role names", (team / "GETTING-STARTED.md").read_text(encoding="utf-8"))
            self.assertIn("First response contract", (team / "AI-START.md").read_text(encoding="utf-8"))
            after = {
                path.relative_to(project).as_posix(): path.read_bytes()
                for path in project.rglob("*")
                if path.is_file()
            }
            self.assertEqual(before, after)
            with self.assertRaisesRegex(GuidedAdoptionError, "already exists"):
                apply_plan(plan_path)

    def test_stale_commit_and_secret_or_unsafe_paths_fail(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            project = make_project(base, git=True)
            plan_path = base / "plan.json"
            plan = software_plan(base, project)
            write_plan(plan, plan_path)
            confirm_plan(
                plan_path,
                digest=plan["proposal_digest"],
                approved_by="Product Owner",
            )
            (project / "CHANGE.md").write_text("new commit\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(project), "add", "."], check=True)
            subprocess.run(
                ["git", "-C", str(project), "commit", "-m", "move target"],
                check=True,
                capture_output=True,
                text=True,
            )
            with self.assertRaisesRegex(GuidedAdoptionError, "commit changed"):
                apply_plan(plan_path)
            with self.assertRaisesRegex(GuidedAdoptionError, "outside the target project"):
                build_plan(
                    project,
                    purpose="software",
                    goals=["Unsafe output."],
                    automation="files",
                    platforms=["generic-ai"],
                    team_name="Unsafe Team",
                    project_name=None,
                    owner="Owner",
                    provider="generic-git",
                    repository=None,
                    default_branch="main",
                    output_path=project / "team",
                )
            secret_plan = software_plan(base / "secret-case", project)
            secret_plan["proposal"]["intent"]["goals"] = ["Use ghp_" + ("A" * 24)]
            with self.assertRaisesRegex(GuidedAdoptionError, "credential"):
                validate_plan(secret_plan)


if __name__ == "__main__":
    unittest.main()
