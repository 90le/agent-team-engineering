from __future__ import annotations

import copy
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from tools.release_audit import (
    EXTERNAL_EVIDENCE_PROTECTED_PATHS,
    SCM_EVIDENCE_PATHS,
    SCM_PROFILE_PATH,
    ReleaseAuditError,
    _validate_release_identity,
    _workflow_action_pins,
    validate_release_assets,
    validate_scm_evidence_documents,
)
from tools.github_scm_conformance import (
    SCM_REPOSITORY,
    SCM_REPOSITORY_ID,
    SCM_WORKFLOW_REF,
    build_approval,
    build_change,
    build_plan,
    build_report,
)

REPOSITORY = SCM_REPOSITORY
ROOT = Path(__file__).resolve().parents[1]


def _profile(gate: str = "GRANTED_DEDICATED_TEST_ONLY") -> dict:
    return {
        "status": "PRE_RELEASE",
        "local_gates": {
            "external_scm": {"status": "PASS", "live_runs": 2}
        },
        "authority_boundaries": {
            "external_scm_write_scope": gate,
            "production_accounts_used": False,
            "automatic_merge": False,
            "automatic_deploy": False,
            "independent_writer_execution": False,
            "dedicated_scm_identity_used": True,
            "ephemeral_scm_token_used": True,
        }
    }


def _report(*, created: bool, run_id: int) -> dict:
    base_commit = "a" * 40
    framework_commit = "f" * 40
    plan = build_plan(
        repository_id=SCM_REPOSITORY_ID,
        base_commit=base_commit,
        framework_commit=framework_commit,
    )
    change = build_change(plan, REPOSITORY)
    signature_ref = f"github-actions://{REPOSITORY}/runs/{run_id}/attempts/1"
    verified = {
        "actor_id": "github:68719118",
        "identity_provider": "github.actions",
        "signature_ref": signature_ref,
        "repository_ref": "refs/heads/main",
        "workflow_ref": SCM_WORKFLOW_REF,
        "workflow_sha": base_commit,
        "framework_repository": "90le/agent-team-engineering",
        "run_id": str(run_id),
        "run_attempt": "1",
    }
    environment = {
        "GITHUB_RUN_ID": str(run_id),
        "GITHUB_RUN_ATTEMPT": "1",
        "GITHUB_REPOSITORY": REPOSITORY,
    }
    approval = build_approval(
        plan,
        verified,
        environment,
        datetime(2026, 8, 11, 8, run_id % 10, tzinfo=timezone.utc),
    )
    objects = {
        "issue": ("issue", f"https://github.com/{REPOSITORY}/issues/1", "I_1"),
        "branch": (
            "branch",
            f"https://api.github.com/repos/{REPOSITORY}/git/refs/heads/{change['proposal_branch']}",
            "REF_1",
        ),
        "commit": (
            "commit",
            f"https://api.github.com/repos/{REPOSITORY}/git/commits/{'e' * 40}",
            "e" * 40,
        ),
        "draft_pull_request": (
            "draft_pull_request",
            f"https://github.com/{REPOSITORY}/pull/1",
            "PR_1",
        ),
    }
    execution = {
        "schema_version": "1.1.0",
        "repository": REPOSITORY,
        "repository_id": SCM_REPOSITORY_ID,
        "base_commit": base_commit,
        "plan_digest": plan["plan_digest"],
        "approval_scope_digest": approval["scope_digest"],
        "actor_id": "github:68719118",
        "identity_provider": "github.actions",
        "identity_ref": signature_ref,
        "merge_performed": False,
        "deployment_performed": False,
    }
    for key, (object_type, external_ref, provider_id) in objects.items():
        execution[key] = {
            "object_type": object_type,
            "external_ref": external_ref,
            "provider_id": provider_id,
            "created": created,
        }
    return build_report(
        execution,
        plan=plan,
        approval=approval,
        change=change,
        verified=verified,
        framework_commit=framework_commit,
    )


