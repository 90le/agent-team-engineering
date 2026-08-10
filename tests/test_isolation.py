from __future__ import annotations

import copy
import unittest

from core.isolation import IsolationViolation, validate_execution_request


def safe_request() -> dict:
    return {
        "schema_version": "1.0.0",
        "job_id": "job-isolation-1",
        "work_item_id": "work-isolation-1",
        "project_id": "project.example",
        "source_ref": "project-source:project.example@main",
        "commit": "a" * 40,
        "command_id": "test",
        "arguments": ["--offline"],
        "workspace_id": "workspace-isolation-1",
        "timeout_seconds": 60,
        "network_policy": "none",
        "network_allowlist": [],
        "secret_refs": [],
        "source_read_only": True,
        "workspace_ephemeral": True,
        "production_mounts": False,
        "docker_socket": False,
        "privileged": False,
    }


class IsolationContractTests(unittest.TestCase):
    def test_safe_ephemeral_request_is_accepted(self) -> None:
        validate_execution_request(safe_request(), allowed_command_ids=("test",))

    def test_arbitrary_command_and_production_access_are_rejected(self) -> None:
        for field, value in (
            ("command_id", "arbitrary-shell"),
            ("source_read_only", False),
            ("workspace_ephemeral", False),
            ("production_mounts", True),
            ("docker_socket", True),
            ("privileged", True),
        ):
            request = safe_request()
            request[field] = value
            with self.subTest(field=field), self.assertRaises(IsolationViolation):
                validate_execution_request(request, allowed_command_ids=("test",))

    def test_unapproved_secret_and_private_network_target_are_rejected(self) -> None:
        request = safe_request()
        request["secret_refs"] = ["secret.production-database"]
        with self.assertRaises(IsolationViolation):
            validate_execution_request(request, allowed_command_ids=("test",))

        for target in ("127.0.0.1:8080", "10.0.0.2", "metadata.local"):
            request = safe_request()
            request["network_policy"] = "allowlist"
            request["network_allowlist"] = [target]
            with self.subTest(target=target), self.assertRaises(IsolationViolation):
                validate_execution_request(request, allowed_command_ids=("test",))

    def test_allowlisted_public_provider_and_bounded_secret_can_be_explicit(self) -> None:
        request = copy.deepcopy(safe_request())
        request["network_policy"] = "allowlist"
        request["network_allowlist"] = ["api.example.com:443"]
        request["secret_refs"] = ["secret.test-provider"]
        validate_execution_request(
            request,
            allowed_command_ids=("test",),
            allowed_secret_refs=("secret.test-provider",),
        )


if __name__ == "__main__":
    unittest.main()
