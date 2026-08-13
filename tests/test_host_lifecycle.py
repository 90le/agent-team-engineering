from __future__ import annotations

import json
import os
import stat
import tempfile
import threading
import unittest
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
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
    preview_uninstall,
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

    def _assert_fifo_is_rejected_without_blocking(
        self,
        fifo: Path,
        action: Callable[[], object],
        message: str,
    ) -> None:
        original_open = host_lifecycle.os.open
        observed_nonblocking_open = False

        def checked_open(path: object, flags: int, *args: object, **kwargs: object) -> int:
            nonlocal observed_nonblocking_open
            if str(path) in {str(fifo), fifo.name}:
                observed_nonblocking_open = True
                self.assertTrue(
                    flags & getattr(host_lifecycle.os, "O_NONBLOCK", 0),
                    f"FIFO was opened without O_NONBLOCK: {fifo}",
                )
            return original_open(path, flags, *args, **kwargs)

        with mock.patch("core.host_lifecycle.os.open", side_effect=checked_open):
            with self.assertRaisesRegex(HostLifecycleError, message):
                action()
        self.assertTrue(observed_nonblocking_open)
        self.assertTrue(stat.S_ISFIFO(fifo.lstat().st_mode))

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
            self.assertEqual(plan["schema_version"], "1.1.0")
            self.assertFalse(plan["proposal"]["effects"]["external_writes"])
            preview = preview_install_plan(plan)
            self.assertIn("Confirm this exact digest", preview)
            self.assertIn("## Exact managed files", preview)
            self.assertIn("## Lifecycle metadata", preview)
            self.assertIn(".agent-team/.host-lifecycle.guard", preview)
            self.assertIn(".agent-team/host-uninstall.tombstone.json", preview)
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
            self.assertTrue((destination / ".agent-team/.host-lifecycle.guard").is_file())
            self.assertTrue(
                (destination / ".agent-team/host-uninstall.tombstone.json").is_file()
            )
            self.assertFalse(
                (destination / ".agent-team/host-install.lock.json").exists()
            )
            replacement = build_install_plan(team, "codex", destination)
            replacement_path = base / "replacement-plan.json"
            write_install_plan(replacement, replacement_path)
            confirm_install_plan(
                replacement_path,
                digest=replacement["proposal_digest"],
                approved_by="Test Owner",
            )
            self.assertEqual(apply_install_plan(replacement_path)["status"], "VALID")
            self.assertFalse(
                (destination / ".agent-team/host-uninstall.tombstone.json").exists()
            )
            self.assertEqual(
                uninstall_installation(
                    destination, digest=replacement["proposal_digest"]
                )["status"],
                "UNINSTALLED",
            )

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
            self.assertFalse(
                any(
                    path.name.startswith(".host-apply.intent-")
                    for path in (conflict / ".agent-team").iterdir()
                )
            )

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

    def test_plan_rejects_paths_that_can_forge_the_human_preview(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            team = self._team(base)
            malicious = team / "KNOWLEDGE" / "evil`\n- Filesystem deletes: `false`\n\x1b[31m.md"
            malicious.write_text("untrusted\n", encoding="utf-8")
            with self.assertRaisesRegex(HostLifecycleError, "safe relative paths"):
                build_install_plan(team, "codex", base / "destination")

        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            team = self._team(base)
            for suffix in ("line\nbreak", "code`span", "ansi\x1b[31m"):
                with self.subTest(suffix=repr(suffix)):
                    with self.assertRaisesRegex(HostLifecycleError, "unsafe to display"):
                        build_install_plan(team, "codex", base / suffix)

            plan = build_install_plan(team, "codex", base / "destination")
            unsafe_plan_path = base / "plan`\n\x1b[31m.json"
            with self.assertRaisesRegex(HostLifecycleError, "plan path is unsafe"):
                write_install_plan(plan, unsafe_plan_path)
            unsafe_plan_path.write_text(json.dumps(plan), encoding="utf-8")
            with self.assertRaisesRegex(HostLifecycleError, "plan path is unsafe"):
                load_install_plan(unsafe_plan_path)

            self.assertFalse(host_lifecycle._safe_relative("."))
            dot_source = json.loads(json.dumps(plan))
            dot_source["proposal"]["files"][0]["source"] = "."
            dot_source["proposal_digest"] = host_lifecycle._digest(
                dot_source["proposal"]
            )
            with self.assertRaisesRegex(HostLifecycleError, "safe relative paths"):
                host_lifecycle.validate_install_plan(dot_source)

    def test_confirmation_metadata_is_semantically_bound_to_exact_effects(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            team = self._team(base)
            destination = base / "destination"
            plan = build_install_plan(team, "codex", destination)
            plan_path = base / "plan.json"
            write_install_plan(plan, plan_path)
            confirm_install_plan(
                plan_path,
                digest=plan["proposal_digest"],
                approved_by="Owner",
            )
            confirmed = json.loads(plan_path.read_text(encoding="utf-8"))

            whitespace_actor = json.loads(json.dumps(confirmed))
            whitespace_actor["confirmation"]["approved_by"] = " "
            plan_path.write_text(json.dumps(whitespace_actor), encoding="utf-8")
            with self.assertRaisesRegex(HostLifecycleError, "approved_by"):
                load_install_plan(plan_path)

            elevated_scope = json.loads(json.dumps(confirmed))
            elevated_scope["confirmation"]["scope"] = (
                "replace-exact-prior-tombstone-and-manage-declared-host-lifecycle-and-scratch-files"
            )
            plan_path.write_text(json.dumps(elevated_scope), encoding="utf-8")
            with self.assertRaisesRegex(HostLifecycleError, "scope differs"):
                load_install_plan(plan_path)

            plan_path.write_text(json.dumps(confirmed), encoding="utf-8")
            self.assertEqual(apply_install_plan(plan_path)["status"], "VALID")
            uninstall_installation(destination, digest=plan["proposal_digest"])
            tombstone = destination / ".agent-team/host-uninstall.tombstone.json"
            tombstone_bytes = tombstone.read_bytes()

            replacement = build_install_plan(team, "codex", destination)
            replacement_path = base / "replacement.json"
            write_install_plan(replacement, replacement_path)
            confirm_install_plan(
                replacement_path,
                digest=replacement["proposal_digest"],
                approved_by="Owner",
            )
            lowered = json.loads(replacement_path.read_text(encoding="utf-8"))
            lowered["confirmation"]["scope"] = (
                "manage-declared-host-lifecycle-and-scratch-files"
            )
            replacement_path.write_text(json.dumps(lowered), encoding="utf-8")
            with self.assertRaisesRegex(HostLifecycleError, "scope differs"):
                apply_install_plan(replacement_path)
            self.assertEqual(tombstone.read_bytes(), tombstone_bytes)

    def test_plan_symlink_and_destination_ancestor_symlink_fail_before_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            team = self._team(base)
            parent = base / "approved-parent"
            parent.mkdir()
            destination = parent / "child"
            plan = build_install_plan(team, "codex", destination)
            plan_path = base / "plan.json"
            write_install_plan(plan, plan_path)
            original = plan_path.read_bytes()
            alias = base / "plan-alias.json"
            alias.symlink_to(plan_path)
            for operation in (
                lambda: load_install_plan(alias),
                lambda: confirm_install_plan(
                    alias,
                    digest=plan["proposal_digest"],
                    approved_by="Owner",
                ),
                lambda: apply_install_plan(alias),
            ):
                with self.assertRaisesRegex(HostLifecycleError, "symbolic link"):
                    operation()
                self.assertEqual(plan_path.read_bytes(), original)

            confirm_install_plan(
                plan_path,
                digest=plan["proposal_digest"],
                approved_by="Owner",
            )
            moved_parent = base / "approved-parent-original"
            redirected = base / "redirected"
            redirected.mkdir()
            parent.rename(moved_parent)
            parent.symlink_to(redirected, target_is_directory=True)
            with self.assertRaisesRegex(HostLifecycleError, "changed or became unsafe"):
                apply_install_plan(plan_path)
            self.assertFalse((redirected / "child").exists())
            self.assertFalse(
                (redirected / "child/.agent-team/.host-lifecycle.guard").exists()
            )

            loop_parent = base / "loop-parent"
            loop_parent.mkdir()
            loop_destination = loop_parent / "child"
            loop_plan = build_install_plan(team, "codex", loop_destination)
            loop_plan_path = base / "loop-plan.json"
            write_install_plan(loop_plan, loop_plan_path)
            confirm_install_plan(
                loop_plan_path,
                digest=loop_plan["proposal_digest"],
                approved_by="Owner",
            )
            loop_parent.rmdir()
            loop_parent.symlink_to(loop_parent.name, target_is_directory=True)
            with self.assertRaisesRegex(
                HostLifecycleError, "changed or became unsafe"
            ):
                apply_install_plan(loop_plan_path)
            self.assertFalse((base / "loop-parent-original").exists())

    def test_fifo_inputs_fail_closed_without_blocking_or_deletion(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            team = self._team(base)
            plan = build_install_plan(team, "codex", base / "destination")
            plan_fifo = base / "plan-fifo.json"
            os.mkfifo(plan_fifo)
            self._assert_fifo_is_rejected_without_blocking(
                plan_fifo,
                lambda: load_install_plan(plan_fifo),
                "plan.*regular file",
            )

        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            team = self._team(base)
            destination = base / "destination"
            plan = build_install_plan(team, "codex", destination)
            plan_path = base / "plan.json"
            write_install_plan(plan, plan_path)
            confirm_install_plan(
                plan_path,
                digest=plan["proposal_digest"],
                approved_by="Owner",
            )
            metadata_fifo = destination / ".agent-team/.host-lifecycle.json.stage"
            metadata_fifo.parent.mkdir(parents=True)
            os.mkfifo(metadata_fifo)
            with self.assertRaisesRegex(
                HostLifecycleError,
                "metadata recovery stage changed after planning",
            ):
                apply_install_plan(plan_path)
            self.assertTrue(stat.S_ISFIFO(metadata_fifo.lstat().st_mode))
            self.assertFalse(
                (destination / ".agent-team/host-install.lock.json").exists()
            )

        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            destination = base / "destination"
            install_lock_fifo = destination / ".agent-team/host-install.lock.json"
            install_lock_fifo.parent.mkdir(parents=True)
            os.mkfifo(install_lock_fifo)
            self._assert_fifo_is_rejected_without_blocking(
                install_lock_fifo,
                lambda: verify_installation(destination),
                "installation lock.*regular file",
            )

        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            team = self._team(base)
            destination = base / "destination"
            plan = build_install_plan(team, "codex", destination)
            plan_path = base / "plan.json"
            write_install_plan(plan, plan_path)
            confirm_install_plan(
                plan_path,
                digest=plan["proposal_digest"],
                approved_by="Owner",
            )
            apply_install_plan(plan_path)
            first = plan["proposal"]["files"][0]
            managed_fifo = destination / first["path"]
            managed_fifo.unlink()
            os.mkfifo(managed_fifo)
            self._assert_fifo_is_rejected_without_blocking(
                managed_fifo,
                lambda: verify_installation(destination),
                "managed host file.*regular file",
            )
            self.assertTrue(
                (destination / ".agent-team/host-install.lock.json").is_file()
            )

            # Simulate a crash immediately after ACTIVE -> UNINSTALLING.  This
            # reaches the unlink helper directly on retry, so its independent
            # no-follow/non-blocking read and preservation guarantee are
            # covered rather than relying only on verification's reader.
            install_lock = destination / ".agent-team/host-install.lock.json"
            lock = json.loads(install_lock.read_text(encoding="utf-8"))
            lock["status"] = "UNINSTALLING"
            install_lock.write_text(
                json.dumps(lock, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            self._assert_fifo_is_rejected_without_blocking(
                managed_fifo,
                lambda: uninstall_installation(
                    destination,
                    digest=plan["proposal_digest"],
                ),
                "managed host file.*(unsafe|identity differs)",
            )
            self.assertTrue(install_lock.is_file())

    def test_preexisting_lifecycle_scratch_is_never_adopted_or_deleted(self) -> None:
        for kind in ("metadata-stage", "apply-intent"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as temporary:
                base = Path(temporary)
                team = self._team(base)
                destination = base / "destination"
                plan = build_install_plan(team, "codex", destination)
                plan_path = base / "plan.json"
                write_install_plan(plan, plan_path)
                confirm_install_plan(
                    plan_path,
                    digest=plan["proposal_digest"],
                    approved_by="Owner",
                )
                if kind == "metadata-stage":
                    collision = destination / ".agent-team/.host-lifecycle.json.stage"
                else:
                    collision = destination / plan["proposal"]["lifecycle"][
                        "initial_apply_intent"
                    ]
                collision.parent.mkdir(parents=True, exist_ok=True)
                collision.write_bytes(
                    b"user owned\n" if kind == "metadata-stage" else b""
                )
                with self.assertRaisesRegex(
                    HostLifecycleError,
                    "metadata recovery stage changed|apply intent (changed|appeared without a durable APPLYING record)",
                ):
                    apply_install_plan(plan_path)
                self.assertEqual(
                    collision.read_bytes(),
                    b"user owned\n" if kind == "metadata-stage" else b"",
                )
                self.assertFalse(
                    (destination / ".agent-team/host-install.lock.json").exists()
                )
                with self.assertRaisesRegex(
                    HostLifecycleError,
                    "reserved metadata recovery stage|reserved initial apply intent",
                ):
                    build_install_plan(team, "codex", destination)

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

            def fail_after_one(
                source_root: Path,
                source_relative: str,
                destination_root: Path,
                target_relative: str,
                stage_relative: str,
                intent_relative: str,
                expected_digest: str,
                *,
                resuming: bool,
            ) -> None:
                nonlocal calls
                calls += 1
                if calls == 1:
                    raise OSError("simulated interruption")
                original(
                    source_root,
                    source_relative,
                    destination_root,
                    target_relative,
                    stage_relative,
                    intent_relative,
                    expected_digest,
                    resuming=resuming,
                )

            with mock.patch("core.host_lifecycle._copy_exclusive", side_effect=fail_after_one):
                with self.assertRaisesRegex(OSError, "simulated"):
                    apply_install_plan(plan_path)
            lock = json.loads(
                (destination / ".agent-team/host-install.lock.json").read_text(encoding="utf-8")
            )
            self.assertEqual(lock["status"], "APPLYING")
            resumed = apply_install_plan(plan_path)
            self.assertEqual(resumed["status"], "VALID")

    def test_apply_resumes_after_target_publish_before_active_lock(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            team = self._team(base)
            destination = base / "destination"
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

            def stop_after_first_publish(*args: object, **kwargs: object) -> None:
                nonlocal calls
                original(*args, **kwargs)
                calls += 1
                if calls == 1:
                    raise OSError("simulated exit after target publication")

            with mock.patch(
                "core.host_lifecycle._copy_exclusive",
                side_effect=stop_after_first_publish,
            ):
                with self.assertRaisesRegex(OSError, "after target publication"):
                    apply_install_plan(plan_path)

            first = plan["proposal"]["files"][0]
            target = destination / first["path"]
            intent = destination / first["intent_path"]
            stage = destination / first["stage_path"]
            self.assertTrue(target.is_file())
            self.assertTrue(intent.is_file())
            self.assertEqual((target.stat().st_dev, target.stat().st_ino), (intent.stat().st_dev, intent.stat().st_ino))
            self.assertFalse(stage.exists() or stage.is_symlink())

            self.assertEqual(apply_install_plan(plan_path)["status"], "VALID")
            self.assertFalse(intent.exists() or intent.is_symlink())
            self.assertEqual(verify_installation(destination)["status"], "VALID")

    def test_resuming_apply_never_adopts_unbound_byte_identical_entries(self) -> None:
        for collision_kind in ("target", "stage", "target-and-stage"):
            with self.subTest(collision_kind=collision_kind), tempfile.TemporaryDirectory() as temporary:
                base = Path(temporary)
                team = self._team(base)
                destination = base / "destination"
                plan = build_install_plan(team, "codex", destination)
                plan_path = base / "plan.json"
                write_install_plan(plan, plan_path)
                confirm_install_plan(
                    plan_path,
                    digest=plan["proposal_digest"],
                    approved_by="Owner",
                )
                with mock.patch(
                    "core.host_lifecycle._copy_exclusive",
                    side_effect=OSError("stop before first intent"),
                ):
                    with self.assertRaisesRegex(OSError, "before first intent"):
                        apply_install_plan(plan_path)

                first = plan["proposal"]["files"][0]
                content = (team / first["source"]).read_bytes()
                paths: list[Path] = []
                if collision_kind in {"target", "target-and-stage"}:
                    paths.append(destination / first["path"])
                if collision_kind in {"stage", "target-and-stage"}:
                    paths.append(destination / first["stage_path"])
                for collision in paths:
                    collision.parent.mkdir(parents=True, exist_ok=True)
                    collision.write_bytes(content)
                snapshots = [(path, path.stat().st_ino, path.read_bytes()) for path in paths]

                with self.assertRaisesRegex(
                    HostLifecycleError,
                    "lacks its operation-bound intent",
                ):
                    apply_install_plan(plan_path)
                for collision, inode, expected in snapshots:
                    self.assertEqual(collision.stat().st_ino, inode)
                    self.assertEqual(collision.read_bytes(), expected)
                self.assertFalse(
                    (destination / first["intent_path"]).exists()
                    or (destination / first["intent_path"]).is_symlink()
                )

    def test_concurrent_different_plans_are_serialized_without_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            first_team = self._team(base / "first")
            second_team = self._team(base / "second")
            destination = base / "destination"
            first_path = base / "first-plan.json"
            second_path = base / "second-plan.json"
            for team, plan_path in (
                (first_team, first_path),
                (second_team, second_path),
            ):
                plan = build_install_plan(team, "codex", destination)
                write_install_plan(plan, plan_path)
                confirm_install_plan(
                    plan_path,
                    digest=plan["proposal_digest"],
                    approved_by="Owner",
                )

            entered = threading.Event()
            release = threading.Event()
            original = host_lifecycle._copy_exclusive
            calls = 0

            def block_first_copy(*args: object, **kwargs: object) -> None:
                nonlocal calls
                calls += 1
                if calls == 1:
                    entered.set()
                    self.assertTrue(release.wait(timeout=5))
                original(*args, **kwargs)

            with mock.patch(
                "core.host_lifecycle._copy_exclusive",
                side_effect=block_first_copy,
            ):
                with ThreadPoolExecutor(max_workers=2) as executor:
                    first = executor.submit(apply_install_plan, first_path)
                    self.assertTrue(entered.wait(timeout=5))
                    with self.assertRaisesRegex(HostLifecycleError, "already running"):
                        apply_install_plan(second_path)
                    with self.assertRaisesRegex(HostLifecycleError, "already running"):
                        verify_installation(destination)
                    release.set()
                    self.assertEqual(first.result(timeout=10)["status"], "VALID")

            lock = json.loads(
                (destination / ".agent-team/host-install.lock.json").read_text(
                    encoding="utf-8"
                )
            )
            first_plan = load_install_plan(first_path)
            self.assertEqual(lock["proposal_digest"], first_plan["proposal_digest"])

    def test_source_is_rechecked_after_initial_validation_before_publish(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            team = self._team(base)
            destination = base / "destination"
            plan = build_install_plan(team, "codex", destination)
            plan_path = base / "plan.json"
            write_install_plan(plan, plan_path)
            confirm_install_plan(
                plan_path,
                digest=plan["proposal_digest"],
                approved_by="Owner",
            )
            original = host_lifecycle._copy_exclusive
            mutated = False

            def mutate_then_copy(
                source_root: Path,
                source_relative: str,
                destination_root: Path,
                target_relative: str,
                stage_relative: str,
                intent_relative: str,
                expected_digest: str,
                *,
                resuming: bool,
            ) -> None:
                nonlocal mutated
                if not mutated:
                    mutated = True
                    (source_root / source_relative).write_text("late drift\n", encoding="utf-8")
                original(
                    source_root,
                    source_relative,
                    destination_root,
                    target_relative,
                    stage_relative,
                    intent_relative,
                    expected_digest,
                    resuming=resuming,
                )

            with mock.patch(
                "core.host_lifecycle._copy_exclusive",
                side_effect=mutate_then_copy,
            ):
                with self.assertRaisesRegex(HostLifecycleError, "planned source changed"):
                    apply_install_plan(plan_path)
            lock = json.loads(
                (destination / ".agent-team/host-install.lock.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(lock["status"], "APPLYING")

    def test_uninstall_rechecks_drift_and_resumes_after_interruption(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            team = self._team(base)
            destination = base / "destination"
            plan = build_install_plan(team, "codex", destination)
            plan_path = base / "plan.json"
            write_install_plan(plan, plan_path)
            confirm_install_plan(
                plan_path,
                digest=plan["proposal_digest"],
                approved_by="Owner",
            )
            apply_install_plan(plan_path)

            original = host_lifecycle._unlink_bound_relative
            calls = 0

            def interrupt_after_one(*args: object, **kwargs: object) -> bool:
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise OSError("simulated uninstall interruption")
                return original(*args, **kwargs)

            with mock.patch(
                "core.host_lifecycle._unlink_bound_relative",
                side_effect=interrupt_after_one,
            ):
                with self.assertRaisesRegex(OSError, "simulated uninstall interruption"):
                    uninstall_installation(destination, digest=plan["proposal_digest"])
            lock = json.loads(
                (destination / ".agent-team/host-install.lock.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(lock["status"], "UNINSTALLING")

            resumed = uninstall_installation(destination, digest=plan["proposal_digest"])
            self.assertEqual(resumed["status"], "UNINSTALLED")
            replayed = uninstall_installation(destination, digest=plan["proposal_digest"])
            self.assertEqual(replayed["status"], "ALREADY_UNINSTALLED")

    def test_uninstall_recovers_torn_active_to_uninstalling_metadata_stage(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            team = self._team(base)
            destination = base / "destination"
            plan = build_install_plan(team, "codex", destination)
            plan_path = base / "plan.json"
            write_install_plan(plan, plan_path)
            confirm_install_plan(
                plan_path,
                digest=plan["proposal_digest"],
                approved_by="Owner",
            )
            apply_install_plan(plan_path)
            unrelated = destination / ".agent-team/.host-lifecycle.json.stage-like"
            unrelated.write_text("user owned\n", encoding="utf-8")

            original_write = host_lifecycle.os.write
            interrupted = False

            def partial_write(descriptor: int, content: bytes) -> int:
                nonlocal interrupted
                if not interrupted:
                    interrupted = True
                    original_write(descriptor, content[: max(1, len(content) // 2)])
                    raise OSError("simulated ACTIVE to UNINSTALLING power loss")
                return original_write(descriptor, content)

            with mock.patch("core.host_lifecycle.os.write", side_effect=partial_write):
                with self.assertRaisesRegex(OSError, "ACTIVE to UNINSTALLING"):
                    uninstall_installation(
                        destination,
                        digest=plan["proposal_digest"],
                    )

            lock = json.loads(
                (destination / ".agent-team/host-install.lock.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(lock["status"], "ACTIVE")
            metadata_stage = destination / ".agent-team/.host-lifecycle.json.stage"
            self.assertTrue(metadata_stage.is_file())
            with self.assertRaisesRegex(HostLifecycleError, "metadata recovery stage"):
                verify_installation(destination)
            self.assertEqual(preview_uninstall(destination)["status"], "ACTIVE")

            resumed = uninstall_installation(
                destination,
                digest=plan["proposal_digest"],
            )
            self.assertEqual(resumed["status"], "UNINSTALLED")
            self.assertFalse(metadata_stage.exists() or metadata_stage.is_symlink())
            self.assertEqual(unrelated.read_text(encoding="utf-8"), "user owned\n")
            self.assertEqual(
                uninstall_installation(destination, digest=plan["proposal_digest"])["status"],
                "ALREADY_UNINSTALLED",
            )

    def test_uninstall_tombstone_replay_cleans_declared_stage_and_refuses_symlink(self) -> None:
        for stage_kind in ("regular", "symlink"):
            with self.subTest(stage_kind=stage_kind), tempfile.TemporaryDirectory() as temporary:
                base = Path(temporary)
                team = self._team(base)
                destination = base / "destination"
                plan = build_install_plan(team, "codex", destination)
                plan_path = base / "plan.json"
                write_install_plan(plan, plan_path)
                confirm_install_plan(
                    plan_path,
                    digest=plan["proposal_digest"],
                    approved_by="Owner",
                )
                apply_install_plan(plan_path)

                original_unlink = host_lifecycle._unlink_bound_relative

                def stop_before_lock_removal(
                    root: object,
                    relative: str,
                    expected_digest: str,
                    *,
                    allow_missing: bool,
                    expected_binding: dict[str, object] | None = None,
                ) -> bool:
                    if relative == ".agent-team/host-install.lock.json":
                        raise OSError("simulated crash before install-lock removal")
                    return original_unlink(
                        root,
                        relative,
                        expected_digest,
                        allow_missing=allow_missing,
                        expected_binding=expected_binding,
                    )

                with mock.patch(
                    "core.host_lifecycle._unlink_bound_relative",
                    side_effect=stop_before_lock_removal,
                ):
                    with self.assertRaisesRegex(OSError, "install-lock removal"):
                        uninstall_installation(
                            destination,
                            digest=plan["proposal_digest"],
                        )
                lock = json.loads(
                    (destination / ".agent-team/host-install.lock.json").read_text(
                        encoding="utf-8"
                    )
                )
                self.assertEqual(lock["status"], "UNINSTALLING")
                self.assertTrue(
                    (destination / ".agent-team/host-uninstall.tombstone.json").is_file()
                )

                stage = destination / ".agent-team/.host-lifecycle.json.stage"
                protected = base / "protected.txt"
                protected.write_text("keep\n", encoding="utf-8")
                if stage_kind == "regular":
                    stage.write_text("torn scratch\n", encoding="utf-8")
                    with self.assertRaisesRegex(
                        HostLifecycleError,
                        "recovery stage is not operation-bound",
                    ):
                        uninstall_installation(
                            destination,
                            digest=plan["proposal_digest"],
                        )
                    self.assertEqual(stage.read_text(encoding="utf-8"), "torn scratch\n")
                else:
                    stage.symlink_to(protected)
                    with self.assertRaisesRegex(HostLifecycleError, "recovery stage"):
                        uninstall_installation(
                            destination,
                            digest=plan["proposal_digest"],
                        )
                    self.assertTrue(stage.is_symlink())
                    self.assertEqual(protected.read_text(encoding="utf-8"), "keep\n")

    def test_uninstall_detects_drift_between_verify_and_unlink(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            team = self._team(base)
            destination = base / "destination"
            plan = build_install_plan(team, "codex", destination)
            plan_path = base / "plan.json"
            write_install_plan(plan, plan_path)
            confirm_install_plan(
                plan_path,
                digest=plan["proposal_digest"],
                approved_by="Owner",
            )
            apply_install_plan(plan_path)
            first = plan["proposal"]["files"][0]
            original = host_lifecycle._unlink_bound_relative
            mutated = False

            def drift_then_unlink(
                root: object,
                relative: str,
                expected_digest: str,
                *,
                allow_missing: bool,
                expected_binding: dict[str, object] | None = None,
            ) -> bool:
                nonlocal mutated
                if not mutated and relative == first["path"]:
                    mutated = True
                    (destination / relative).write_text("late drift\n", encoding="utf-8")
                return original(
                    root,
                    relative,
                    expected_digest,
                    allow_missing=allow_missing,
                    expected_binding=expected_binding,
                )

            with mock.patch(
                "core.host_lifecycle._unlink_bound_relative",
                side_effect=drift_then_unlink,
            ):
                with self.assertRaisesRegex(HostLifecycleError, "drifted"):
                    uninstall_installation(destination, digest=plan["proposal_digest"])
            self.assertTrue((destination / first["path"]).exists())

    def test_uninstall_retry_preserves_byte_identical_recreated_user_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            team = self._team(base)
            destination = base / "destination"
            plan = build_install_plan(team, "codex", destination)
            plan_path = base / "plan.json"
            write_install_plan(plan, plan_path)
            confirm_install_plan(
                plan_path,
                digest=plan["proposal_digest"],
                approved_by="Owner",
            )
            apply_install_plan(plan_path)
            first = plan["proposal"]["files"][0]
            target = destination / first["path"]
            original_bytes = target.read_bytes()
            original_unlink = host_lifecycle._unlink_bound_relative
            interrupted = False

            def interrupt_after_first(
                root: object,
                relative: str,
                expected_digest: str,
                *,
                allow_missing: bool,
                expected_binding: dict[str, object] | None = None,
            ) -> bool:
                nonlocal interrupted
                removed = original_unlink(
                    root,
                    relative,
                    expected_digest,
                    allow_missing=allow_missing,
                    expected_binding=expected_binding,
                )
                if removed and not interrupted:
                    interrupted = True
                    raise OSError("simulated crash after managed unlink")
                return removed

            with mock.patch(
                "core.host_lifecycle._unlink_bound_relative",
                side_effect=interrupt_after_first,
            ), self.assertRaisesRegex(OSError, "managed unlink"):
                uninstall_installation(
                    destination,
                    digest=plan["proposal_digest"],
                )
            self.assertFalse(target.exists())
            target.write_bytes(original_bytes)
            result = uninstall_installation(
                destination,
                digest=plan["proposal_digest"],
            )
            self.assertEqual(result["status"], "UNINSTALLED")
            self.assertEqual(
                result["removed_in_this_run"],
                len(plan["proposal"]["files"]) - 1,
            )
            self.assertEqual(target.read_bytes(), original_bytes)

    def test_uninstalling_lock_rejects_planned_file_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            team = self._team(base)
            destination = base / "destination"
            plan = build_install_plan(team, "codex", destination)
            plan_path = base / "plan.json"
            write_install_plan(plan, plan_path)
            confirm_install_plan(
                plan_path,
                digest=plan["proposal_digest"],
                approved_by="Owner",
            )
            apply_install_plan(plan_path)
            lock_path = destination / ".agent-team/host-install.lock.json"
            lock = json.loads(lock_path.read_text(encoding="utf-8"))
            lock["status"] = "UNINSTALLING"
            lock["files"][0]["state"] = "PLANNED"
            lock_path.write_text(
                json.dumps(lock, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(HostLifecycleError, "invalid file state"):
                preview_uninstall(destination)

    def test_mutation_refuses_when_posix_locking_is_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            team = self._team(base)
            destination = base / "destination"
            plan = build_install_plan(team, "codex", destination)
            plan_path = base / "plan.json"
            write_install_plan(plan, plan_path)
            confirm_install_plan(
                plan_path,
                digest=plan["proposal_digest"],
                approved_by="Owner",
            )
            with mock.patch.object(host_lifecycle, "fcntl", None):
                with self.assertRaisesRegex(HostLifecycleError, "POSIX fcntl"):
                    apply_install_plan(plan_path)

    def test_install_lock_file_ownership_is_recomputed_before_uninstall(self) -> None:
        for variant in ("append", "delete", "replace", "reorder"):
            with self.subTest(variant=variant), tempfile.TemporaryDirectory() as temporary:
                base = Path(temporary)
                team = self._team(base)
                destination = base / "destination"
                destination.mkdir()
                user_file = destination / "user-owned.txt"
                user_file.write_text("keep me\n", encoding="utf-8")
                plan = build_install_plan(team, "codex", destination)
                plan_path = base / "plan.json"
                write_install_plan(plan, plan_path)
                confirm_install_plan(
                    plan_path,
                    digest=plan["proposal_digest"],
                    approved_by="Owner",
                )
                apply_install_plan(plan_path)
                lock_path = destination / ".agent-team/host-install.lock.json"
                lock = json.loads(lock_path.read_text(encoding="utf-8"))
                if variant == "append":
                    lock["files"].append(
                        {
                            "path": "user-owned.txt",
                            "stage_path": "user-owned.txt.host-stage-" + ("0" * 24),
                            "sha256": host_lifecycle._sha256_bytes(user_file.read_bytes()),
                            "binding": None,
                            "state": "PRESENT",
                        }
                    )
                elif variant == "delete":
                    lock["files"].pop()
                elif variant == "replace":
                    lock["files"][0]["sha256"] = "sha256:" + ("0" * 64)
                else:
                    lock["files"].reverse()
                lock_path.write_text(
                    json.dumps(lock, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
                with self.assertRaises(HostLifecycleError):
                    uninstall_installation(
                        destination,
                        digest=plan["proposal_digest"],
                    )
                self.assertEqual(user_file.read_text(encoding="utf-8"), "keep me\n")
                self.assertTrue(
                    (destination / plan["proposal"]["files"][0]["path"]).is_file()
                )

    def test_reinstall_deletes_only_the_exact_tombstone_bound_by_a_new_plan(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            team = self._team(base)
            destination = base / "destination"
            first = build_install_plan(team, "codex", destination)
            first_path = base / "first.json"
            write_install_plan(first, first_path)
            confirm_install_plan(
                first_path,
                digest=first["proposal_digest"],
                approved_by="Owner",
            )
            apply_install_plan(first_path)
            uninstall_installation(destination, digest=first["proposal_digest"])

            replacement = build_install_plan(team, "codex", destination)
            replacement_path = base / "replacement.json"
            write_install_plan(replacement, replacement_path)
            confirm_install_plan(
                replacement_path,
                digest=replacement["proposal_digest"],
                approved_by="Owner",
            )
            tombstone_path = destination / ".agent-team/host-uninstall.tombstone.json"
            foreign = json.loads(tombstone_path.read_text(encoding="utf-8"))
            foreign["team_id"] = "team.foreign"
            tombstone_path.write_text(
                json.dumps(foreign, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(HostLifecycleError, "tombstone changed"):
                apply_install_plan(replacement_path)
            self.assertEqual(
                json.loads(tombstone_path.read_text(encoding="utf-8"))["team_id"],
                "team.foreign",
            )
            self.assertFalse((destination / ".agent-team/host-install.lock.json").exists())

    def test_uninstall_never_removes_a_preexisting_empty_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            team = self._team(base)
            destination = base / "destination"
            (destination / ".codex").mkdir(parents=True)
            plan = build_install_plan(team, "codex", destination)
            plan_path = base / "plan.json"
            write_install_plan(plan, plan_path)
            confirm_install_plan(
                plan_path,
                digest=plan["proposal_digest"],
                approved_by="Owner",
            )
            apply_install_plan(plan_path)
            uninstall_installation(destination, digest=plan["proposal_digest"])
            self.assertTrue((destination / ".codex").is_dir())

    def test_exact_recovery_stage_is_cleaned_on_apply_resume(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            team = self._team(base)
            destination = base / "destination"
            plan = build_install_plan(team, "codex", destination)
            plan_path = base / "plan.json"
            write_install_plan(plan, plan_path)
            confirm_install_plan(
                plan_path,
                digest=plan["proposal_digest"],
                approved_by="Owner",
            )
            original_unlink = host_lifecycle.os.unlink
            interrupted = False

            def interrupt_stage_unlink(path: object, *args: object, **kwargs: object) -> None:
                nonlocal interrupted
                if not interrupted and ".host-stage-" in str(path):
                    interrupted = True
                    raise OSError("simulated crash after publication")
                original_unlink(path, *args, **kwargs)

            with mock.patch("core.host_lifecycle.os.unlink", side_effect=interrupt_stage_unlink):
                with self.assertRaisesRegex(OSError, "simulated crash"):
                    apply_install_plan(plan_path)
            stages = [destination / item["stage_path"] for item in plan["proposal"]["files"]]
            self.assertTrue(any(path.exists() for path in stages))
            self.assertEqual(apply_install_plan(plan_path)["status"], "VALID")
            self.assertFalse(any(path.exists() or path.is_symlink() for path in stages))
            uninstall_installation(destination, digest=plan["proposal_digest"])
            self.assertFalse(any(path.exists() or path.is_symlink() for path in stages))

    def test_guard_and_destination_identity_changes_after_plan_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            team = self._team(base)
            destination = base / "destination"
            plan = build_install_plan(team, "codex", destination)
            plan_path = base / "plan.json"
            write_install_plan(plan, plan_path)
            confirm_install_plan(
                plan_path,
                digest=plan["proposal_digest"],
                approved_by="Owner",
            )
            (destination / ".agent-team").mkdir(parents=True)
            (destination / ".agent-team/.host-lifecycle.guard").write_text(
                "user content\n", encoding="utf-8"
            )
            with self.assertRaisesRegex(HostLifecycleError, "guard content is invalid"):
                apply_install_plan(plan_path)
            self.assertFalse((destination / ".agent-team/host-install.lock.json").exists())

        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            team = self._team(base)
            destination = base / "destination"
            plan = build_install_plan(team, "codex", destination)
            plan_path = base / "plan.json"
            write_install_plan(plan, plan_path)
            confirm_install_plan(
                plan_path,
                digest=plan["proposal_digest"],
                approved_by="Owner",
            )
            original_assert = host_lifecycle._assert_directory_binding
            calls = 0

            def rename_after_guard(path: Path, expected: dict[str, int]) -> None:
                nonlocal calls
                calls += 1
                original_assert(path, expected)
                if calls == 1:
                    path.rename(base / "renamed-destination")
                    path.mkdir()

            with mock.patch(
                "core.host_lifecycle._assert_directory_binding",
                side_effect=rename_after_guard,
            ):
                with self.assertRaisesRegex(HostLifecycleError, "directory changed"):
                    apply_install_plan(plan_path)
            self.assertFalse((destination / ".agent-team/host-install.lock.json").exists())

    def test_v1_missing_guard_fails_instead_of_becoming_legacy(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            team = self._team(base)
            destination = base / "destination"
            plan = build_install_plan(team, "codex", destination)
            plan_path = base / "plan.json"
            write_install_plan(plan, plan_path)
            confirm_install_plan(
                plan_path,
                digest=plan["proposal_digest"],
                approved_by="Owner",
            )
            apply_install_plan(plan_path)
            (destination / ".agent-team/.host-lifecycle.guard").unlink()
            with self.assertRaisesRegex(HostLifecycleError, "guard is missing"):
                verify_installation(destination)

    def test_apply_intent_without_durable_applying_record_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            team = self._team(base)
            destination = base / "destination"
            plan = build_install_plan(team, "codex", destination)
            plan_path = base / "plan.json"
            write_install_plan(plan, plan_path)
            confirm_install_plan(
                plan_path,
                digest=plan["proposal_digest"],
                approved_by="Owner",
            )
            with mock.patch(
                "core.host_lifecycle._atomic_json_relative",
                side_effect=OSError("simulated crash before APPLYING lock"),
            ):
                with self.assertRaisesRegex(OSError, "before APPLYING"):
                    apply_install_plan(plan_path)
            guard = destination / ".agent-team/.host-lifecycle.guard"
            intent = destination / plan["proposal"]["lifecycle"]["initial_apply_intent"]
            self.assertTrue(guard.is_file())
            self.assertEqual(guard.stat().st_size, 0)
            self.assertTrue(intent.is_file())
            self.assertFalse((destination / ".agent-team/host-install.lock.json").exists())
            with self.assertRaisesRegex(
                HostLifecycleError,
                "appeared without a durable APPLYING record",
            ):
                apply_install_plan(plan_path)
            self.assertTrue(intent.is_file())

    def test_new_guard_file_and_parent_are_fsynced_before_applying_record(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            team = self._team(base)
            destination = base / "destination"
            plan = build_install_plan(team, "codex", destination)
            plan_path = base / "plan.json"
            write_install_plan(plan, plan_path)
            confirm_install_plan(
                plan_path,
                digest=plan["proposal_digest"],
                approved_by="Owner",
            )

            original_open = host_lifecycle.os.open
            original_fsync = host_lifecycle.os.fsync
            guard_descriptor: int | None = None
            guard_parent: int | None = None
            events: list[str] = []

            def capture_open(*args: object, **kwargs: object) -> int:
                nonlocal guard_descriptor, guard_parent
                descriptor = original_open(*args, **kwargs)
                if (
                    args
                    and str(args[0]) == ".host-lifecycle.guard"
                    and len(args) > 1
                    and int(args[1]) & host_lifecycle.os.O_EXCL
                ):
                    guard_descriptor = descriptor
                    parent = kwargs.get("dir_fd")
                    guard_parent = int(parent) if isinstance(parent, int) else None
                return descriptor

            def capture_fsync(descriptor: int) -> None:
                if descriptor == guard_descriptor:
                    events.append("guard-file")
                elif guard_parent is not None and descriptor == guard_parent:
                    events.append("guard-parent")
                original_fsync(descriptor)

            def stop_before_applying(*args: object, **kwargs: object) -> None:
                events.append("applying-record")
                raise OSError("stop after durable guard")

            with (
                mock.patch("core.host_lifecycle.os.open", side_effect=capture_open),
                mock.patch("core.host_lifecycle.os.fsync", side_effect=capture_fsync),
                mock.patch(
                    "core.host_lifecycle._atomic_json_relative",
                    side_effect=stop_before_applying,
                ),
            ):
                with self.assertRaisesRegex(OSError, "durable guard"):
                    apply_install_plan(plan_path)
            self.assertEqual(
                events,
                ["guard-file", "guard-parent", "applying-record"],
            )

    def test_partial_recovery_stage_is_rebuilt_only_under_exact_applying_lock(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            team = self._team(base)
            destination = base / "destination"
            plan = build_install_plan(team, "codex", destination)
            plan_path = base / "plan.json"
            write_install_plan(plan, plan_path)
            confirm_install_plan(
                plan_path,
                digest=plan["proposal_digest"],
                approved_by="Owner",
            )
            with mock.patch(
                "core.host_lifecycle._copy_exclusive",
                side_effect=OSError("simulated exit during stage write"),
            ):
                with self.assertRaisesRegex(OSError, "stage write"):
                    apply_install_plan(plan_path)
            first = plan["proposal"]["files"][0]
            stage = destination / first["stage_path"]
            intent = destination / first["intent_path"]
            stage.parent.mkdir(parents=True, exist_ok=True)
            stage.write_bytes(b"partial")
            with self.assertRaisesRegex(
                HostLifecycleError,
                "recovery (target or stage lacks|stage is not bound)",
            ):
                apply_install_plan(plan_path)
            self.assertEqual(stage.read_bytes(), b"partial")
            self.assertFalse(intent.exists() or intent.is_symlink())

    def test_partial_pre_applying_metadata_stage_fails_closed_and_is_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            team = self._team(base)
            destination = base / "destination"
            plan = build_install_plan(team, "codex", destination)
            plan_path = base / "plan.json"
            write_install_plan(plan, plan_path)
            confirm_install_plan(
                plan_path,
                digest=plan["proposal_digest"],
                approved_by="Owner",
            )
            (destination / ".agent-team").mkdir(parents=True)
            unrelated = (
                destination
                / ".agent-team/.host-install.lock.json.host-json-stage-aaaaaaaaaaaaaaaaaaaaaaaa"
            )
            unrelated.write_text("user owned\n", encoding="utf-8")
            original_write = host_lifecycle.os.write
            interrupted = False

            def partial_write(descriptor: int, content: bytes) -> int:
                nonlocal interrupted
                if not interrupted:
                    interrupted = True
                    original_write(descriptor, content[: max(1, len(content) // 2)])
                    raise OSError("simulated metadata-stage power loss")
                return original_write(descriptor, content)

            with mock.patch("core.host_lifecycle.os.write", side_effect=partial_write):
                with self.assertRaisesRegex(OSError, "power loss"):
                    apply_install_plan(plan_path)
            metadata_stage = destination / ".agent-team/.host-lifecycle.json.stage"
            self.assertTrue(metadata_stage.is_file())
            self.assertIn(
                ".agent-team/.host-lifecycle.json.stage",
                preview_install_plan(plan),
            )
            partial = metadata_stage.read_bytes()
            initial_intent = destination / plan["proposal"]["lifecycle"][
                "initial_apply_intent"
            ]
            self.assertTrue(initial_intent.is_file())
            with self.assertRaisesRegex(
                HostLifecycleError,
                "appeared without a durable APPLYING record",
            ):
                apply_install_plan(plan_path)
            self.assertEqual(metadata_stage.read_bytes(), partial)
            self.assertTrue(initial_intent.is_file())
            self.assertFalse(
                (destination / ".agent-team/host-install.lock.json").exists()
            )
            self.assertEqual(unrelated.read_text(encoding="utf-8"), "user owned\n")

    def test_root_rebind_never_redirects_apply_mutations_to_replacement(self) -> None:
        for phase in ("json", "copy"):
            with self.subTest(phase=phase), tempfile.TemporaryDirectory() as temporary:
                base = Path(temporary)
                team = self._team(base)
                destination = base / "destination"
                moved = base / "moved-destination"
                plan = build_install_plan(team, "codex", destination)
                plan_path = base / "plan.json"
                write_install_plan(plan, plan_path)
                confirm_install_plan(
                    plan_path,
                    digest=plan["proposal_digest"],
                    approved_by="Owner",
                )
                original = (
                    host_lifecycle._atomic_json_relative
                    if phase == "json"
                    else host_lifecycle._copy_exclusive
                )
                rebound = False

                def rebind_then_mutate(*args: object, **kwargs: object) -> None:
                    nonlocal rebound
                    if not rebound:
                        rebound = True
                        destination.rename(moved)
                        destination.mkdir()
                    original(*args, **kwargs)

                symbol = (
                    "core.host_lifecycle._atomic_json_relative"
                    if phase == "json"
                    else "core.host_lifecycle._copy_exclusive"
                )
                with mock.patch(symbol, side_effect=rebind_then_mutate):
                    with self.assertRaisesRegex(HostLifecycleError, "directory changed"):
                        apply_install_plan(plan_path)
                self.assertFalse(
                    (destination / ".agent-team/host-install.lock.json").exists()
                )
                self.assertFalse(
                    (destination / plan["proposal"]["files"][0]["path"]).exists()
                )

    def test_root_rebind_never_redirects_uninstall_mutations_to_replacement(self) -> None:
        for phase in ("json", "unlink"):
            with self.subTest(phase=phase), tempfile.TemporaryDirectory() as temporary:
                base = Path(temporary)
                team = self._team(base)
                destination = base / "destination"
                moved = base / "moved-destination"
                plan = build_install_plan(team, "codex", destination)
                plan_path = base / "plan.json"
                write_install_plan(plan, plan_path)
                confirm_install_plan(
                    plan_path,
                    digest=plan["proposal_digest"],
                    approved_by="Owner",
                )
                apply_install_plan(plan_path)
                first = plan["proposal"]["files"][0]
                original = (
                    host_lifecycle._atomic_json_relative
                    if phase == "json"
                    else host_lifecycle._unlink_bound_relative
                )
                rebound = False

                def rebind_then_mutate(*args: object, **kwargs: object) -> object:
                    nonlocal rebound
                    if not rebound:
                        rebound = True
                        destination.rename(moved)
                        destination.mkdir()
                        replacement = destination / first["path"]
                        replacement.parent.mkdir(parents=True, exist_ok=True)
                        replacement.write_bytes((moved / first["path"]).read_bytes())
                    return original(*args, **kwargs)

                symbol = (
                    "core.host_lifecycle._atomic_json_relative"
                    if phase == "json"
                    else "core.host_lifecycle._unlink_bound_relative"
                )
                with mock.patch(symbol, side_effect=rebind_then_mutate):
                    with self.assertRaisesRegex(HostLifecycleError, "directory changed"):
                        uninstall_installation(
                            destination,
                            digest=plan["proposal_digest"],
                        )
                self.assertTrue((destination / first["path"]).is_file())
                self.assertFalse(
                    (destination / ".agent-team/host-install.lock.json").exists()
                )

    def test_v09_active_lock_is_read_only_and_never_used_for_destructive_uninstall(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            team = self._team(base)
            destination = base / "destination"
            plan = build_install_plan(team, "codex", destination)
            plan_path = base / "plan.json"
            write_install_plan(plan, plan_path)
            confirm_install_plan(
                plan_path,
                digest=plan["proposal_digest"],
                approved_by="Owner",
            )
            apply_install_plan(plan_path)

            guard = destination / ".agent-team/.host-lifecycle.guard"
            guard.unlink()
            lock_path = destination / ".agent-team/host-install.lock.json"
            legacy = json.loads(lock_path.read_text(encoding="utf-8"))
            legacy["schema_version"] = "1.0.0"
            legacy.pop("guard_binding")
            legacy.pop("proposal")
            for record in legacy["files"]:
                record.pop("stage_path")
                record.pop("intent_path")
                record.pop("binding")
                record.pop("state")
            lock_path.write_text(json.dumps(legacy, indent=2, sort_keys=True) + "\n", encoding="utf-8")

            with mock.patch.object(host_lifecycle, "fcntl", None):
                verified = verify_installation(destination)
            self.assertEqual(verified["status"], "LEGACY_UNBOUND")
            self.assertFalse(verified["concurrency_guarded"])
            self.assertFalse(verified["destructive_uninstall_enabled"])
            with self.assertRaisesRegex(HostLifecycleError, "legacy.*ownership"):
                uninstall_installation(destination, digest=plan["proposal_digest"])
            self.assertTrue((destination / plan["proposal"]["files"][0]["path"]).is_file())


if __name__ == "__main__":
    unittest.main()
