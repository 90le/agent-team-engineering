from __future__ import annotations

import json
import subprocess
import unittest

from core.adapters import AdapterRetryableError
from core.github_transport import GitHubCliTransport


class GitHubCliTransportTests(unittest.TestCase):
    def test_create_uses_stdin_json_and_returns_only_stable_identity(self) -> None:
        calls: list[tuple[list[str], dict[str, object]]] = []

        def runner(arguments: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
            calls.append((arguments, kwargs))
            output = {"html_url": "https://github.com/owner/repo/issues/1", "node_id": "I_1"}
            return subprocess.CompletedProcess(arguments, 0, json.dumps(output), "")

        transport = GitHubCliTransport(
            command_runner=runner,
            binary_resolver=lambda name: f"/usr/bin/{name}",
        )
        result = transport.create(
            "issue.create",
            "/repos/owner/repo/issues",
            {"title": "Bound issue", "body": "No credentials"},
        )
        self.assertEqual(result["request_id"], "I_1")
        arguments, kwargs = calls[0]
        self.assertIn("--input", arguments)
        self.assertEqual(arguments[arguments.index("--input") + 1], "-")
        self.assertEqual(json.loads(str(kwargs["input"])), {"body": "No credentials", "title": "Bound issue"})
        self.assertFalse(any("token" in value.casefold() for value in arguments))

    def test_reconciliation_scans_paginated_records_for_exact_marker(self) -> None:
        marker = "<!-- agent-team-effect:abc -->"
        calls = 0

        def runner(arguments: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
            nonlocal calls
            del kwargs
            calls += 1
            if calls == 1:
                records = [{"body": "unrelated"} for _ in range(100)]
            else:
                records = [
                    {
                        "html_url": "https://github.com/owner/repo/pull/2",
                        "node_id": "PR_2",
                        "body": f"Proposal\n\n{marker}",
                    }
                ]
            return subprocess.CompletedProcess(arguments, 0, json.dumps(records), "")

        transport = GitHubCliTransport(
            command_runner=runner,
            binary_resolver=lambda name: f"/usr/bin/{name}",
        )
        result = transport.find_by_marker(
            "pull-request.create", "owner/repo", marker
        )
        self.assertEqual(result["request_id"], "PR_2")
        self.assertEqual(calls, 2)

    def test_provider_failure_does_not_echo_cli_stderr(self) -> None:
        def runner(arguments: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
            del kwargs
            return subprocess.CompletedProcess(arguments, 1, "", "sensitive provider stderr")

        transport = GitHubCliTransport(
            command_runner=runner,
            binary_resolver=lambda name: f"/usr/bin/{name}",
        )
        with self.assertRaisesRegex(AdapterRetryableError, "GitHub request failed") as raised:
            transport.create("issue.create", "/repos/owner/repo/issues", {"title": "x"})
        self.assertNotIn("sensitive", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
