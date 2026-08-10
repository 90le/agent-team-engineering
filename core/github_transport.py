"""Explicit GitHub CLI transport for the bounded reference adapter.

This module is never loaded by discovery. The operator must select GitHub mode,
enable provider writes, and inject this transport into ``GitHubReferenceAdapter``.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from typing import Any, Callable

from core.adapters import AdapterContractError, AdapterPermanentError, AdapterRetryableError
from core.json_support import loads_strict

MAX_GITHUB_RESPONSE_BYTES = 5_000_000


class GitHubCliTransport:
    """Use an existing ``gh`` login without exposing credentials to task agents."""

    def __init__(
        self,
        *,
        command_runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
        binary_resolver: Callable[[str], str | None] = shutil.which,
    ) -> None:
        binary = binary_resolver("gh")
        if not binary:
            raise AdapterPermanentError("GitHub CLI is unavailable")
        self.binary = binary
        self.command_runner = command_runner

    def _api(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
    ) -> Any:
        arguments = [
            self.binary,
            "api",
            "--method",
            method,
            "-H",
            "Accept: application/vnd.github+json",
            "-H",
            "X-GitHub-Api-Version: 2022-11-28",
        ]
        arguments.append(path)
        input_value: str | None = None
        if payload is not None:
            arguments.extend(["--input", "-"])
            input_value = json.dumps(
                payload,
                allow_nan=False,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        environment = os.environ.copy()
        environment.update({"GH_PAGER": "cat", "NO_COLOR": "1"})
        try:
            completed = self.command_runner(
                arguments,
                input=input_value,
                text=True,
                capture_output=True,
                timeout=60,
                check=False,
                env=environment,
            )
        except subprocess.TimeoutExpired as exc:
            raise AdapterRetryableError("GitHub request timed out") from exc
        if completed.returncode != 0:
            raise AdapterRetryableError("GitHub request failed")
        encoded = completed.stdout.encode("utf-8")
        if len(encoded) > MAX_GITHUB_RESPONSE_BYTES:
            raise AdapterContractError("GitHub response exceeds 5 MiB")
        try:
            return loads_strict(completed.stdout)
        except ValueError as exc:
            raise AdapterContractError("GitHub response is not strict JSON") from exc

    @staticmethod
    def _stable_response(value: Any) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise AdapterContractError("GitHub create response is not an object")
        html_url = value.get("html_url")
        request_id = value.get("node_id", value.get("id"))
        if not isinstance(html_url, str) or not html_url or request_id is None:
            raise AdapterContractError("GitHub create response lacks stable identity")
        return {"html_url": html_url, "request_id": str(request_id)}

    def create(
        self,
        operation: str,
        path: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        del operation
        return self._stable_response(self._api("POST", path, payload))

    def find_by_marker(
        self,
        operation: str,
        repository: str,
        marker: str,
    ) -> dict[str, Any] | None:
        if operation == "issue.create":
            path = f"/repos/{repository}/issues?state=all&per_page=100"
        elif operation == "pull-request.create":
            path = f"/repos/{repository}/pulls?state=all&per_page=100"
        else:
            raise AdapterPermanentError("unsupported GitHub reconciliation operation")
        for page_number in range(1, 101):
            page = self._api("GET", f"{path}&page={page_number}")
            if not isinstance(page, list):
                raise AdapterContractError("GitHub reconciliation response is not a list")
            for record in page:
                if not isinstance(record, dict) or marker not in str(record.get("body", "")):
                    continue
                return self._stable_response(record)
            if len(page) < 100:
                return None
        raise AdapterContractError("GitHub reconciliation exceeded 100 bounded pages")
