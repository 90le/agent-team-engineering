"""Strict JSON decoding helpers for authority and boundary documents."""

from __future__ import annotations

import json
from typing import Any


class StrictJSONError(ValueError):
    pass


def _reject_constant(value: str) -> None:
    raise StrictJSONError(f"non-finite number is not valid JSON: {value}")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, child in pairs:
        if key in value:
            raise StrictJSONError(f"duplicate JSON object key: {key}")
        value[key] = child
    return value


def loads_strict(content: str | bytes | bytearray) -> Any:
    """Decode RFC-compatible JSON and reject duplicate object keys."""

    return json.loads(
        content,
        object_pairs_hook=_unique_object,
        parse_constant=_reject_constant,
    )
