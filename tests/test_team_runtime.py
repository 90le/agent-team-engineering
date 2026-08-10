from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from core.team_creator import create_team
from core.team_runtime import (
    TeamRuntimeError,
    _commit_implementation,
    _run_profile,
    approve_team_plan,
    create_reference_demo,
    run_team,
    validate_runner_profile,
)

ROOT = Path(__file__).resolve().parents[1]


def git(repo: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", *arguments],
        cwd=repo,
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()


class TeamRuntimeAcceptanceTests(unittest.TestCase):
    def test_default_branch_cannot_move_between_scope_binding_and_implementation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            demo = Path(temporary) / "demo"
            first = create_reference_demo(demo)
            execution = first["specification"]["execution_binding"]
            self.assertEqual(execution["source_repo"], str((demo / "project").resolve()))
            self.assertEqual(
                execution["base_commit"], git(demo / "project", "rev-parse", "HEAD")
            )
            (demo / "project/base-moved.md").write_text("new base\n", encoding="utf-8")
            git(demo / "project", "add", "base-moved.md")
            subprocess.run(
                [
                    "git",
                    "-c",
                    "user.name=Project Maintainer",
                    "-c",
                    "user.email=maintainer@localhost",
                    "commit",
                    "-m",
                    "move default branch",
                ],
                cwd=demo / "project",
                text=True,
                capture_output=True,
                check=True,
            )
            approve_team_plan(
                demo / "team", first["work_item_id"], first["specification"]["scope_hash"]
            )
            with self.assertRaisesRegex(TeamRuntimeError, "default branch moved"):
                run_team(
                    demo / "team",
                    first["work_item_id"],
                    demo / "project",
                    demo / "runner-profile.json",
                    model_mode="reference",
                    provider="local",
                    allow_host_runner=True,
                )

    def test_interrupted_worktree_and_commit_artifacts_are_reconciled(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            demo = Path(temporary) / "demo"
            first = create_reference_demo(demo)
            work_id = first["work_item_id"]
            approve_team_plan(demo / "team", work_id, first["specification"]["scope_hash"])
            waiting = run_team(
                demo / "team",
                work_id,
                demo / "project",
                demo / "runner-profile.json",
                model_mode="reference",
                provider="local",
                allow_host_runner=False,
            )
            self.assertEqual(waiting["work_item"]["state"], "PR_OPEN")
            artifact_dir = demo / "team/runtime/artifacts" / work_id
            (artifact_dir / "workspace.json").unlink()
            completed = run_team(
                demo / "team",
                work_id,
                demo / "project",
                demo / "runner-profile.json",
                model_mode="reference",
                provider="local",
                allow_host_runner=True,
            )
            self.assertEqual(completed["status"], "DRAFT_PR_READY")
            self.assertTrue((artifact_dir / "workspace.json").is_file())

            repo = Path(temporary) / "commit-recovery"
            repo.mkdir()
            (repo / "README.md").write_text("baseline\n", encoding="utf-8")
            git(repo, "init", "-b", "main")
            git(repo, "add", "README.md")
            subprocess.run(
                [
                    "git",
                    "-c",
                    "user.name=Recovery Test",
                    "-c",
                    "user.email=recovery@localhost",
                    "commit",
                    "-m",
                    "baseline",
                ],
                cwd=repo,
                text=True,
                capture_output=True,
                check=True,
            )
            (repo / "change.md").write_text("bounded change\n", encoding="utf-8")
            commit_artifacts = Path(temporary) / "commit-artifacts"
            commit_artifacts.mkdir()
            item = SimpleNamespace(id="work-recovery", title="Recover commit")
            base_commit = git(repo, "rev-parse", "HEAD")
            first_commit = _commit_implementation(
                repo, commit_artifacts, item, base_commit
            )
            (commit_artifacts / "implementation.json").unlink()
            recovered_commit = _commit_implementation(
                repo, commit_artifacts, item, base_commit
            )
            self.assertEqual(recovered_commit, first_commit)

    def test_runner_profile_is_digest_bound_before_human_approval(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            demo = Path(temporary) / "demo"
            first = create_reference_demo(demo)
            profile_path = demo / "runner-profile.json"
            profile = json.loads(profile_path.read_text(encoding="utf-8"))
            profile["commands"][0]["argv"] = ["python3", "--version"]
            profile_path.write_text(json.dumps(profile), encoding="utf-8")
            with self.assertRaisesRegex(TeamRuntimeError, "runner profile changed"):
                run_team(
                    demo / "team",
                    first["work_item_id"],
                    demo / "project",
                    profile_path,
                    model_mode="reference",
                    provider="local",
                )

    def test_multi_project_team_requires_explicit_project_selection(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            document = json.loads(
                (ROOT / "examples/team-blueprint/input/team.json").read_text(
                    encoding="utf-8"
                )
            )
            document["instance"]["projects"].append(
                {
                    "id": "project.second-product",
                    "provider": "generic-git",
                    "locator": "local/second-product",
                    "default_branch": "main",
                    "mode": "proposal-only",
                }
            )
            blueprint_path = base / "blueprint.json"
            blueprint_path.write_text(json.dumps(document), encoding="utf-8")
            team = base / "team"
            create_team(blueprint_path, team)
            with self.assertRaisesRegex(TeamRuntimeError, "--project-id"):
                run_team(
                    team,
                    "work-does-not-exist",
                    base / "missing-project",
                    base / "missing-profile.json",
                )

    def test_reference_demo_enforces_human_gate_then_reaches_reviewed_draft_pr(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            demo = Path(temporary) / "demo"
            first = create_reference_demo(demo)
            self.assertEqual(first["status"], "WAITING_FOR_HUMAN")
            self.assertEqual(first["work_item"]["state"], "SPEC_READY")
            self.assertIsNone(first["work_item"]["plan_approved_by"])
            self.assertFalse((demo / "project/agent-team-reference-change.md").exists())
            self.assertFalse((demo / "team/runtime/workspaces").exists())

            work_id = first["work_item_id"]
            scope_hash = first["specification"]["scope_hash"]
            with self.assertRaisesRegex(TeamRuntimeError, "scope hash"):
                approve_team_plan(demo / "team", work_id, "sha256:" + ("0" * 64))

            approved = approve_team_plan(demo / "team", work_id, scope_hash)
            self.assertEqual(approved["status"], "PLAN_APPROVED")
            self.assertEqual(approved["work_item"]["plan_approved_by"], "human.project-owner")

            completed = run_team(
                demo / "team",
                work_id,
                demo / "project",
                demo / "runner-profile.json",
                model_mode="reference",
                provider="local",
                allow_host_runner=True,
            )
            self.assertEqual(completed["status"], "DRAFT_PR_READY")
            self.assertEqual(completed["work_item"]["state"], "REVIEW_APPROVED")
            self.assertTrue(completed["pull_request"]["draft"])
            self.assertTrue(completed["pull_request"]["external_ref"].startswith("local-draft-pr:"))
            self.assertEqual(completed["runner_evidence"]["result"], "PASSED")
            self.assertEqual(git(demo / "project", "branch", "--show-current"), "main")
            self.assertFalse((demo / "project/agent-team-reference-change.md").exists())

            item = completed["work_item"]
            review = next(event for event in item["audit"] if event["action"] == "approve_review")
            self.assertNotEqual(item["author_id"], review["actor_id"])
            self.assertNotIn("deploy", {event["action"] for event in item["audit"]})

            replay = run_team(
                demo / "team",
                work_id,
                demo / "project",
                demo / "runner-profile.json",
                model_mode="reference",
                provider="local",
                allow_host_runner=True,
            )
            self.assertEqual(replay["status"], "DRAFT_PR_READY")
            self.assertEqual(replay["audit"]["events"], completed["audit"]["events"])

            artifact = (
                demo
                / "team/runtime/artifacts"
                / work_id
                / "runner-evidence.json"
            )
            tampered = json.loads(artifact.read_text(encoding="utf-8"))
            tampered["commands"][0]["stdout"] = "tampered after review"
            artifact.write_text(json.dumps(tampered), encoding="utf-8")
            with self.assertRaisesRegex(TeamRuntimeError, "evidence digest"):
                run_team(
                    demo / "team",
                    work_id,
                    demo / "project",
                    demo / "runner-profile.json",
                    model_mode="reference",
                    provider="local",
                    allow_host_runner=True,
                )
            rebound = dict(tampered)
            rebound.pop("evidence_digest", None)
            encoded = json.dumps(
                rebound,
                allow_nan=False,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            tampered["evidence_digest"] = "sha256:" + hashlib.sha256(encoded).hexdigest()
            artifact.write_text(json.dumps(tampered), encoding="utf-8")
            with self.assertRaisesRegex(TeamRuntimeError, "durable CI audit"):
                run_team(
                    demo / "team",
                    work_id,
                    demo / "project",
                    demo / "runner-profile.json",
                    model_mode="reference",
                    provider="local",
                    allow_host_runner=True,
                )

    def test_missing_runner_consent_stops_at_open_draft_pr(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            demo = Path(temporary) / "demo"
            first = create_reference_demo(demo)
            work_id = first["work_item_id"]
            approve_team_plan(demo / "team", work_id, first["specification"]["scope_hash"])
            report = run_team(
                demo / "team",
                work_id,
                demo / "project",
                demo / "runner-profile.json",
                model_mode="reference",
                provider="local",
                allow_host_runner=False,
            )
            self.assertEqual(report["work_item"]["state"], "PR_OPEN")
            self.assertEqual(report["status"], "WAITING_FOR_RUNNER")
            self.assertTrue(report["pull_request"]["draft"])

    def test_failed_test_command_cannot_record_ci_pass(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            workspace = base / "workspace"
            workspace.mkdir()
            (workspace / "README.md").write_text("baseline\n", encoding="utf-8")
            git(workspace, "init", "-b", "main")
            git(workspace, "add", "README.md")
            subprocess.run(
                [
                    "git",
                    "-c",
                    "user.name=Runner Test",
                    "-c",
                    "user.email=runner@localhost",
                    "commit",
                    "-m",
                    "baseline",
                ],
                cwd=workspace,
                text=True,
                capture_output=True,
                check=True,
            )
            commit = git(workspace, "rev-parse", "HEAD")
            profile = {
                "schema_version": "1.0.0",
                "project_id": "project.example",
                "working_directory": ".",
                "commands": [
                    {
                        "id": "intentional-failure",
                        "argv": ["python3", "-c", "raise SystemExit(7)"],
                        "timeout_seconds": 30,
                    }
                ],
            }
            artifact_dir = base / "artifacts"
            with self.assertRaisesRegex(TeamRuntimeError, "test commands failed"):
                _run_profile(
                    profile,
                    workspace=workspace,
                    artifact_dir=artifact_dir,
                    work_item_id="work-runner-failure",
                    commit=commit,
                    allow_host_runner=True,
                )
            evidence = json.loads(
                (artifact_dir / "runner-evidence.json").read_text(encoding="utf-8")
            )
            self.assertEqual(evidence["result"], "FAILED")

    def test_passing_runner_evidence_is_reused_after_restart(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            workspace = base / "workspace"
            workspace.mkdir()
            (workspace / "README.md").write_text("baseline\n", encoding="utf-8")
            git(workspace, "init", "-b", "main")
            git(workspace, "add", "README.md")
            subprocess.run(
                [
                    "git",
                    "-c",
                    "user.name=Runner Test",
                    "-c",
                    "user.email=runner@localhost",
                    "commit",
                    "-m",
                    "baseline",
                ],
                cwd=workspace,
                text=True,
                capture_output=True,
                check=True,
            )
            commit = git(workspace, "rev-parse", "HEAD")
            marker = base / "outside-runner-marker"
            script = (
                "from pathlib import Path; import sys; p=Path(sys.argv[1]); "
                "sys.exit(9) if p.exists() else p.write_text('once', encoding='utf-8')"
            )
            profile = {
                "schema_version": "1.0.0",
                "project_id": "project.example",
                "working_directory": ".",
                "commands": [
                    {
                        "id": "one-shot",
                        "argv": ["python3", "-c", script, str(marker)],
                        "timeout_seconds": 30,
                    }
                ],
            }
            artifact_dir = base / "artifacts"
            first = _run_profile(
                profile,
                workspace=workspace,
                artifact_dir=artifact_dir,
                work_item_id="work-runner-replay",
                commit=commit,
                allow_host_runner=True,
            )
            second = _run_profile(
                profile,
                workspace=workspace,
                artifact_dir=artifact_dir,
                work_item_id="work-runner-replay",
                commit=commit,
                allow_host_runner=True,
            )
            self.assertEqual(second, first)
            self.assertEqual(marker.read_text(encoding="utf-8"), "once")


class RunnerProfileTests(unittest.TestCase):
    def test_profile_rejects_traversal_duplicate_ids_and_inline_credentials(self) -> None:
        profile = {
            "schema_version": "1.0.0",
            "project_id": "project.example",
            "working_directory": "../outside",
            "commands": [{"id": "test", "argv": ["python3"], "timeout_seconds": 1}],
        }
        with self.assertRaisesRegex(TeamRuntimeError, "within the worktree"):
            validate_runner_profile(profile)

        profile["working_directory"] = "."
        profile["commands"].append(dict(profile["commands"][0]))
        with self.assertRaisesRegex(TeamRuntimeError, "unique"):
            validate_runner_profile(profile)

        profile["commands"] = [
            {
                "id": "test",
                "argv": ["ghp_" + ("A" * 24)],
                "timeout_seconds": 1,
            }
        ]
        with self.assertRaisesRegex(TeamRuntimeError, "credential"):
            validate_runner_profile(profile)


if __name__ == "__main__":
    unittest.main()
