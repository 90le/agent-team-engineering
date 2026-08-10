from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.installation import (
    InstallationError,
    build_installation_manifest,
    install_factory,
    verify_factory_installation,
)


class FactoryInstallationTests(unittest.TestCase):
    def test_public_install_path_cannot_bypass_release_identity(self) -> None:
        with patch(
            "core.installation._release_identity",
            return_value=("a" * 40, None, False),
        ):
            with self.assertRaisesRegex(InstallationError, "clean annotated"):
                build_installation_manifest()

    def test_development_snapshot_installs_atomically_and_verifies(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "factory"
            with patch(
                "core.installation._release_identity",
                return_value=("d" * 40, None, False),
            ):
                report = install_factory(destination, _allow_unreleased=True)
            manifest = verify_factory_installation(destination)

            self.assertEqual(report["status"], "INSTALLED")
            self.assertEqual(report["factory_version"], "0.6.0")
            self.assertFalse(report["release_verified"])
            self.assertEqual(report["installation_id"], manifest["installation_id"])
            self.assertTrue((destination / "tools" / "agent_team.py").is_file())
            self.assertFalse((destination / ".git").exists())

    def test_installation_never_overwrites_an_existing_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "factory"
            destination.mkdir()
            marker = destination / "owned.txt"
            marker.write_text("preserve\n", encoding="utf-8")
            with self.assertRaisesRegex(InstallationError, "already exists"):
                install_factory(destination, _allow_unreleased=True)
            self.assertEqual(marker.read_text(encoding="utf-8"), "preserve\n")

    def test_file_tampering_and_undeclared_files_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            first = base / "first"
            install_factory(first, _allow_unreleased=True)
            (first / "README.md").write_text("tampered\n", encoding="utf-8")
            with self.assertRaisesRegex(InstallationError, "metadata differs"):
                verify_factory_installation(first)

            second = base / "second"
            install_factory(second, _allow_unreleased=True)
            (second / "undeclared.txt").write_text("unexpected\n", encoding="utf-8")
            with self.assertRaisesRegex(InstallationError, "undeclared"):
                verify_factory_installation(second)

    def test_derived_bytecode_cache_is_not_an_integrity_exception(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            installation = Path(temporary) / "factory"
            install_factory(installation, _allow_unreleased=True)
            cache = installation / "core" / "__pycache__"
            cache.mkdir()
            (cache / "injected.pyc").write_bytes(b"untrusted bytecode")

            with self.assertRaisesRegex(InstallationError, "derived cache"):
                verify_factory_installation(installation)

    def test_installed_factory_rejects_symbolic_links(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "factory"
            install_factory(destination, _allow_unreleased=True)
            readme = destination / "README.md"
            original = destination / "README.original"
            readme.rename(original)
            readme.symlink_to(original.name)
            with self.assertRaisesRegex(InstallationError, "symbolic link"):
                verify_factory_installation(destination)

    def test_installed_entrypoint_can_diagnose_and_generate_an_instance(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            destination = base / "factory"
            instance = base / "instance"
            with patch(
                "core.installation._release_identity",
                return_value=("d" * 40, None, False),
            ):
                install_factory(destination, _allow_unreleased=True)
            doctor = subprocess.run(
                [sys.executable, str(destination / "tools" / "agent_team.py"), "doctor"],
                check=True,
                capture_output=True,
                text=True,
            )
            report = json.loads(doctor.stdout)
            self.assertEqual(report["source"]["mode"], "installed-distribution")
            self.assertFalse(report["source"]["release_verified"])
            subprocess.run(
                [
                    sys.executable,
                    str(destination / "tools" / "agent_team.py"),
                    "instance",
                    "init",
                    "--config",
                    str(destination / "examples" / "team-instance" / "input" / "instance.json"),
                    "--output",
                    str(instance),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            lock = json.loads(
                (instance / ".agent-team" / "instance.lock.json").read_text(encoding="utf-8")
            )
            manifest = verify_factory_installation(destination)
            self.assertEqual(lock["factory"]["source_revision"], manifest["source_revision"])
            self.assertTrue(lock["factory"]["source_dirty"])
            self.assertFalse(any(destination.rglob("__pycache__")))


if __name__ == "__main__":
    unittest.main()
