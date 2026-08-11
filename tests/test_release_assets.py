from __future__ import annotations

import copy
import unittest

from tools.release_audit import (
    ReleaseAuditError,
    validate_release_assets,
    validate_scm_evidence_documents,
)

REPOSITORY = "90le/agent-team-v08-conformance-private"


def _profile(gate: str = "GRANTED_DEDICATED_TEST_ONLY") -> dict:
    return {
        "authority_boundaries": {
            "gate_c_external_write": gate,
            "production_integrations": False,
        }
    }


def _report(*, created: bool, run_id: int, scope_character: str) -> dict:
    objects = {
        "issue": (f"https://github.com/{REPOSITORY}/issues/1", "ISSUE_1"),
        "branch": (
            f"https://api.github.com/repos/{REPOSITORY}/git/refs/heads/agent-team/test",
            "REF_1",
        ),
        "commit": (f"https://github.com/{REPOSITORY}/commit/{'e' * 40}", "COMMIT_1"),
        "draft_pull_request": (f"https://github.com/{REPOSITORY}/pull/1", "PR_1"),
    }
    report = {
        "schema_version": "1.0.0",
        "repository": REPOSITORY,
        "repository_id": "conformance.github.v08",
        "repository_private": True,
        "base_commit": "a" * 40,
        "framework_commit": "f" * 40,
        "plan_digest": "sha256:" + "b" * 64,
        "approval_scope_digest": "sha256:" + scope_character * 64,
        "actor_id": "github:68719118",
        "identity_provider": "github.actions",
        "identity_ref": f"github-actions://{REPOSITORY}/runs/{run_id}/attempts/1",
        "merge_performed": False,
        "deployment_performed": False,
    }
    for key, (external_ref, provider_id) in objects.items():
        report[key] = {
            "external_ref": external_ref,
            "provider_id": provider_id,
            "created": created,
        }
    return report


class ReleaseAssetTests(unittest.TestCase):
    def test_versions_sbom_license_and_provenance_are_consistent(self) -> None:
        report = validate_release_assets()
        self.assertEqual(report["version"], "0.8.0")
        self.assertEqual(report["spdx_packages"], 1)
        self.assertGreaterEqual(report["evaluated_upstreams"], 6)

    def test_live_scm_evidence_requires_one_creation_and_one_exact_replay(self) -> None:
        first = _report(created=True, run_id=101, scope_character="c")
        replay = _report(created=False, run_id=102, scope_character="d")
        result = validate_scm_evidence_documents(_profile(), first, replay)
        self.assertEqual(result["scm_evidence_objects"], 4)
        self.assertEqual(result["scm_evidence_framework_commit"], "f" * 40)

    def test_live_scm_evidence_rejects_pending_gate_or_identity_drift(self) -> None:
        first = _report(created=True, run_id=101, scope_character="c")
        replay = _report(created=False, run_id=102, scope_character="d")
        with self.assertRaises(ReleaseAuditError):
            validate_scm_evidence_documents(
                _profile("AUTHORIZED_EVIDENCE_PENDING"), first, replay
            )

        wrong_replay = copy.deepcopy(replay)
        wrong_replay["commit"]["provider_id"] = "DIFFERENT_COMMIT"
        with self.assertRaises(ReleaseAuditError):
            validate_scm_evidence_documents(_profile(), first, wrong_replay)


if __name__ == "__main__":
    unittest.main()
