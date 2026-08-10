from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.control_plane import ControlPlane
from core.instance import init_instance, validate_instance_directory
from core.lifecycle import (
    LifecycleError,
    apply_instance_upgrade,
    inspect_recovery_bundle,
    recover_interrupted_lifecycle,
    rollback_instance,
    write_instance_upgrade_plan,
)
from core.models import Actor

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "team-instance" / "input" / "instance.json"
OLD_RELEASES = {
    "0.2.0": (
        "995c4f3eb8690498d7501bcc8e29c187b23e0c9e",
        "sha256:cbe49ab83eec4e8244853228215fb86bb8782aa16d61bd53729c165759833c60",
    ),
    "0.3.0": (
        "ff14abf39200b13e0363d58862333ad596e2825c",
        "sha256:bfcbc29ecb54c43b1a858c2ee03d18528605e2741a878e08e0433d3c09301451",
    ),
    "0.4.0": (
        "43c5202df6727a779dd0a5f4c0caec29090b18fd",
        "sha256:7dc2e979fcefef6c00c4c5d223c5bfb2019519ceebe733a41686dc253d100fee",
    ),
    "0.5.0": (
        "67d22264d000253837676a13ca8034cffe2a8486",
        "sha256:ef963b23dcb7331213dc1462f6064ef8945ea8564a337f6b013e9b6f3e8fb36d",
    ),
}


