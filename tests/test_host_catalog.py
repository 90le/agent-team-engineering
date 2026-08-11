from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from core.host_catalog import (
    HostCatalogError,
    list_host_ids,
    load_host_catalog,
    load_host_descriptor,
    probe_host,
    validate_host_descriptor,
)

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_HOSTS = ("claude", "codex", "generic-ai", "hermes", "multica", "openclaw")


class HostCatalogTests(unittest.TestCase):
    def test_catalog_has_six_explicit_hosts_and_does_not_invent_leda(self) -> None:
        self.assertEqual(list_host_ids(), EXPECTED_HOSTS)
        catalog = load_host_catalog()
        self.assertEqual(tuple(catalog), EXPECTED_HOSTS)
        self.assertNotIn("leda", catalog)
        self.assertTrue(all(not validate_host_descriptor(value) for value in catalog.values()))

    def test_multica_is_pinned_experimental_overlay_with_custom_license(self) -> None:
        descriptor = load_host_descriptor("multica")
        self.assertEqual(descriptor["support_tier"], "experimental-plan")
        self.assertEqual(descriptor["integration_mode"], "overlay")
        self.assertEqual(descriptor["upstream"]["pinned_version"], "v0.4.23")
        self.assertEqual(
            descriptor["upstream"]["pinned_commit"],
            "e0d0b3815342a80460f8a1c66c56ddfc662c7d46",
        )
        self.assertEqual(descriptor["license"]["classification"], "custom-source-available")
        self.assertNotEqual(descriptor["license"]["identifier"], "Apache-2.0")

    def test_local_version_evidence_is_exact_but_not_a_runtime_load_claim(self) -> None:
        openclaw = load_host_descriptor("openclaw")
        hermes = load_host_descriptor("hermes")
        self.assertEqual(
            openclaw["tested_versions"][0]["observed_output"],
            "OpenClaw 2026.7.1-2 (0790d9f)",
        )
        self.assertEqual(
            hermes["tested_versions"][0]["observed_output"],
            "Hermes Agent v0.20.0 (2026.8.3)",
        )
        self.assertEqual(openclaw["support_tier"], "native-install-verified")
        self.assertEqual(hermes["support_tier"], "native-install-verified")

    def test_probe_runs_only_declared_version_argv_with_isolated_environment(self) -> None:
        calls: list[tuple[list[str], dict[str, object]]] = []

        def fake_run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
            calls.append((argv, kwargs))
            return subprocess.CompletedProcess(argv, 0, "OpenClaw 2026.7.1-2\n", "")

        result = probe_host(
            "openclaw",
            which=lambda name: "/safe/bin/openclaw" if name == "openclaw" else None,
            run=fake_run,
            environment={"PATH": "/safe/bin", "OPENAI_API_KEY": "must-not-be-forwarded"},
        )
        self.assertEqual(result["status"], "available")
        self.assertEqual(result["version_output"], "OpenClaw 2026.7.1-2")
        self.assertEqual(len(calls), 1)
        argv, kwargs = calls[0]
        self.assertEqual(argv, ["/safe/bin/openclaw", "--version"])
        self.assertIs(kwargs["shell"], False)
        self.assertEqual(kwargs["cwd"], "/")
        self.assertEqual(kwargs["env"]["HOME"], "/nonexistent")
        self.assertNotIn("OPENAI_API_KEY", kwargs["env"])
        self.assertIs(kwargs["stdin"], subprocess.DEVNULL)

    def test_missing_timeout_and_os_error_fail_closed_without_escaping(self) -> None:
        not_found = probe_host("codex", which=lambda _name: None)
        self.assertEqual(not_found["status"], "not-found")
        self.assertFalse(not_found["installed"])

        def timeout(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
            raise subprocess.TimeoutExpired(["hermes", "--version"], 3)

        timed_out = probe_host("hermes", which=lambda _name: "/bin/hermes", run=timeout)
        self.assertEqual(timed_out["status"], "timeout")
        self.assertEqual(timed_out["error"], "version-command-timeout")

        def os_error(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
            raise OSError("sensitive local detail")

        failed = probe_host("claude", which=lambda _name: "/bin/claude", run=os_error)
        self.assertEqual(failed["status"], "error")
        self.assertNotIn("sensitive", json.dumps(failed))

    def test_portable_host_never_executes_a_process(self) -> None:
        def must_not_run(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
            raise AssertionError("portable host probe must not invoke a process")

        result = probe_host("generic-ai", which=lambda _name: None, run=must_not_run)
        self.assertEqual(result["status"], "not-applicable")
        self.assertEqual(result["command"], [])

    def test_invalid_ids_and_non_version_commands_are_refused(self) -> None:
        for invalid in ("../openclaw", "/tmp/openclaw", "OpenClaw", "open_claw"):
            with self.subTest(host_id=invalid), self.assertRaises(HostCatalogError):
                load_host_descriptor(invalid)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "schemas").mkdir()
            (root / "hosts" / "unsafe").mkdir(parents=True)
            (root / "schemas" / "host-capability.schema.json").write_text(
                (ROOT / "schemas" / "host-capability.schema.json").read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            descriptor = load_host_descriptor("openclaw")
            descriptor["host_id"] = "unsafe"
            descriptor["probe"]["command"] = ["unsafe", "run"]
            (root / "hosts" / "unsafe" / "host.json").write_text(
                json.dumps(descriptor), encoding="utf-8"
            )
            with self.assertRaisesRegex(HostCatalogError, "only --version or version"):
                load_host_descriptor("unsafe", repository_root=root)


if __name__ == "__main__":
    unittest.main()
