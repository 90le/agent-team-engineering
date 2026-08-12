from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from core.contract_migration import MigrationError, migrate_work_item_v1
from core.contracts import (
    CONTRACT_SCHEMAS,
    PLAN_ACTION_TO_TOPOLOGY_ACTIONS,
    ContractViolation,
    approval_scope_digest,
    canonical_json,
    digest_value,
    evidence_bundle_digest,
    load_contract_file,
    plan_revision_digest,
    require_contract,
    validate_contract,
    validate_writer_authority,
    writer_topology_digest,
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
    "writer_topology": "writer-topology.json",
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

    def test_plan_and_approval_schema_versions_bind_topology_presence(self) -> None:
        for contract in ("plan_revision", "approval_grant"):
            current = self._load(contract)
            schema = json.loads(
                (ROOT / CONTRACT_SCHEMAS[contract]).read_text(encoding="utf-8")
            )
            from core.schema_validation import validate_schema

            self.assertEqual(validate_schema(current, schema), [])

            missing = copy.deepcopy(current)
            missing.pop("writer_topology")
            self.assertTrue(validate_schema(missing, schema))

            legacy = copy.deepcopy(current)
            legacy["$schema"] = legacy["$schema"].replace("1.1.0", "1.0.0")
            legacy["schema_version"] = "1.0.0"
            legacy.pop("writer_topology")
            self.assertEqual(validate_schema(legacy, schema), [])

            forbidden = copy.deepcopy(legacy)
            forbidden["writer_topology"] = None
            self.assertTrue(validate_schema(forbidden, schema))

            mismatched = copy.deepcopy(current)
            mismatched["schema_version"] = "1.0.0"
            self.assertTrue(validate_schema(mismatched, schema))

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

    def test_writer_topology_is_design_only_and_explicitly_degrades_per_host(self) -> None:
        topology = self._load("writer_topology")
        plan = self._load("plan_revision")
        approval = self._load("approval_grant")
        self.assertEqual(writer_topology_digest(topology), topology["topology_digest"])
        self.assertEqual(validate_writer_authority(topology, plan, approval), [])
        self.assertEqual(topology["status"], "DESIGN_ONLY")
        self.assertFalse(topology["default_effects"]["automatic_merge"])
        self.assertFalse(topology["default_effects"]["automatic_release"])
        self.assertFalse(topology["default_effects"]["automatic_deploy"])
        records = {record["host"]: record for record in topology["host_degradation"]}
        self.assertEqual(
            set(records),
            {"claude", "codex", "generic-ai", "hermes", "multica", "openclaw"},
        )
        self.assertTrue(all(not record["topology_enforced"] for record in records.values()))
        self.assertTrue(all(not record["automatic_execution"] for record in records.values()))

        changed = copy.deepcopy(topology)
        changed["writers"][0]["ownership_roots"] = ["apps/admin", "packages/ui"]
        changed["topology_digest"] = writer_topology_digest(changed)
        self.assertEqual(validate_contract("writer_topology", changed), [])
        authority_issues = validate_writer_authority(changed, plan, approval)
        self.assertIn("$.plan.writer_topology", {issue.path for issue in authority_issues})

        # A coherent re-signing cannot swap frontend/backend path authority
        # while preserving the same plan-wide path union.
        cross_writer_plan = copy.deepcopy(plan)
        cross_writer_approval = copy.deepcopy(approval)
        frontend_paths = cross_writer_plan["tasks"][0]["allowed_paths"]
        backend_paths = cross_writer_plan["tasks"][1]["allowed_paths"]
        cross_writer_plan["tasks"][0]["allowed_paths"] = backend_paths
        cross_writer_plan["tasks"][1]["allowed_paths"] = frontend_paths
        cross_writer_plan["plan_digest"] = plan_revision_digest(cross_writer_plan)
        cross_writer_approval["plan_digest"] = cross_writer_plan["plan_digest"]
        cross_writer_approval["scope_digest"] = approval_scope_digest(
            cross_writer_approval
        )
        self.assertEqual(validate_contract("plan_revision", cross_writer_plan), [])
        self.assertEqual(
            validate_contract("approval_grant", cross_writer_approval), []
        )
        cross_writer_issues = validate_writer_authority(
            topology, cross_writer_plan, cross_writer_approval
        )
        self.assertIn(
            "$.plan.tasks[0].allowed_paths[0]",
            {issue.path for issue in cross_writer_issues},
        )

        # Git paths are case-sensitive authority identities. A case-only path
        # change cannot borrow another spelling of an owned root.
        case_changed_plan = copy.deepcopy(plan)
        case_changed_approval = copy.deepcopy(approval)
        case_changed_plan["tasks"][0]["allowed_paths"][0] = "Apps/web/secret"
        case_changed_plan["allowed_paths"][0] = "Apps/web/secret"
        case_changed_plan["plan_digest"] = plan_revision_digest(case_changed_plan)
        case_changed_approval["allowed_paths"] = case_changed_plan["allowed_paths"]
        case_changed_approval["plan_digest"] = case_changed_plan["plan_digest"]
        case_changed_approval["scope_digest"] = approval_scope_digest(
            case_changed_approval
        )
        self.assertEqual(validate_contract("plan_revision", case_changed_plan), [])
        case_issues = validate_writer_authority(
            topology, case_changed_plan, case_changed_approval
        )
        self.assertIn(
            "$.plan.tasks[0].allowed_paths[0]",
            {issue.path for issue in case_issues},
        )
        self.assertIn(
            "$.plan.tasks[1].allowed_paths[0]",
            {issue.path for issue in cross_writer_issues},
        )

    def test_writer_topology_semantic_bypass_matrix_fails_with_recomputed_digest(self) -> None:
        def writer_scope(document: dict) -> None:
            document["writers"][0]["allowed_actions"].append("outside-owned-paths.write")

        def assurance_write(document: dict) -> None:
            document["assurance_roles"][1]["allowed_actions"].extend(
                ["review-own-work", "source.write"]
            )

        def worktree_escape(document: dict) -> None:
            document["writers"][1]["worktree_template"] = (
                ".agent-team/worktrees/{work_item_id}/{writer_id}/.."
            )

        def mutable_base(document: dict) -> None:
            document["repository"]["base_ref"] = "main"

        def approval_without_input(document: dict) -> None:
            document["phases"][0]["requires"] = []

        def phase_reorder(document: dict) -> None:
            document["phases"][1], document["phases"][2] = (
                document["phases"][2],
                document["phases"][1],
            )
            document["phases"][1]["sequence"] = 2
            document["phases"][2]["sequence"] = 3

        def draft_without_evidence(document: dict) -> None:
            document["phases"][-1]["requires"] = []

        def dangerous_final_effect(document: dict) -> None:
            document["phases"][-1]["produces"].extend(
                ["default-branch-merged", "production-deployed", "release-published"]
            )

        def overstated_multica(document: dict) -> None:
            record = next(
                item for item in document["host_degradation"] if item["host"] == "multica"
            )
            record["support_tier"] = "native-install-verified"
            record["projection"] = "native-team-files-no-multiwriter-runtime"

        def fictional_host_only(document: dict) -> None:
            document["host_degradation"] = [
                {
                    "host": "fictional",
                    "support_tier": "portable",
                    "projection": "portable-documents-only",
                    "topology_enforced": False,
                    "automatic_execution": False,
                    "limitations": ["No evidence."],
                }
            ]

        def random_retry_nonce(document: dict) -> None:
            document["recovery"]["idempotency_fields"].append("random_nonce")

        def casefold_ownership_overlap(document: dict) -> None:
            document["writers"][1]["ownership_roots"][0] = "Apps/Web/components"

        def shared_identity(document: dict) -> None:
            document["assurance_roles"][0]["actor_id"] = document["writers"][0][
                "actor_id"
            ]
            document["assurance_roles"][0]["role_ref"] = "role.frontend@1.0.0"

        def reserved_git_ownership(document: dict) -> None:
            document["writers"][0]["ownership_roots"] = [".git"]

        def reserved_governance_ownership(document: dict) -> None:
            document["writers"][0]["ownership_roots"] = [".agent-team"]

        def invalid_git_actor(document: dict) -> None:
            old = document["writers"][0]["actor_id"]
            new = "role.front..end"
            document["writers"][0]["actor_id"] = new
            document["writers"][0]["role_ref"] = new + "@1.0.0"
            for phase in document["phases"]:
                phase["actors"] = [new if actor == old else actor for actor in phase["actors"]]

        def invalid_git_base_label(document: dict) -> None:
            document["repository"]["base_ref"] = "main..evil@" + ("a" * 40)

        def dishonest_host_limitation(document: dict) -> None:
            record = next(
                item for item in document["host_degradation"] if item["host"] == "multica"
            )
            record["limitations"] = [
                "Independent multi-writer runtime is fully enforced and production ready."
            ]

        def nondeterministic_phase_identity(document: dict) -> None:
            document["phases"][2]["phase_id"] = "nondeterministic-integration"

        def weakened_failure_policy(document: dict) -> None:
            for phase in document["phases"]:
                phase["failure_state"] = "CANCELLED"

        def stale_host_catalog_binding(document: dict) -> None:
            document["factory_host_catalog"]["catalog_digest"] = "sha256:" + ("0" * 64)

        def git_lock_actor(document: dict) -> None:
            old = document["writers"][0]["actor_id"]
            new = "role.front.lock"
            document["writers"][0]["actor_id"] = new
            document["writers"][0]["role_ref"] = new + "@1.0.0"
            for phase in document["phases"]:
                phase["actors"] = [new if actor == old else actor for actor in phase["actors"]]

        def windows_absolute_root(document: dict) -> None:
            document["writers"][0]["ownership_roots"] = ["C:/project"]

        def windows_git_alias(document: dict) -> None:
            document["writers"][0]["ownership_roots"] = [".git."]

        def root_governance_file(document: dict) -> None:
            document["writers"][0]["ownership_roots"] = ["AGENTS.md"]

        def dash_prefixed_base(document: dict) -> None:
            document["repository"]["base_ref"] = "-evil@" + ("a" * 40)

        def symbolic_head_base(document: dict) -> None:
            document["repository"]["base_ref"] = "HEAD@" + ("a" * 40)

        mutations = {
            "writer-outside-scope": writer_scope,
            "assurance-writes-and-self-review": assurance_write,
            "worktree-path-escape": worktree_escape,
            "mutable-base": mutable_base,
            "approval-without-plan": approval_without_input,
            "phase-reorder": phase_reorder,
            "draft-without-evidence": draft_without_evidence,
            "dangerous-final-effect": dangerous_final_effect,
            "overstated-multica": overstated_multica,
            "fictional-host-only": fictional_host_only,
            "random-retry-nonce": random_retry_nonce,
            "casefold-ownership-overlap": casefold_ownership_overlap,
            "shared-writer-and-tester-identity": shared_identity,
            "reserved-git-ownership": reserved_git_ownership,
            "reserved-governance-ownership": reserved_governance_ownership,
            "invalid-git-actor": invalid_git_actor,
            "invalid-git-base-label": invalid_git_base_label,
            "dishonest-host-limitation": dishonest_host_limitation,
            "nondeterministic-phase-identity": nondeterministic_phase_identity,
            "weakened-failure-policy": weakened_failure_policy,
            "stale-host-catalog-binding": stale_host_catalog_binding,
            "git-lock-actor": git_lock_actor,
            "windows-absolute-root": windows_absolute_root,
            "windows-git-alias": windows_git_alias,
            "root-governance-file": root_governance_file,
            "dash-prefixed-base": dash_prefixed_base,
            "symbolic-head-base": symbolic_head_base,
        }
        for label, mutate in mutations.items():
            with self.subTest(label=label):
                topology = self._load("writer_topology")
                mutate(topology)
                topology["topology_digest"] = writer_topology_digest(topology)
                self.assertTrue(validate_contract("writer_topology", topology))

    def test_writer_authority_rejects_uninstantiable_work_item_identity(self) -> None:
        topology = self._load("writer_topology")
        plan = self._load("plan_revision")
        approval = self._load("approval_grant")
        oversized = "work-" + ("a" * 300)
        plan["work_item_id"] = oversized
        plan["plan_digest"] = plan_revision_digest(plan)
        approval["work_item_id"] = oversized
        approval["plan_digest"] = plan["plan_digest"]
        approval["scope_digest"] = approval_scope_digest(approval)
        self.assertTrue(validate_contract("plan_revision", plan))
        self.assertTrue(validate_contract("approval_grant", approval))
        self.assertTrue(validate_writer_authority(topology, plan, approval))

    def test_writer_authority_rejects_scm_and_governance_roots_after_full_resigning(self) -> None:
        """Semantic safety survives a coherent three-document digest rewrite."""

        for unsafe_root in (
            ".circleci",
            ".claude-plugin",
            ".buildkite",
            ".devcontainer",
            ".dockerignore",
            ".gitattributes",
            ".gitignore",
            ".gitlab",
            ".gitlab-ci.yml",
            ".gitmodules",
            ".husky",
            ".mailmap",
            ".pre-commit-config.yaml",
            ".teamcity",
            ".travis.yml",
            "AGENTS.md/child",
            "AI-INSTRUCTIONS.md",
            "capability-package.json",
            "CODEOWNERS",
            "docs",
            "docs/CODEOWNERS/child",
            "factory-package.json",
            "Jenkinsfile",
            "Makefile",
            "policies",
            "pyproject.toml",
            "ROLES",
            "skills",
            "team-packs",
            "VERSION",
        ):
            with self.subTest(unsafe_root=unsafe_root):
                topology = self._load("writer_topology")
                plan = self._load("plan_revision")
                approval = self._load("approval_grant")

                topology["writers"][0]["ownership_roots"] = [unsafe_root]
                topology["topology_digest"] = writer_topology_digest(topology)
                binding = {
                    "topology_id": topology["topology_id"],
                    "topology_version": topology["topology_version"],
                    "topology_digest": topology["topology_digest"],
                }
                allowed_paths = [unsafe_root.rstrip("/") + "/"]
                plan["writer_topology"] = binding
                plan["allowed_paths"] = allowed_paths
                plan["plan_digest"] = plan_revision_digest(plan)
                approval["writer_topology"] = binding
                approval["allowed_paths"] = allowed_paths
                approval["plan_digest"] = plan["plan_digest"]
                approval["scope_digest"] = approval_scope_digest(approval)

                topology_issues = validate_contract("writer_topology", topology)
                authority_issues = validate_writer_authority(topology, plan, approval)
                self.assertIn(
                    "$.writers[0].ownership_roots[0]",
                    {issue.path for issue in topology_issues},
                )
                self.assertIn(
                    "$.topology.writers[0].ownership_roots[0]",
                    {issue.path for issue in authority_issues},
                )

    def test_writer_authority_closes_plan_actions_against_topology_capabilities(self) -> None:
        topology = self._load("writer_topology")
        plan = self._load("plan_revision")
        approval = self._load("approval_grant")
        self.assertEqual(validate_writer_authority(topology, plan, approval), [])

        plan_schema = json.loads(
            (ROOT / CONTRACT_SCHEMAS["plan_revision"]).read_text(encoding="utf-8")
        )
        schema_actions = set(
            plan_schema["properties"]["allowed_actions"]["items"]["enum"]
        )
        self.assertEqual(schema_actions, set(PLAN_ACTION_TO_TOPOLOGY_ACTIONS))
        actors = [
            *topology["writers"],
            topology["integrator"],
            *topology["assurance_roles"],
        ]
        granted = {
            action for actor in actors for action in actor["allowed_actions"]
        }
        forbidden = {
            action for actor in actors for action in actor["forbidden_actions"]
        }
        for action, required in PLAN_ACTION_TO_TOPOLOGY_ACTIONS.items():
            with self.subTest(mapped_action=action):
                self.assertLessEqual(required, granted)
                self.assertFalse(required & forbidden)

        for forbidden_action in (
            "approval.issue",
            "default-branch.merge",
            "release.publish",
            "production.deploy",
        ):
            with self.subTest(forbidden_action=forbidden_action):
                changed_plan = copy.deepcopy(plan)
                changed_approval = copy.deepcopy(approval)
                changed_plan["allowed_actions"].append(forbidden_action)
                changed_plan["plan_digest"] = plan_revision_digest(changed_plan)
                changed_approval["allowed_actions"] = changed_plan["allowed_actions"]
                changed_approval["plan_digest"] = changed_plan["plan_digest"]
                changed_approval["scope_digest"] = approval_scope_digest(changed_approval)
                issues = validate_writer_authority(
                    topology, changed_plan, changed_approval
                )
                self.assertTrue(issues)
                self.assertTrue(
                    any(
                        issue.path.startswith("$.plan.allowed_actions")
                        for issue in issues
                    )
                )

    def test_writer_authority_rejects_cross_platform_allowed_path_escape(self) -> None:
        for unsafe_path in (
            "apps/web/..\\..\\.github",
            "apps/web/..\\..\\AGENTS.md",
            "apps/web/../.github",
            "C:/apps/web",
            "CON",
            "apps/web/NUL.txt",
            "services/api/COM1.log",
            "packages/ui/lPt9.cache",
        ):
            with self.subTest(unsafe_path=unsafe_path):
                topology = self._load("writer_topology")
                plan = self._load("plan_revision")
                approval = self._load("approval_grant")
                plan["allowed_paths"] = [unsafe_path]
                plan["plan_digest"] = plan_revision_digest(plan)
                approval["allowed_paths"] = [unsafe_path]
                approval["plan_digest"] = plan["plan_digest"]
                approval["scope_digest"] = approval_scope_digest(approval)
                self.assertIn(
                    "$.allowed_paths[0]",
                    {issue.path for issue in validate_contract("plan_revision", plan)},
                )
                authority_issues = validate_writer_authority(topology, plan, approval)
                self.assertTrue(authority_issues)


if __name__ == "__main__":
    unittest.main()