def _digest(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _write_json(path: Path, value: dict) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _make_old_instance(base: Path, version: str) -> Path:
    instance = base / "instance"
    init_instance(EXAMPLE, instance)
    lock_path = instance / ".agent-team" / "instance.lock.json"
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    for record in lock["files"]:
        path = instance / record["path"]
        content = path.read_text(encoding="utf-8").replace("0.5.1", version)
        path.write_text(content, encoding="utf-8")
        record["sha256"] = _digest(content.encode("utf-8"))
    revision, contract = OLD_RELEASES[version]
    lock["factory"] = {
        "id": "factory.agent-team-engineering",
        "version": version,
        "source_revision": revision,
        "source_dirty": False,
        "contract_digest": contract,
    }
    _write_json(lock_path, lock)
    findings = validate_instance_directory(instance)
    if any(finding.severity == "ERROR" for finding in findings):
        raise AssertionError(findings)
    return instance


def _make_v04_instance(base: Path) -> Path:
    return _make_old_instance(base, "0.4.0")


def _locked_version(instance: Path) -> str:
    return json.loads(
        (instance / ".agent-team" / "instance.lock.json").read_text(encoding="utf-8")
    )["factory"]["version"]


class InstanceLifecycleTests(unittest.TestCase):
    def test_every_declared_legacy_release_has_an_explicit_upgrade_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            for version in OLD_RELEASES:
                with self.subTest(version=version):
                    case = base / version
                    instance = _make_old_instance(case, version)
                    plan_path = case / "upgrade-plan.json"
                    recovery = case / "recovery"
                    plan = write_instance_upgrade_plan(instance, plan_path)
                    self.assertEqual(plan["source"]["factory_version"], version)
                    result = apply_instance_upgrade(
                        instance,
                        plan_path,
                        recovery,
                        _allow_dirty_factory=True,
                    )
                    self.assertEqual(result["status"], "UPGRADED")
                    self.assertEqual(_locked_version(instance), "0.5.1")

    def test_upgrade_plan_output_cannot_be_a_symbolic_link(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            instance = _make_v04_instance(base)
            plan_link = base / "upgrade-plan.json"
            plan_link.symlink_to(base / "redirected-plan.json")
            with self.assertRaisesRegex(LifecycleError, "symbolic link"):
                write_instance_upgrade_plan(instance, plan_link)

    def test_upgrade_preserves_seeded_customization_and_round_trip_rollback(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            instance = _make_v04_instance(base)
            readme = instance / "README.md"
            readme.write_text("owner customization\n", encoding="utf-8")
            plan_path = base / "upgrade-plan.json"
            recovery = base / "recovery-v04"
            plan = write_instance_upgrade_plan(instance, plan_path)

            self.assertEqual(plan["source"]["factory_version"], "0.4.0")
            self.assertEqual(plan["target"]["factory_version"], "0.5.1")
            self.assertIn("README.md", plan["preserved_seeded_files"])
            result = apply_instance_upgrade(
                instance,
                plan_path,
                recovery,
                _allow_dirty_factory=True,
            )

            self.assertEqual(result["status"], "UPGRADED")
            self.assertEqual(_locked_version(instance), "0.5.1")
            self.assertEqual(readme.read_text(encoding="utf-8"), "owner customization\n")
            self.assertFalse((instance / "runtime" / ".factory-lifecycle-journal.json").exists())
            self.assertFalse(
                any(finding.severity == "ERROR" for finding in validate_instance_directory(instance))
            )

            rescue = base / "rescue-v05"
            rolled_back = rollback_instance(instance, recovery, rescue)
            self.assertEqual(rolled_back["status"], "ROLLED_BACK")
            self.assertEqual(_locked_version(instance), "0.4.0")
            self.assertEqual(readme.read_text(encoding="utf-8"), "owner customization\n")

            second_rescue = base / "rescue-v04"
            restored = rollback_instance(instance, rescue, second_rescue)
            self.assertEqual(restored["status"], "ROLLED_BACK")
            self.assertEqual(_locked_version(instance), "0.5.1")

    def test_stale_plan_fails_before_recovery_or_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            instance = _make_v04_instance(base)
            plan_path = base / "upgrade-plan.json"
            recovery = base / "recovery"
            write_instance_upgrade_plan(instance, plan_path)
            lock_path = instance / ".agent-team" / "instance.lock.json"
            lock = json.loads(lock_path.read_text(encoding="utf-8"))
            lock_path.write_text(json.dumps(lock, separators=(",", ":")), encoding="utf-8")

            with self.assertRaisesRegex(LifecycleError, "stale"):
                apply_instance_upgrade(
                    instance,
                    plan_path,
                    recovery,
                    _allow_dirty_factory=True,
                )
            self.assertFalse(recovery.exists())
            self.assertEqual(_locked_version(instance), "0.4.0")

    def test_runtime_must_be_paused_and_have_no_active_work(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            instance = _make_v04_instance(base)
            plan_path = base / "upgrade-plan.json"
            write_instance_upgrade_plan(instance, plan_path)
            database = instance / "runtime" / "state" / "control-plane.sqlite3"
            with ControlPlane(database, create=True):
                pass

            with self.assertRaisesRegex(LifecycleError, "paused"):
                apply_instance_upgrade(
                    instance,
                    plan_path,
                    base / "recovery-unpaused",
                    _allow_dirty_factory=True,
                )
            with ControlPlane(database, create=False) as control:
                control.set_paused(
                    True,
                    Actor("human.owner", "owner", kind="human"),
                    reason="planned upgrade",
                    idempotency_key="pause-for-upgrade",
                )
            result = apply_instance_upgrade(
                instance,
                plan_path,
                base / "recovery-paused",
                _allow_dirty_factory=True,
            )
            self.assertEqual(result["runtime"]["state"], "QUIESCENT")

    def test_injected_failure_automatically_restores_source(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            instance = _make_v04_instance(base)
            plan_path = base / "upgrade-plan.json"
            recovery = base / "recovery"
            write_instance_upgrade_plan(instance, plan_path)

            with self.assertRaisesRegex(LifecycleError, "rolled back"):
                apply_instance_upgrade(
                    instance,
                    plan_path,
                    recovery,
                    _allow_dirty_factory=True,
                    _fail_after_actions=1,
                )
            self.assertEqual(_locked_version(instance), "0.4.0")
            self.assertTrue(recovery.is_dir())
            self.assertFalse((instance / "runtime" / ".factory-lifecycle-journal.json").exists())
            self.assertFalse(
                any(finding.severity == "ERROR" for finding in validate_instance_directory(instance))
            )

    def test_interrupted_upgrade_is_recovered_from_journal(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            instance = _make_v04_instance(base)
            plan_path = base / "upgrade-plan.json"
            recovery = base / "recovery"
            write_instance_upgrade_plan(instance, plan_path)

            with self.assertRaises(RuntimeError):
                apply_instance_upgrade(
                    instance,
                    plan_path,
                    recovery,
                    _allow_dirty_factory=True,
                    _simulate_crash_after_actions=1,
                )
            self.assertTrue((instance / "runtime" / ".factory-lifecycle-journal.json").is_file())
            result = recover_interrupted_lifecycle(instance)
            self.assertEqual(result["status"], "RECOVERED_TO_SOURCE")
            self.assertEqual(_locked_version(instance), "0.4.0")
            self.assertFalse((instance / "runtime" / ".factory-lifecycle-journal.json").exists())

    def test_interrupted_rollback_is_recovered_from_journal(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            instance = _make_v04_instance(base)
            plan_path = base / "upgrade-plan.json"
            recovery = base / "recovery-v04"
            write_instance_upgrade_plan(instance, plan_path)
            apply_instance_upgrade(
                instance,
                plan_path,
                recovery,
                _allow_dirty_factory=True,
            )

            with self.assertRaises(RuntimeError):
                rollback_instance(
                    instance,
                    recovery,
                    base / "rescue-v05",
                    _simulate_crash_after_actions=1,
                )
            journal_path = instance / "runtime" / ".factory-lifecycle-journal.json"
            self.assertTrue(journal_path.is_file())
            journal = json.loads(journal_path.read_text(encoding="utf-8"))
            self.assertEqual(journal["operation"], "ROLLBACK")

            result = recover_interrupted_lifecycle(instance)
            self.assertEqual(result["status"], "RECOVERED_TO_PRE_ROLLBACK")
            self.assertEqual(result["operation"], "ROLLBACK")
            self.assertEqual(_locked_version(instance), "0.5.1")
            self.assertFalse(journal_path.exists())

    def test_rollback_failure_automatically_restores_pre_rollback_release(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            instance = _make_v04_instance(base)
            plan_path = base / "upgrade-plan.json"
            recovery = base / "recovery-v04"
            write_instance_upgrade_plan(instance, plan_path)
            apply_instance_upgrade(
                instance,
                plan_path,
                recovery,
                _allow_dirty_factory=True,
            )

            with self.assertRaisesRegex(LifecycleError, "current release was rescued"):
                rollback_instance(
                    instance,
                    recovery,
                    base / "rescue-v05",
                    _fail_after_actions=1,
                )
            self.assertEqual(_locked_version(instance), "0.5.1")
            self.assertFalse((instance / "runtime" / ".factory-lifecycle-journal.json").exists())

    def test_tampered_recovery_bundle_cannot_roll_back(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            instance = _make_v04_instance(base)
            plan_path = base / "upgrade-plan.json"
            recovery = base / "recovery"
            write_instance_upgrade_plan(instance, plan_path)
            apply_instance_upgrade(
                instance,
                plan_path,
                recovery,
                _allow_dirty_factory=True,
            )
            manifest = inspect_recovery_bundle(recovery)
            record = next(
                item
                for item in manifest["files"]
                if item["path"] != ".agent-team/instance.lock.json" and item["existed"]
            )
            backup = recovery / "files" / record["path"]
            backup.write_text("tampered\n", encoding="utf-8")

            with self.assertRaisesRegex(LifecycleError, "digest differs"):
                rollback_instance(instance, recovery, base / "rescue")
            self.assertEqual(_locked_version(instance), "0.5.1")

    def test_recovery_bundle_permissions_are_part_of_verification(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            instance = _make_v04_instance(base)
            plan_path = base / "upgrade-plan.json"
            recovery = base / "recovery"
            write_instance_upgrade_plan(instance, plan_path)
            apply_instance_upgrade(
                instance,
                plan_path,
                recovery,
                _allow_dirty_factory=True,
            )
            recovery.chmod(0o755)

            with self.assertRaisesRegex(LifecycleError, "permissions must be 0700"):
                inspect_recovery_bundle(recovery)

    def test_dirty_factory_requires_an_explicit_internal_test_override(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            instance = _make_v04_instance(base)
            plan_path = base / "upgrade-plan.json"
            with patch(
                "core.instance._git_revision",
                return_value=("a" * 40, True),
            ):
                write_instance_upgrade_plan(instance, plan_path)
                with self.assertRaisesRegex(LifecycleError, "dirty Factory"):
                    apply_instance_upgrade(instance, plan_path, base / "recovery")
            self.assertFalse((base / "recovery").exists())

    def test_clean_untagged_factory_cannot_apply_an_upgrade(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            instance = _make_v04_instance(base)
            plan_path = base / "upgrade-plan.json"
            with patch(
                "core.instance._git_revision",
                return_value=("b" * 40, False),
            ):
                write_instance_upgrade_plan(instance, plan_path)
                with (
                    patch("core.lifecycle.current_source_release_verified", return_value=False),
                    self.assertRaisesRegex(LifecycleError, "unverified Factory release"),
                ):
                    apply_instance_upgrade(instance, plan_path, base / "recovery")
            self.assertFalse((base / "recovery").exists())


if __name__ == "__main__":
    unittest.main()
