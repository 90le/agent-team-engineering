from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from core.contract_migration import MigrationError, migrate_work_item_v1
from core.contracts import (
    CONTRACT_SCHEMAS,
    ContractViolation,
    approval_scope_digest,
    canonical_json,
    digest_value,
    evidence_bundle_digest,
    load_contract_file,
    plan_revision_digest,
    require_contract,
    validate_contract,
)

ROOT = Path(__file__).resolve().parents[1]
VALID = ROOT / "examples/v08-contracts/valid"
INVALID = ROOT / "examples/v08-contracts/invalid/cases.json"

EXAMPLES = {
    "team_spec": "team-spec.json",
    "role_contract": "role-contract.json",
    "workflow_spec": "workflow-spec.json",
    "work_item": "work-item.json",
    "plan_revision": "plan-revision.json",
    "approval_grant": "approval-grant.json",
    "run": "run.json",
    "evidence_bundle": "evidence-bundle.json",
    "adapter_descriptor": "adapter-descriptor.json",
    "command_envelope": "command-envelope.json",
    "event_envelope": "event-envelope.json",
}


def _set_pointer(document: object, pointer: str, value: object) -> None:
    parts = [part.replace("~1", "/").replace("~0", "~") for part in pointer.split("/")[1:]]
    target = document
    for part in parts[:-1]:
        target = target[int(part)] if isinstance(target, list) else target[part]  # type: ignore[index]
    final = parts[-1]
    if isinstance(target, list):
        target[int(final)] = value
    else:
        target[final] = value  # type: ignore[index]


class V08ContractTests(unittest.TestCase):
    def _load(self, name: str) -> dict[str, object]:
        return json.loads((VALID / EXAMPLES[name]).read_text(encoding="utf-8"))

    def test_every_declared_contract_has_a_valid_portable_example(self) -> None:
        self.assertEqual(set(CONTRACT_SCHEMAS), set(EXAMPLES))
        for contract, filename in sorted(EXAMPLES.items()):
            with self.subTest(contract=contract):
                document = load_contract_file(contract, VALID / filename)
                self.assertEqual(validate_contract(contract, document), [])

    def test_machine_registry_matches_code_and_schema_ids(self) -> None:
        registry = json.loads((ROOT / "contracts/core-contracts.json").read_text(encoding="utf-8"))
        entries = {entry["name"]: entry for entry in registry["contracts"]}
        self.assertEqual(set(entries), set(CONTRACT_SCHEMAS))
        self.assertEqual(registry["unknown_field_policy"], "reject")
        self.assertFalse(registry["compatibility"]["automatic_runtime_download"])
        for name, relative in sorted(CONTRACT_SCHEMAS.items()):
            with self.subTest(contract=name):
                self.assertEqual(entries[name]["path"], relative)
                schema = json.loads((ROOT / relative).read_text(encoding="utf-8"))
                self.assertEqual(entries[name]["schema_id"], schema["$id"])

    def test_negative_example_mutations_fail_at_the_declared_boundary(self) -> None:
        suite = json.loads(INVALID.read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(suite["cases"]), len(EXAMPLES))
        for case in suite["cases"]:
            with self.subTest(case=case["id"]):
                base = (INVALID.parent / case["base"]).resolve()
                document = json.loads(base.read_text(encoding="utf-8"))
                _set_pointer(document, case["path"], case["value"])
                issues = validate_contract(case["contract"], document)
                self.assertTrue(issues)
                self.assertIn(case["expected_path"], {issue.path for issue in issues})

    def test_canonical_digests_bind_content_and_ignore_key_order(self) -> None:
        plan = self._load("plan_revision")
        self.assertEqual(plan_revision_digest(plan), plan["plan_digest"])
        reordered = dict(reversed(list(plan.items())))
        self.assertEqual(plan_revision_digest(reordered), plan["plan_digest"])
        self.assertEqual(canonical_json({"b": 2, "a": 1}), '{"a":1,"b":2}')

        approval = self._load("approval_grant")
        self.assertEqual(approval_scope_digest(approval), approval["scope_digest"])
        evidence = self._load("evidence_bundle")
        self.assertEqual(evidence_bundle_digest(evidence), evidence["bundle_digest"])

    def test_unknown_contract_versions_and_fields_fail_closed(self) -> None:
        team = self._load("team_spec")
        team["schema_version"] = "1.1.0"
        team["paperclip_company_id"] = "not-core"
        with self.assertRaises(ContractViolation):
            require_contract("team_spec", team)
        with self.assertRaises(KeyError):
            validate_contract("paperclip_company", {})

    def test_core_schemas_do_not_require_known_platform_names(self) -> None:
        combined = "\n".join(
            (ROOT / relative).read_text(encoding="utf-8").lower()
            for relative in CONTRACT_SCHEMAS.values()
        )
        for vendor in ("paperclip", "openhands", "openclaw", "github", "codex", "claude"):
            with self.subTest(vendor=vendor):
                self.assertNotIn(vendor, combined)

    def test_work_item_v1_migration_is_one_way_and_deterministic(self) -> None:
        source = {
            "id": "work-legacy-1",
            "source_event_id": "legacy-event-1",
            "title": "Legacy request",
            "summary": "Preserve portable intake facts.",
            "risk": "MEDIUM",
            "state": "SPEC_READY",
            "revision": 4,
            "untrusted_directive_detected": False,
            "audit": [
                {
                    "timestamp": "2026-08-10T01:00:00Z",
                    "action": "create",
                }
            ],
        }
        original = copy.deepcopy(source)
        first = migrate_work_item_v1(source, repository_candidates=("repo.example",))
        second = migrate_work_item_v1(source, repository_candidates=("repo.example",))
        self.assertEqual(source, original)
        self.assertEqual(first.document, second.document)
        self.assertEqual(first.document["state"], "PLANNED")
        self.assertEqual(first.document["normalized"]["target_repository_candidates"], ["repo.example"])
        self.assertEqual(validate_contract("work_item", first.document), [])

    def test_migration_never_carries_post_draft_or_legacy_approval_authority(self) -> None:
        source = {
            "id": "work-legacy-2",
            "source_event_id": "legacy-event-2",
            "title": "Already deployed",
            "summary": "This state must not cross the v0.8 boundary.",
            "risk": "HIGH",
            "state": "DEPLOYED",
            "revision": 8,
            "audit": [{"timestamp": "2026-08-10T01:00:00Z"}],
            "production_approved_by": "legacy-owner",
        }
        with self.assertRaisesRegex(MigrationError, "exceeds the v0.8"):
            migrate_work_item_v1(source)

    def test_digest_rejects_non_json_numbers(self) -> None:
        with self.assertRaises(ValueError):
            digest_value({"cost": float("nan")})


if __name__ == "__main__":
    unittest.main()
