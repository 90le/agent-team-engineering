from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path

from core.runner_conformance import (
    DISPOSABLE_ACK,
    REQUIRED_PROBES,
    RunnerConformanceError,
    assert_disposable_worker,
    build_native_oci_plan,
    load_sandbox_profile,
    validate_runner_report,
    validate_sandbox_profile,
)

ROOT = Path(__file__).resolve().parents[1]
PROFILE_PATH = ROOT / "examples" / "v08-contracts" / "valid" / "sandbox-profile.json"


def execution_request() -> dict:
    return {
        "schema_version": "1.0.0",
        "job_id": "job-runner-conformance",
        "work_item_id": "work-runner-conformance",
        "project_id": "project.conformance",
        "source_ref": "project-source:project.conformance@main",
        "commit": "a" * 40,
        "command_id": "probe",
        "arguments": [],
        "workspace_id": "workspace-runner-conformance",
        "timeout_seconds": 10,
        "network_policy": "none",
        "network_allowlist": [],
        "secret_refs": [],
        "source_read_only": True,
        "workspace_ephemeral": True,
        "production_mounts": False,
        "docker_socket": False,
        "privileged": False,
    }


def conformance_report() -> dict:
    results = {probe: "PASS" for probe in REQUIRED_PROBES}
    return {
        "schema_version": "1.0.0",
        "candidate_id": "runner.native-oci",
        "profile_id": "runner-profile.github-ephemeral-native-oci",
        "environment_kind": "github-hosted-ephemeral",
        "resolved_image_digest": "sha256:" + "b" * 64,
        "required_probe_ids": list(REQUIRED_PROBES),
        "runs": [
            {
                "run_id": f"run-{index}",
                "status": "PASS",
                "probe_results": copy.deepcopy(results),
                "container_residue": 0,
                "duration_milliseconds": 100,
            }
            for index in range(1, 4)
        ],
        "score": 100,
        "hard_gate_passed": True,
        "decision": "REFERENCE_ELIGIBLE",
        "cleanup_verified": True,
    }


class RunnerPlanTests(unittest.TestCase):
    def test_live_probe_requires_github_hosted_attestation_and_no_production_paths(self) -> None:
        environment = {
            "CI": "true",
            "GITHUB_ACTIONS": "true",
            "RUNNER_ENVIRONMENT": "github-hosted",
            "RUNNER_OS": "Linux",
            "GITHUB_EVENT_NAME": "pull_request",
            "AGENT_TEAM_DISPOSABLE_ACK": DISPOSABLE_ACK,
        }
        assert_disposable_worker(environment, path_exists=lambda path: False)

        for key in ("GITHUB_ACTIONS", "RUNNER_ENVIRONMENT", "AGENT_TEAM_DISPOSABLE_ACK"):
            unsafe = copy.deepcopy(environment)
            del unsafe[key]
            with self.subTest(key=key), self.assertRaises(RunnerConformanceError):
                assert_disposable_worker(unsafe, path_exists=lambda path: False)

        with self.assertRaises(RunnerConformanceError):
            assert_disposable_worker(
                environment,
                path_exists=lambda path: str(path) == "/mnt/synology",
            )

    def test_plan_is_immutable_bounded_and_has_no_shell(self) -> None:
        profile = load_sandbox_profile(PROFILE_PATH)
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "source"
            source.mkdir()
            plan = build_native_oci_plan(
                execution_request(),
                profile,
                source_directory=source,
                resolved_image_digest="sha256:" + "a" * 64,
                container_name="agent-team-conformance-1",
                command_registry={"probe": ("/bin/sh", "/source/probe.sh")},
            )
        argv = plan["argv"]
        self.assertEqual(argv[0:2], ["docker", "run"])
        self.assertIn("--read-only", argv)
        self.assertEqual(argv[argv.index("--network") + 1], "none")
        self.assertEqual(argv[argv.index("--cap-drop") + 1], "ALL")
        self.assertEqual(argv[argv.index("--user") + 1], "65534:65534")
        self.assertIn("no-new-privileges:true", argv)
        self.assertNotIn("--privileged", argv)
        self.assertNotIn("/var/run/docker.sock", " ".join(argv))
        self.assertTrue(plan["plan_digest"].startswith("sha256:"))

    def test_unsafe_request_and_mutable_image_are_rejected(self) -> None:
        profile = load_sandbox_profile(PROFILE_PATH)
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary)
            cases = []
            for field, value in (
                ("network_policy", "allowlist"),
                ("secret_refs", ["secret.example"]),
                ("arguments", ["--arbitrary"]),
                ("production_mounts", True),
            ):
                request = execution_request()
                request[field] = value
                if field == "network_policy":
                    request["network_allowlist"] = ["example.com:443"]
                cases.append((field, request, "sha256:" + "a" * 64))
            cases.append(("mutable-image", execution_request(), "alpine:3.22"))
            for label, request, image in cases:
                with self.subTest(label=label), self.assertRaises(RunnerConformanceError):
                    build_native_oci_plan(
                        request,
                        profile,
                        source_directory=source,
                        resolved_image_digest=image,
                        container_name="agent-team-conformance-1",
                        command_registry={"probe": ("true",)},
                    )

    def test_symlink_and_denied_source_are_rejected(self) -> None:
        profile = load_sandbox_profile(PROFILE_PATH)
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            source = base / "source"
            source.mkdir()
            link = base / "link"
            link.symlink_to(source, target_is_directory=True)
            with self.assertRaises(RunnerConformanceError):
                build_native_oci_plan(
                    execution_request(),
                    profile,
                    source_directory=link,
                    resolved_image_digest="sha256:" + "a" * 64,
                    container_name="agent-team-conformance-1",
                    command_registry={"probe": ("true",)},
                )

        denied_profile = copy.deepcopy(profile)
        denied_profile["mounts"]["denied_host_paths"].append("/tmp")
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaises(RunnerConformanceError):
                build_native_oci_plan(
                    execution_request(),
                    denied_profile,
                    source_directory=Path(temporary),
                    resolved_image_digest="sha256:" + "a" * 64,
                    container_name="agent-team-conformance-1",
                    command_registry={"probe": ("true",)},
                )

    def test_required_production_path_denials_are_fail_closed(self) -> None:
        profile = load_sandbox_profile(PROFILE_PATH)
        profile["mounts"]["denied_host_paths"].remove("/mnt/synology")
        with self.assertRaises(RunnerConformanceError):
            validate_sandbox_profile(profile)


class RunnerReportTests(unittest.TestCase):
    def test_three_complete_passes_are_reference_eligible(self) -> None:
        report = validate_runner_report(conformance_report())
        self.assertEqual(report["decision"], "REFERENCE_ELIGIBLE")

    def test_missing_probe_failed_run_and_false_decision_are_rejected(self) -> None:
        cases = []
        missing = conformance_report()
        del missing["runs"][0]["probe_results"][REQUIRED_PROBES[0]]
        cases.append(missing)

        failed = conformance_report()
        failed["runs"][1]["probe_results"][REQUIRED_PROBES[0]] = "FAIL"
        cases.append(failed)

        wrong_decision = conformance_report()
        wrong_decision["decision"] = "NO_GO"
        cases.append(wrong_decision)

        too_few = conformance_report()
        too_few["runs"] = too_few["runs"][:2]
        cases.append(too_few)

        for index, report in enumerate(cases):
            with self.subTest(case=index), self.assertRaises(RunnerConformanceError):
                validate_runner_report(report)


if __name__ == "__main__":
    unittest.main()
