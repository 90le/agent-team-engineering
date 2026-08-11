from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from core.context_team import build_design, create_context_team
from core.host_lifecycle import (
    HostLifecycleError,
    apply_install_plan,
    build_install_plan,
    confirm_install_plan,
    load_install_plan,
    preview_install_plan,
    uninstall_installation,
    verify_installation,
    write_install_plan,
)
from core import host_lifecycle


class HostLifecycleTests(unittest.TestCase):
    def _team(self, base: Path, host: str = "codex") -> Path:
        base.mkdir(parents=True, exist_ok=True)
        design = build_design(
            "custom",
            team_name="Native Host Test Team",
            project_name="Native Host Test",
            repository="example/native-host-test",
            provider="github",
            default_branch="main",
            owner_name="Test Owner",
            platforms=[host],
            custom_roles=["builder:Builder", "reviewer:Reviewer"],
        )
        design_path = base / "design.json"
        design_path.write_text(json.dumps(design, indent=2) + "\n", encoding="utf-8")
        team = base / "team"
        create_context_team(design_path, team)
        return team

    def _descriptor(self, host: str) -> dict:
        from core.host_catalog import load_host_descriptor

        return load_host_descriptor(host)

    def test_plan_preview_confirmation_apply_verify_replay_and_uninstall(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            team = self._team(base)
            destination = base / "project"
            destination.mkdir()
            (destination / "user.txt").write_text("keep\n", encoding="utf-8")
            with mock.patch("core.host_lifecycle._host_descriptor", return_value=self._descriptor("codex")):
                plan = build_install_plan(team, "codex", destination)
            self.assertEqual(plan["state"], "DRAFT")
            self.assertFalse(plan["proposal"]["effects"]["external_writes"])
            preview = preview_install_plan(plan)
            self.assertIn("Confirm this exact digest", preview)
            self.assertIn("## Exact managed files", preview)
            self.assertIn("`.codex/config.toml`", preview)
            self.assertIn("External writes: `false`", preview)
            self.assertIn(plan["proposal"]["host"]["descriptor_digest"], preview)
            plan_path = base / "host-plan.json"
            write_install_plan(plan, plan_path)
            with self.assertRaisesRegex(HostLifecycleError, "confirm"):
                apply_install_plan(plan_path)
            confirm_install_plan(
                plan_path,
                digest=plan["proposal_digest"],
                approved_by="Test Owner",
            )
            report = apply_install_plan(plan_path)
            self.assertEqual(report["status"], "VALID")
            self.assertTrue((destination / ".codex/config.toml").is_file())
            self.assertTrue((destination / ".agent-team/context/AI-START.md").is_file())
            self.assertEqual(apply_install_plan(plan_path)["status"], "ALREADY_APPLIED")
            self.assertEqual(verify_installation(destination)["status"], "VALID")
            removed = uninstall_installation(destination, digest=plan["proposal_digest"])
            self.assertEqual(removed["status"], "UNINSTALLED")
            self.assertEqual((destination / "user.txt").read_text(encoding="utf-8"), "keep\n")
            self.assertFalse((destination / ".codex/config.toml").exists())

    def test_tampering_conflicts_symlinks_and_drift_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            team = self._team(base)
            destination = base / "destination"
            with mock.patch("core.host_lifecycle._host_descriptor", return_value=self._descriptor("codex")):
                plan = build_install_plan(team, "codex", destination)
            plan_path = base / "plan.json"
            write_install_plan(plan, plan_path)
            with self.assertRaisesRegex(HostLifecycleError, "does not match"):
                confirm_install_plan(
                    plan_path,
                    digest="sha256:" + ("0" * 64),
                    approved_by="Owner",
                )
            confirm_install_plan(
                plan_path,
                digest=plan["proposal_digest"],
                approved_by="Owner",
            )
            (team / "AI-START.md").write_text("drift\n", encoding="utf-8")
            with self.assertRaisesRegex(HostLifecycleError, "team|source"):
                apply_install_plan(plan_path)

            second_team = self._team(base / "second")
            conflict = base / "conflict"
            (conflict / ".codex").mkdir(parents=True)
            (conflict / ".codex/config.toml").write_text("user owned\n", encoding="utf-8")
            with mock.patch("core.host_lifecycle._host_descriptor", return_value=self._descriptor("codex")):
                second = build_install_plan(second_team, "codex", conflict)
            second_path = base / "second-plan.json"
            write_install_plan(second, second_path)
            confirm_install_plan(second_path, digest=second["proposal_digest"], approved_by="Owner")
            with self.assertRaisesRegex(HostLifecycleError, "never overwrites"):
                apply_install_plan(second_path)

    def test_plan_digest_detects_edits_and_unknown_target_stops(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            team = self._team(base)
            with mock.patch("core.host_lifecycle._host_descriptor", return_value=self._descriptor("codex")):
                plan = build_install_plan(team, "codex", base / "destination")
            plan_path = base / "plan.json"
            write_install_plan(plan, plan_path)
            document = json.loads(plan_path.read_text(encoding="utf-8"))
            document["proposal"]["destination"] = str(base / "changed")
            plan_path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(HostLifecycleError, "digest"):
                load_install_plan(plan_path)
            with self.assertRaisesRegex(HostLifecycleError, "not compiled"):
                build_install_plan(team, "hermes", base / "other")

    def test_host_descriptor_drift_invalidates_the_plan(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            team = self._team(base)
            plan = build_install_plan(team, "codex", base / "destination")
            changed = self._descriptor("codex")
            changed["description"] = changed["description"] + " changed"
            with mock.patch("core.host_lifecycle._host_descriptor", return_value=changed):
                with self.assertRaisesRegex(HostLifecycleError, "descriptor changed"):
                    preview_install_plan(plan)

    def test_managed_team_can_plan_hermes_and_multica_host_packages(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            for host in ("hermes", "multica"):
                design = build_design(
                    "software-managed",
                    team_name=f"Managed {host} Team",
                    project_name="Managed Host Test",
                    repository="example/managed-host-test",
                    provider="github",
                    default_branch="main",
                    owner_name="Test Owner",
                    platforms=[host],
                )
                design_path = base / f"{host}-design.json"
                design_path.write_text(json.dumps(design, indent=2) + "\n", encoding="utf-8")
                team = base / f"{host}-team"
                create_context_team(design_path, team)
                plan = build_install_plan(team, host, base / f"{host}-destination")
                self.assertEqual(plan["proposal"]["host"]["id"], host)
                self.assertTrue(
                    any(
                        record["source"].startswith(f"platforms/{host}/")
                        for record in plan["proposal"]["files"]
                    )
                )

    def test_interrupted_apply_resumes_only_the_same_exact_plan(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            team = self._team(base)
            destination = base / "destination"
            with mock.patch(
                "core.host_lifecycle._host_descriptor",
                return_value=self._descriptor("codex"),
            ):
                plan = build_install_plan(team, "codex", destination)
            plan_path = base / "plan.json"
            write_install_plan(plan, plan_path)
            confirm_install_plan(
                plan_path,
                digest=plan["proposal_digest"],
                approved_by="Owner",
            )
            original = host_lifecycle._copy_exclusive
            calls = 0

            def fail_after_one(source: Path, target: Path) -> None:
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise OSError("simulated interruption")
                original(source, target)

            with mock.patch("core.host_lifecycle._copy_exclusive", side_effect=fail_after_one):
                with self.assertRaisesRegex(OSError, "simulated"):
                    apply_install_plan(plan_path)
            lock = json.loads(
                (destination / ".agent-team/host-install.lock.json").read_text(encoding="utf-8")
            )
            self.assertEqual(lock["status"], "APPLYING")
            resumed = apply_install_plan(plan_path)
            self.assertEqual(resumed["status"], "VALID")


if __name__ == "__main__":
    unittest.main()
