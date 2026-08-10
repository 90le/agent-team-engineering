"""Shared high-confidence credential detection and redaction helpers."""

from __future__ import annotations

import re
from typing import Any

CREDENTIAL_PATTERNS = (
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bAKIA[A-Z0-9]{16}\b"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{32,}\b"),
)

FORBIDDEN_SECRET_KEYS = {
    "access_key",
    "api_key",
    "client_secret",
    "password",
    "private_key",
    "secret_value",
    "token",
}


def is_secret_key(key: str) -> bool:
    normalized = key.casefold().replace("-", "_")
    return normalized in FORBIDDEN_SECRET_KEYS or any(
        normalized.endswith(suffix)
        for suffix in (
            "_access_key",
            "_api_key",
            "_client_secret",
            "_password",
            "_private_key",
            "_secret",
            "_token",
        )
    )


def contains_credential_like(value: str) -> bool:
    return any(pattern.search(value) for pattern in CREDENTIAL_PATTERNS)


def redact_credential_like(value: str) -> str:
    redacted = value
    for pattern in CREDENTIAL_PATTERNS:
        redacted = pattern.sub("[REDACTED_CREDENTIAL]", redacted)
    return redacted


def find_inline_secret(value: Any, path: str = "$") -> str | None:
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if is_secret_key(str(key)):
                return child_path
            found = find_inline_secret(child, child_path)
            if found:
                return found
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found = find_inline_secret(child, f"{path}[{index}]")
            if found:
                return found
    elif isinstance(value, str) and contains_credential_like(value):
        return path
    return None