class ReleaseAssetTests(unittest.TestCase):
    def test_release_authorizing_scm_documents_are_protected(self) -> None:
        self.assertTrue(
            set(SCM_EVIDENCE_PATHS) | {SCM_PROFILE_PATH}
            <= EXTERNAL_EVIDENCE_PROTECTED_PATHS
        )

    def test_versions_sbom_license_and_provenance_are_consistent(self) -> None:
        report = validate_release_assets()
        self.assertEqual(report["version"], "1.0.0")
        self.assertEqual(report["spdx_packages"], 1)
        self.assertGreaterEqual(report["evaluated_upstreams"], 8)
        self.assertEqual(report["host_claims"], 6)

    def test_candidate_schema_requires_each_catalog_host_exactly_once(self) -> None:
        from core.json_support import loads_strict
        from core.schema_validation import validate_schema

        document = loads_strict(
            (ROOT / "acceptance/v10-host-native-conformance.json").read_text(
                encoding="utf-8"
            )
        )
        schema = loads_strict(
            (ROOT / "schemas/v10-release-candidate-conformance.schema.json").read_text(
                encoding="utf-8"
            )
        )
        altered = copy.deepcopy(document)
        altered["hosts"][1]["host_id"] = "codex"
        altered["hosts"][1]["evidence_scope"] = "different whole object"
        self.assertTrue(validate_schema(altered, schema))

        for gate, fields in {
            "isolated_hosts": {"load_tests": 0, "hosts": []},
            "cold_start": {"runs": 0},
            "release_smoke": {"runs": 0},
            "external_scm": {"live_runs": 0, "evidence_files": []},
        }.items():
            altered = copy.deepcopy(document)
            altered["local_gates"][gate].update(fields)
            self.assertTrue(
                validate_schema(altered, schema),
                f"PASS gate accepted empty evidence: {gate}",
            )

    def test_live_scm_evidence_requires_one_creation_and_one_exact_replay(self) -> None:
        first = _report(created=True, run_id=101)
        replay = _report(created=False, run_id=102)
        result = validate_scm_evidence_documents(_profile(), first, replay)
        self.assertEqual(result["scm_evidence_objects"], 4)
        self.assertEqual(result["scm_evidence_framework_commit"], "f" * 40)

    def test_live_scm_evidence_rejects_pending_gate_or_identity_drift(self) -> None:
        first = _report(created=True, run_id=101)
        replay = _report(created=False, run_id=102)
        with self.assertRaises(ReleaseAuditError):
            validate_scm_evidence_documents(
                _profile("NONE"), first, replay
            )

        wrong_replay = copy.deepcopy(replay)
        wrong_replay["commit"]["provider_id"] = "DIFFERENT_COMMIT"
        with self.assertRaises(ReleaseAuditError):
            validate_scm_evidence_documents(_profile(), first, wrong_replay)

        # Exercise coherent-forgery and type-confusion attacks in the same evidence gate.
        first = _report(created=True, run_id=101)
        replay = _report(created=False, run_id=102)

        attacks: list[tuple[str, dict, dict]] = []

        forged_plan_first = copy.deepcopy(first)
        forged_plan_replay = copy.deepcopy(replay)
        for report in (forged_plan_first, forged_plan_replay):
            report["plan_digest"] = "sha256:" + "9" * 64
        attacks.append(("same forged plan digest", forged_plan_first, forged_plan_replay))

        forged_scope_first = copy.deepcopy(first)
        forged_scope_replay = copy.deepcopy(replay)
        forged_scope_first["approval_scope_digest"] = "sha256:" + "8" * 64
        forged_scope_replay["approval_scope_digest"] = "sha256:" + "7" * 64
        attacks.append(("forged approval scopes", forged_scope_first, forged_scope_replay))

        swapped_first = copy.deepcopy(first)
        swapped_first["issue"], swapped_first["draft_pull_request"] = (
            swapped_first["draft_pull_request"],
            swapped_first["issue"],
        )
        attacks.append(("issue and pull request swap", swapped_first, replay))

        forged_run = copy.deepcopy(replay)
        forged_run["workflow"]["run_id"] = "999"
        forged_run["workflow"]["run_url"] = f"https://github.com/{REPOSITORY}/actions/runs/999"
        forged_run["identity_ref"] = f"github-actions://{REPOSITORY}/runs/999/attempts/1"
        forged_run["approval_id"] = "approval-github-run-999-attempt-1"
        forged_run["approval_nonce"] = "github-run-999-attempt-1-nonce"
        forged_run["approval_evidence_ref"] = f"github-actions://{REPOSITORY}/runs/999"
        attacks.append(("coherently rewritten run references", first, forged_run))

        old_identity = copy.deepcopy(first)
        old_identity["schema_version"] = "1.0.0"
        old_identity["repository_id"] = "repo.conformance.github.v08"
        attacks.append(("v0.8 schema and identity", old_identity, replay))

        workflow_drift = copy.deepcopy(first)
        workflow_drift["workflow"]["sha"] = "b" * 40
        attacks.append(("workflow/base commit drift", workflow_drift, replay))

        missing_topology = copy.deepcopy(first)
        missing_topology.pop("writer_topology")
        attacks.append(("omitted explicit topology", missing_topology, replay))

        forged_change_first = copy.deepcopy(first)
        forged_change_replay = copy.deepcopy(replay)
        for report in (forged_change_first, forged_change_replay):
            report["change_digest"] = "sha256:" + "6" * 64
        attacks.append(("same forged change digest", forged_change_first, forged_change_replay))

        for label, attacked_first, attacked_replay in attacks:
            with self.subTest(attack=label), self.assertRaises(ReleaseAuditError):
                validate_scm_evidence_documents(
                    _profile(), attacked_first, attacked_replay
                )

    def test_release_identity_rejects_sbom_provenance_and_action_pin_drift(self) -> None:
        sbom = json.loads(
            (ROOT / "sbom/agent-team-engineering.spdx.json").read_text(encoding="utf-8")
        )
        provenance = json.loads(
            (ROOT / "supply-chain/source-provenance.json").read_text(encoding="utf-8")
        )
        _validate_release_identity(sbom, provenance, "1.0.0")

        wrong_sbom = copy.deepcopy(sbom)
        wrong_sbom["name"] = "wrong"
        with self.assertRaises(ReleaseAuditError):
            _validate_release_identity(wrong_sbom, provenance, "1.0.0")

        for field, value in (
            ("project", "other/project"),
            ("release_commit_binding", "mutable-branch"),
            ("github_actions", []),
            ("claims", {}),
        ):
            wrong_provenance = copy.deepcopy(provenance)
            wrong_provenance[field] = value
            with self.subTest(field=field), self.assertRaises(ReleaseAuditError):
                _validate_release_identity(sbom, wrong_provenance, "1.0.0")

    def test_release_identity_scans_yaml_workflows_too(self) -> None:
        sbom = json.loads(
            (ROOT / "sbom/agent-team-engineering.spdx.json").read_text(encoding="utf-8")
        )
        provenance = json.loads(
            (ROOT / "supply-chain/source-provenance.json").read_text(encoding="utf-8")
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workflows = root / ".github/workflows"
            workflows.mkdir(parents=True)
            example = root / "examples/github-scm-conformance"
            example.mkdir(parents=True)
            (example / "workflow.yml").write_text("jobs: {}\n", encoding="utf-8")
            (workflows / "unrecorded.yaml").write_text(
                "jobs:\n  audit:\n    steps:\n      - uses: actions/cache@"
                + "1" * 40
                + "\n",
                encoding="utf-8",
            )
            with mock.patch("tools.release_audit.ROOT", root), self.assertRaises(
                ReleaseAuditError
            ):
                _validate_release_identity(sbom, provenance, "1.0.0")

            for token in (
                "third-party/action@" + "1" * 40,
                "./local-action",
                "docker://example.invalid/action:latest",
                "Actions/checkout@" + "3d3c42e5aac5ba805825da76410c181273ba90b1",
                "actions/checkout@main",
            ):
                candidate = workflows / "candidate.yml"
                candidate.write_text(
                    f"jobs:\n  audit:\n    steps:\n      - uses: {token}\n",
                    encoding="utf-8",
                )
                with self.subTest(token=token), self.assertRaises(ReleaseAuditError):
                    _workflow_action_pins(candidate)

            flow = workflows / "flow.yml"
            flow.write_text(
                "jobs:\n  audit:\n    steps:\n      - { uses: actions/checkout@"
                + "3d3c42e5aac5ba805825da76410c181273ba90b1"
                + " }\n",
                encoding="utf-8",
            )
            with self.assertRaises(ReleaseAuditError):
                _workflow_action_pins(flow)

            quoted = workflows / "quoted.yml"
            quoted.write_text(
                "jobs:\n  audit:\n    steps:\n      - \"uses\": actions/checkout@"
                + "3d3c42e5aac5ba805825da76410c181273ba90b1"
                + "\n",
                encoding="utf-8",
            )
            with self.assertRaises(ReleaseAuditError):
                _workflow_action_pins(quoted)

            explicit = workflows / "explicit.yml"
            explicit.write_text(
                "jobs:\n  audit:\n    steps:\n      - ? uses\n        : actions/checkout@"
                + "3d3c42e5aac5ba805825da76410c181273ba90b1"
                + "\n",
                encoding="utf-8",
            )
            with self.assertRaises(ReleaseAuditError):
                _workflow_action_pins(explicit)

            escaped = workflows / "escaped.yml"
            escaped.write_text(
                "jobs:\n  audit:\n    steps:\n      - \"\\u0075ses\": actions/checkout@"
                + "3d3c42e5aac5ba805825da76410c181273ba90b1"
                + "\n",
                encoding="utf-8",
            )
            with self.assertRaises(ReleaseAuditError):
                _workflow_action_pins(escaped)


if __name__ == "__main__":
    unittest.main()
