from __future__ import annotations

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

    def test_unknown_schema_keyword_is_not_silently_ignored(self) -> None:
        issues = validate_schema("value", {"type": "string", "format": "uri"})
        self.assertEqual(issues[0].message, "unsupported schema keyword: format")

    def test_boolean_does_not_satisfy_integer(self) -> None:
        issues = validate_schema(True, {"type": "integer"})
        self.assertTrue(issues)


if __name__ == "__main__":
    unittest.main()
