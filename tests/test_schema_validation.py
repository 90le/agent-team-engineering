from __future__ import annotations

import math
import unittest

from core.schema_validation import validate_schema


class PortableSchemaValidationTests(unittest.TestCase):
    def test_nested_objects_and_arrays_are_validated(self) -> None:
        schema = {
            "type": "object",
            "additionalProperties": False,
            "required": ["name", "items"],
            "properties": {
                "name": {"type": "string", "pattern": "^[a-z]+$"},
                "items": {
                    "type": "array",
                    "minItems": 1,
                    "uniqueItems": True,
                    "items": {"type": "integer", "minimum": 1},
                },
            },
        }
        self.assertEqual(validate_schema({"name": "valid", "items": [1, 2]}, schema), [])
        issues = validate_schema({"name": "INVALID", "items": [0, 0], "extra": True}, schema)
        messages = {issue.message for issue in issues}
        self.assertTrue(any("pattern" in message for message in messages))
        self.assertIn("array items must be unique", messages)
        self.assertIn("additional property is not allowed", messages)

    def test_unknown_string_format_is_not_silently_ignored(self) -> None:
        issues = validate_schema("value", {"type": "string", "format": "uri"})
        self.assertEqual(issues[0].message, "unsupported string format: uri")

    def test_date_time_and_maximum_string_length_are_enforced(self) -> None:
        schema = {"type": "string", "format": "date-time", "maxLength": 25}
        self.assertEqual(validate_schema("2026-08-10T00:00:00Z", schema), [])
        self.assertTrue(validate_schema("2026-08-10 00:00:00", schema))
        self.assertTrue(validate_schema("2026-08-10T00:00:00.000000+08:00", schema))

    def test_boolean_does_not_satisfy_integer(self) -> None:
        issues = validate_schema(True, {"type": "integer"})
        self.assertTrue(issues)

    def test_non_finite_values_are_not_json_numbers(self) -> None:
        for value in (math.nan, math.inf, -math.inf):
            with self.subTest(value=value):
                issues = validate_schema(value, {"type": "number"})
                self.assertEqual(issues[0].message, "expected type number")

        issues = validate_schema(
            [{"value": math.nan}],
            {"type": "array", "uniqueItems": True},
        )
        self.assertIn("array contains a non-JSON value", [issue.message for issue in issues])

    def test_one_of_and_not_are_enforced(self) -> None:
        schema = {
            "type": "object",
            "oneOf": [
                {
                    "required": ["version"],
                    "properties": {"version": {"const": "1.0"}},
                    "not": {"required": ["binding"]},
                },
                {
                    "required": ["version", "binding"],
                    "properties": {"version": {"const": "1.1"}},
                },
            ],
        }
        self.assertEqual(validate_schema({"version": "1.0"}, schema), [])
        self.assertEqual(
            validate_schema({"version": "1.1", "binding": None}, schema), []
        )
        self.assertTrue(validate_schema({"version": "1.0", "binding": None}, schema))
        self.assertTrue(validate_schema({"version": "1.1"}, schema))


if __name__ == "__main__":
    unittest.main()
