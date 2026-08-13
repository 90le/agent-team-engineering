"""Small dependency-free validator for the JSON Schema subset used by the factory."""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class SchemaIssue:
    path: str
    message: str


def _is_type(value: Any, expected: str) -> bool:
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return (
            isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
        )
    if expected == "null":
        return value is None
    return False


def _json_identity(value: Any) -> str:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def validate_schema(value: Any, schema: dict[str, Any], path: str = "$") -> list[SchemaIssue]:
    """Validate the deliberately small schema vocabulary used by this repository.

    This is not presented as a complete JSON Schema implementation. Keeping the
    supported vocabulary explicit prevents a document from appearing validated
    when it uses keywords the portable runtime silently ignores.
    """

    supported = {
        "$schema",
        "$id",
        "title",
        "description",
        "type",
        "required",
        "properties",
        "additionalProperties",
        "items",
        "prefixItems",
        "enum",
        "const",
        "pattern",
        "minLength",
        "maxLength",
        "minItems",
        "maxItems",
        "uniqueItems",
        "minimum",
        "maximum",
        "format",
        "oneOf",
        "not",
    }
    issues = [
        SchemaIssue(path, f"unsupported schema keyword: {key}")
        for key in schema
        if key not in supported
    ]

    one_of = schema.get("oneOf")
    if one_of is not None:
        if not isinstance(one_of, list) or not one_of or not all(
            isinstance(candidate, dict) for candidate in one_of
        ):
            issues.append(SchemaIssue(path, "oneOf must contain schema objects"))
        else:
            matches = sum(
                not validate_schema(value, candidate, path) for candidate in one_of
            )
            if matches != 1:
                issues.append(
                    SchemaIssue(path, f"must match exactly one oneOf branch; matched {matches}")
                )

    forbidden = schema.get("not")
    if forbidden is not None:
        if not isinstance(forbidden, dict):
            issues.append(SchemaIssue(path, "not must contain a schema object"))
        elif not validate_schema(value, forbidden, path):
            issues.append(SchemaIssue(path, "must not match the forbidden schema"))

    expected = schema.get("type")
    if expected is not None:
        expected_types = [expected] if isinstance(expected, str) else list(expected)
        if not any(_is_type(value, candidate) for candidate in expected_types):
            return issues + [SchemaIssue(path, f"expected type {' or '.join(expected_types)}")]

    if "const" in schema and value != schema["const"]:
        issues.append(SchemaIssue(path, f"must equal {schema['const']!r}"))
    if "enum" in schema and value not in schema["enum"]:
        issues.append(SchemaIssue(path, f"must be one of {schema['enum']!r}"))

    if isinstance(value, str):
        if len(value) < int(schema.get("minLength", 0)):
            issues.append(SchemaIssue(path, "string is shorter than minLength"))
        if "maxLength" in schema and len(value) > int(schema["maxLength"]):
            issues.append(SchemaIssue(path, "string is longer than maxLength"))
        pattern = schema.get("pattern")
        if pattern and re.search(str(pattern), value) is None:
            issues.append(SchemaIssue(path, f"does not match pattern {pattern!r}"))
        value_format = schema.get("format")
        if value_format == "date-time":
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                if parsed.tzinfo is None:
                    raise ValueError("timezone is required")
            except ValueError:
                issues.append(SchemaIssue(path, "must be an RFC 3339 date-time with timezone"))
        elif value_format is not None:
            issues.append(SchemaIssue(path, f"unsupported string format: {value_format}"))

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            issues.append(SchemaIssue(path, f"must be >= {schema['minimum']}"))
        if "maximum" in schema and value > schema["maximum"]:
            issues.append(SchemaIssue(path, f"must be <= {schema['maximum']}"))

    if isinstance(value, list):
        if len(value) < int(schema.get("minItems", 0)):
            issues.append(SchemaIssue(path, "array is shorter than minItems"))
        if "maxItems" in schema and len(value) > int(schema["maxItems"]):
            issues.append(SchemaIssue(path, "array is longer than maxItems"))
        if schema.get("uniqueItems"):
            try:
                identities = [_json_identity(item) for item in value]
            except (TypeError, ValueError):
                issues.append(SchemaIssue(path, "array contains a non-JSON value"))
            else:
                if len(identities) != len(set(identities)):
                    issues.append(SchemaIssue(path, "array items must be unique"))
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for index, item in enumerate(value):
                issues.extend(validate_schema(item, item_schema, f"{path}[{index}]"))
        prefix_schemas = schema.get("prefixItems")
        if prefix_schemas is not None:
            if not isinstance(prefix_schemas, list) or not all(
                isinstance(candidate, dict) for candidate in prefix_schemas
            ):
                issues.append(SchemaIssue(path, "prefixItems must contain schema objects"))
            else:
                for index, child_schema in enumerate(prefix_schemas[: len(value)]):
                    issues.extend(
                        validate_schema(value[index], child_schema, f"{path}[{index}]")
                    )

    if isinstance(value, dict):
        required = schema.get("required", [])
        for key in required:
            if key not in value:
                issues.append(SchemaIssue(f"{path}.{key}", "required property is missing"))
        properties = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            for key in value:
                if key not in properties:
                    issues.append(
                        SchemaIssue(f"{path}.{key}", "additional property is not allowed")
                    )
        for key, child_schema in properties.items():
            if key in value:
                issues.extend(validate_schema(value[key], child_schema, f"{path}.{key}"))

    return issues
