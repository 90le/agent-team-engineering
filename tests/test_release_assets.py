from __future__ import annotations

import unittest

from tools.release_audit import validate_release_assets


class ReleaseAssetTests(unittest.TestCase):
    def test_versions_sbom_license_and_provenance_are_consistent(self) -> None:
        report = validate_release_assets()
        self.assertEqual(report["version"], "0.8.0")
        self.assertEqual(report["spdx_packages"], 1)
        self.assertGreaterEqual(report["evaluated_upstreams"], 6)


if __name__ == "__main__":
    unittest.main()
