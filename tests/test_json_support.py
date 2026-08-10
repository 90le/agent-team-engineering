from __future__ import annotations

import unittest

from core.json_support import StrictJSONError, loads_strict


class StrictJSONTests(unittest.TestCase):
    def test_duplicate_keys_are_rejected(self) -> None:
        with self.assertRaises(StrictJSONError):
            loads_strict('{"authority":"first","authority":"second"}')

    def test_non_finite_numbers_are_rejected(self) -> None:
        for value in ("NaN", "Infinity", "-Infinity"):
            with self.subTest(value=value), self.assertRaises(StrictJSONError):
                loads_strict('{"value":' + value + "}")

    def test_normal_json_is_accepted(self) -> None:
        self.assertEqual(loads_strict('{"value":1,"items":[true,null]}')["value"], 1)


if __name__ == "__main__":
    unittest.main()
