#!/usr/bin/env python3
"""Fail-closed release metadata, license, provenance, and history audit."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import tomllib
import unittest
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.json_support import loads_strict  # noqa: E402
from core.contracts import (  # noqa: E402
    approval_scope_digest,
    digest_value,
    plan_revision_digest,
    writer_topology_digest,
)
from core.lifecycle import SUPPORTED_UPGRADE_SOURCES  # noqa: E402
from core.schema_validation import validate_schema  # noqa: E402
from core.security import CREDENTIAL_PATTERNS  # noqa: E402
from tools.github_scm_conformance import (  # noqa: E402
    SCM_BASE_BRANCH,
    SCM_REPOSITORY,
    SCM_REPOSITORY_ID,
    SCM_WORKFLOW_PATH,
    SCM_WORKFLOW_REF,
    FRAMEWORK_REPOSITORY,
    build_approval as build_scm_conformance_approval,
    build_change as build_scm_conformance_change,
    build_plan as build_scm_conformance_plan,
)

ALLOWED_EVALUATION_LICENSES = {"Apache-2.0", "MIT"}
REVIEWED_CUSTOM_EVALUATION_LICENSES = {"host.multica": "Multica-License"}
EXPECTED_SCM_REPOSITORY = SCM_REPOSITORY
EXPECTED_SCM_REPOSITORY_ID = SCM_REPOSITORY_ID
EXPECTED_SCM_ACTOR_ID = "github:68719118"
SCM_OBJECT_KEYS = ("issue", "branch", "commit", "draft_pull_request")
SCM_EVIDENCE_PATHS = (
    "acceptance/github-scm-v10-first-run.json",
    "acceptance/github-scm-v10-replay.json",
)
SCM_PROFILE_PATH = "acceptance/v10-host-native-conformance.json"
SCM_EVIDENCE_RECORD_PATHS = frozenset(SCM_EVIDENCE_PATHS)
EXTERNAL_EVIDENCE_BASELINE_TAG = "v0.9.0"
EXTERNAL_EVIDENCE_BASELINE_COMMIT = "a286cfadbfb6f387a4f1fb94c244f57d4dd089e6"
EXTERNAL_EVIDENCE_PROTECTED_PATHS = frozenset(
    {
        ".github/workflows/release-verify.yml",
        ".github/workflows/disposable-runner.yml",
        ".github/workflows/validate.yml",
        "acceptance/github-scm-v10-first-run.json",
        "acceptance/github-scm-v10-replay.json",
        "acceptance/v10-host-native-conformance.json",
        "adapters/github/adapter.json",
        "contracts/core-contracts.json",
        "contracts/native-reference-workflow.json",
        "core/adapter_ports.py",
        "core/approval.py",
        "core/contracts.py",
        "core/github_scm.py",
        "core/json_support.py",
        "core/native_controller.py",
        "core/reference_adapters.py",
        "core/schema_validation.py",
        "core/security.py",
        "docs/16-release/v1.0-acceptance.md",
        "factory-package.json",
        "policies/adapter-authority.json",
        "schemas/adapter-authority-policy.schema.json",
        "schemas/approval-grant.schema.json",
        "schemas/evidence-bundle.schema.json",
        "schemas/github-change-set.schema.json",
        "schemas/github-scm-conformance-report.schema.json",
        "schemas/plan-revision.schema.json",
        "schemas/release-evidence.schema.json",
        "schemas/team-spec.schema.json",
        "schemas/v10-release-candidate-conformance.schema.json",
        "schemas/writer-topology.schema.json",
        "tests/test_release_assets.py",
        "tests/test_release_evidence.py",
        "tests/test_github_scm.py",
        "examples/github-scm-conformance/workflow.yml",
        "tools/github_scm_conformance.py",
        "tools/anonymous_release_worker.py",
        "tools/release_evidence.py",
        "tools/release_publication.py",
        "tools/release_audit.py",
        "skills/verify-release/SKILL.md",
    }
)
COMMIT_ID = re.compile(r"^[a-f0-9]{40}$")
WORKFLOW_USE_LINE = re.compile(
    r"^[ \t]*(?:-[ \t]*)?uses[ \t]*:[ \t]*([^#\s]+)[ \t]*(?:#.*)?$"
)
WORKFLOW_USE_KEY = re.compile(
    r"(?:^[ \t]*(?:-[ \t]*)?|[{,][ \t]*)(?:uses|'uses'|\"uses\")[ \t]*:"
)
WORKFLOW_QUOTED_KEY = re.compile(r"^[ \t]*(?:-[ \t]*)?(?:'[^']*'|\"[^\"]*\")[ \t]*:")
ACTION_USE = re.compile(r"^(actions/[a-z0-9-]+)@([a-f0-9]{40})$")
EXPECTED_ACTIONS = {
    "actions/checkout": ("3d3c42e5aac5ba805825da76410c181273ba90b1", "v7.0.1"),
    "actions/setup-python": ("5fda3b95a4ea91299a34e894583c3862153e4b97", "v7.0.0"),
    "actions/upload-artifact": ("043fb46d1a93c77aae656e7c1c64a875d1fc6a0a", "v7.0.1"),
}


class ReleaseAuditError(RuntimeError):
    pass


def _workflow_action_pins(path: Path) -> set[tuple[str, str]]:
    """Read every unambiguous workflow ``uses`` key and reject all other forms."""

    pins: set[tuple[str, str]] = set()
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        stripped = line.lstrip()
        if not stripped or stripped.startswith("#"):
            continue
        match = WORKFLOW_USE_LINE.fullmatch(line)
        starts_use_key = WORKFLOW_USE_KEY.search(line)
        mentions_use_key = re.search(r"(?i)\buses\b", line)
        quoted_key = WORKFLOW_QUOTED_KEY.match(line)
        if match is None:
            if (
                starts_use_key is not None
                or mentions_use_key is not None
                or quoted_key is not None
            ):
                raise ReleaseAuditError(
                    f"workflow uses syntax is unsupported at {path}:{line_number}"
                )
            continue
        action = ACTION_USE.fullmatch(match.group(1))
        if action is None:
            raise ReleaseAuditError(
                f"workflow action is not an exact allowlisted pin at {path}:{line_number}"
            )
        repository, revision = action.groups()
        expected = EXPECTED_ACTIONS.get(repository)
        if expected is None or expected[0] != revision:
            raise ReleaseAuditError(
                f"workflow action pin differs from source provenance at {path}:{line_number}"
            )
        pins.add((repository, revision))
    return pins


def _json(relative: str) -> dict[str, Any]:
    value = loads_strict((ROOT / relative).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ReleaseAuditError(f"JSON root is not an object: {relative}")
    return value


def _sha256_path(relative: str) -> str:
    return "sha256:" + hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()


def _discovered_test_count(module: str | None = None) -> int:
    loader = unittest.TestLoader()
    pattern = "test*.py" if module is None else module.rsplit(".", 1)[-1] + ".py"
    return loader.discover(str(ROOT / "tests"), pattern=pattern).countTestCases()


def _validate_release_identity(
    sbom: dict[str, Any], provenance: dict[str, Any], version: str
) -> None:
    package_values = sbom.get("packages")
    package = package_values[0] if isinstance(package_values, list) and package_values else None
    expected_spdx = {
        "name": f"agent-team-engineering-{version}",
        "documentNamespace": (
            "https://github.com/90le/agent-team-engineering/releases/download/"
            f"v{version}/agent-team-engineering-{version}.spdx.json"
        ),
        "documentDescribes": ["SPDXRef-Package-Agent-Team-Engineering"],
    }
    if any(sbom.get(field) != value for field, value in expected_spdx.items()):
        raise ReleaseAuditError("SPDX document identity differs from the release")
    if not isinstance(package, dict):
        raise ReleaseAuditError("SPDX package identity is malformed")
    expected_package = {
        "name": "agent-team-engineering",
        "SPDXID": "SPDXRef-Package-Agent-Team-Engineering",
        "downloadLocation": (
            f"git+https://github.com/90le/agent-team-engineering.git@v{version}"
        ),
        "licenseConcluded": "Apache-2.0",
        "supplier": "Organization: 90le",
        "primaryPackagePurpose": "APPLICATION",
    }
    if any(package.get(field) != value for field, value in expected_package.items()):
        raise ReleaseAuditError("SPDX package release identity differs")
    external_refs = package.get("externalRefs")
    expected_purl = f"pkg:github/90le/agent-team-engineering@v{version}"
    if not isinstance(external_refs, list) or not any(
        isinstance(record, dict)
        and record.get("referenceCategory") == "PACKAGE-MANAGER"
        and record.get("referenceType") == "purl"
        and record.get("referenceLocator") == expected_purl
        for record in external_refs
    ):
        raise ReleaseAuditError("SPDX package purl differs from the release")

    expected_provenance = {
        "schema_version": "1.0.0",
        "project": "90le/agent-team-engineering",
        "release_commit_binding": "annotated-tag-object",
        "license": "Apache-2.0",
        "claims": {
            "external_products_are_optional": True,
            "host_projections_are_data_only": True,
            "custom_licensed_upstreams_are_not_embedded": True,
            "external_databases_are_not_core_authority": True,
            "production_credentials_in_repository": False,
            "automatic_merge_or_deploy": False,
        },
    }
    if any(provenance.get(field) != value for field, value in expected_provenance.items()):
        raise ReleaseAuditError("source provenance identity or claims differ from policy")
    action_records = provenance.get("github_actions")
    if not isinstance(action_records, list):
        raise ReleaseAuditError("source provenance lacks GitHub Action pins")
    observed_actions = {
        str(record.get("repository")): (
            str(record.get("revision")),
            str(record.get("tag_observed")),
        )
        for record in action_records
        if isinstance(record, dict)
    }
    if len(observed_actions) != len(action_records) or observed_actions != EXPECTED_ACTIONS:
        raise ReleaseAuditError("source provenance GitHub Action pins differ")
    workflow_root = ROOT / ".github/workflows"
    workflow_paths = sorted(
        {
            *workflow_root.glob("*.yml"),
            *workflow_root.glob("*.yaml"),
        }
    ) + [ROOT / "examples/github-scm-conformance/workflow.yml"]
    uses: set[tuple[str, str]] = set()
    for workflow_path in workflow_paths:
        uses.update(_workflow_action_pins(workflow_path))
    expected_uses = {(repository, values[0]) for repository, values in EXPECTED_ACTIONS.items()}
    if uses != expected_uses:
        raise ReleaseAuditError("workflow Action pins differ from source provenance")


def validate_release_assets() -> dict[str, Any]:
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    factory = _json("factory-package.json")
    capability = _json("capability-package.json")
    codex = _json(".agents/plugins/plugins/agent-team/.codex-plugin/plugin.json")
    claude = _json(".agents/plugins/plugins/agent-team/.claude-plugin/plugin.json")
    marketplace = _json(".claude-plugin/marketplace.json")
    observed = {
        "VERSION": version,
        "pyproject": str(pyproject["project"]["version"]),
        "factory": str(factory["version"]),
        "capability": str(capability["version"]),
        "codex_plugin": str(codex["version"]),
        "claude_plugin": str(claude["version"]),
        "claude_marketplace_plugin": str(marketplace["plugins"][0]["version"]),
        "claude_marketplace": str(marketplace["version"]),
    }
    if set(observed.values()) != {version}:
        raise ReleaseAuditError(f"release versions differ: {observed}")
    if factory["status"] != "STABLE":
        raise ReleaseAuditError("factory package is not STABLE")
    if "Apache License" not in (ROOT / "LICENSE").read_text(encoding="utf-8"):
        raise ReleaseAuditError("Apache-2.0 license text is missing")

    sbom = _json("sbom/agent-team-engineering.spdx.json")
    if sbom.get("spdxVersion") != "SPDX-2.3" or sbom.get("dataLicense") != "CC0-1.0":
        raise ReleaseAuditError("SPDX document metadata is invalid")
    packages = sbom.get("packages")
    if not isinstance(packages, list) or len(packages) != 1:
        raise ReleaseAuditError("SPDX must describe exactly the shipped dependency-free package")
    package = packages[0]
    if (
        not isinstance(package, dict)
        or package.get("versionInfo") != version
        or package.get("licenseDeclared") != "Apache-2.0"
        or package.get("filesAnalyzed") is not False
    ):
        raise ReleaseAuditError("SPDX package differs from release metadata")

    provenance = _json("supply-chain/source-provenance.json")
    if provenance.get("release") != f"v{version}":
        raise ReleaseAuditError("source provenance release differs from VERSION")
    if provenance.get("python_runtime_dependencies") != []:
        raise ReleaseAuditError("unexpected Python runtime dependency in provenance")
    if provenance.get("copied_external_source_files") != []:
        raise ReleaseAuditError("external source copy requires a separate license review")
    upstreams = provenance.get("evaluated_upstreams")
    if not isinstance(upstreams, list) or len(upstreams) < 6:
        raise ReleaseAuditError("evaluated upstream registry is incomplete")
    identities: set[str] = set()
    for record in upstreams:
        if not isinstance(record, dict):
            raise ReleaseAuditError("evaluated upstream entry is malformed")
        identity = str(record.get("id"))
        if identity in identities:
            raise ReleaseAuditError(f"duplicate evaluated upstream: {identity}")
        identities.add(identity)
        license_id = record.get("license")
        allowed_custom = REVIEWED_CUSTOM_EVALUATION_LICENSES.get(identity)
        if license_id not in ALLOWED_EVALUATION_LICENSES and license_id != allowed_custom:
            raise ReleaseAuditError(f"unreviewed upstream license: {identity}")
        revision = str(record.get("revision", ""))
        if len(revision) != 40 or any(character not in "0123456789abcdef" for character in revision):
            raise ReleaseAuditError(f"upstream revision is not an immutable commit: {identity}")
        if record.get("runtime_dependency") is not False:
            raise ReleaseAuditError(f"upstream unexpectedly became a runtime dependency: {identity}")
    _validate_release_identity(sbom, provenance, version)

    conformance = _json("acceptance/v10-host-native-conformance.json")
    conformance_schema = _json("schemas/v10-release-candidate-conformance.schema.json")
    conformance_issues = validate_schema(conformance, conformance_schema)
    if conformance_issues:
        details = "; ".join(
            f"{issue.path}: {issue.message}" for issue in conformance_issues
        )
        raise ReleaseAuditError(f"host-native conformance report violates schema: {details}")
    if conformance.get("factory_release") != f"v{version}":
        raise ReleaseAuditError("host-native conformance release differs from VERSION")
    if conformance.get("status") != "PRE_RELEASE":
        raise ReleaseAuditError("source conformance must remain PRE_RELEASE")
    hosts = conformance.get("hosts")
    if not isinstance(hosts, list):
        raise ReleaseAuditError("host-native conformance hosts are malformed")
    claimed_hosts = {
        str(record.get("host_id")): str(record.get("support_tier"))
        for record in hosts
        if isinstance(record, dict)
    }
    if len(claimed_hosts) != len(hosts):
        raise ReleaseAuditError("host-native conformance contains duplicate host identities")
    descriptor_hosts: dict[str, str] = {}
    for descriptor_path in sorted((ROOT / "hosts").glob("*/host.json")):
        descriptor = _json(descriptor_path.relative_to(ROOT).as_posix())
        descriptor_hosts[str(descriptor.get("host_id"))] = str(descriptor.get("support_tier"))
    if claimed_hosts != descriptor_hosts:
        raise ReleaseAuditError(
            "host-native conformance claims differ from host descriptors: "
            f"report={claimed_hosts}, descriptors={descriptor_hosts}"
        )
    local_gates = conformance.get("local_gates")
    if not isinstance(local_gates, dict):
        raise ReleaseAuditError("v1.0 candidate lacks local gates")
    expected_counts = {
        "unit_tests": _discovered_test_count(),
        "writer_authority": _discovered_test_count("tests.test_v08_contracts"),
        "host_lifecycle": _discovered_test_count("tests.test_host_lifecycle"),
    }
    reported_counts = {
        "unit_tests": local_gates.get("unit_tests", {}).get("count"),
        "writer_authority": local_gates.get("writer_authority", {}).get("test_count"),
        "host_lifecycle": local_gates.get("host_lifecycle", {}).get("test_count"),
    }
    if reported_counts != expected_counts:
        raise ReleaseAuditError(
            f"v1.0 candidate test counts differ: report={reported_counts}, actual={expected_counts}"
        )

    topology = _json("examples/v08-contracts/valid/writer-topology.json")
    plan = _json("examples/v08-contracts/valid/plan-revision.json")
    approval = _json("examples/v08-contracts/valid/approval-grant.json")
    writer_gate = local_gates.get("writer_authority")
    expected_writer_digests = {
        "topology_digest": writer_topology_digest(topology),
        "plan_digest": plan_revision_digest(plan),
        "approval_scope_digest": approval_scope_digest(approval),
    }
    if not isinstance(writer_gate, dict) or any(
        writer_gate.get(field) != digest for field, digest in expected_writer_digests.items()
    ):
        raise ReleaseAuditError("v1.0 candidate writer authority digests differ from examples")

    migration = local_gates.get("instance_migration")
    expected_sources = sorted(
        SUPPORTED_UPGRADE_SOURCES,
        key=lambda value: tuple(int(part) for part in value.split(".")),
    )
    if not isinstance(migration, dict) or migration.get("source_versions") != expected_sources:
        raise ReleaseAuditError("v1.0 candidate migration sources differ from implementation")

    package_gate = local_gates.get("skills_and_plugins")
    skill_count = len(list((ROOT / "skills").glob("*/SKILL.md"))) + len(
        list((ROOT / ".agents/plugins/plugins/agent-team/skills").glob("*/SKILL.md"))
    )
    if not isinstance(package_gate, dict) or package_gate.get("skill_packages") != skill_count:
        raise ReleaseAuditError("v1.0 candidate Skill count differs from the distribution")
    if package_gate.get("plugin_manifests") != 2:
        raise ReleaseAuditError("v1.0 candidate plugin manifest count differs")

    supply = conformance.get("supply_chain")
    if not isinstance(supply, dict):
        raise ReleaseAuditError("v1.0 candidate lacks supply-chain bindings")
    for field in ("sbom", "source_provenance"):
        record = supply.get(field)
        if not isinstance(record, dict) or record.get("sha256") != _sha256_path(str(record.get("path", ""))):
            raise ReleaseAuditError(f"v1.0 candidate {field} digest differs from the file")

    for gate_name in ("cold_start", "release_smoke"):
        gate = local_gates.get(gate_name)
        if not isinstance(gate, dict):
            raise ReleaseAuditError(f"v1.0 candidate lacks {gate_name} gate")
        if (gate.get("status") == "PASS") != (isinstance(gate.get("runs"), int) and gate["runs"] > 0):
            raise ReleaseAuditError(f"v1.0 candidate {gate_name} status/count disagree")
    isolated = local_gates.get("isolated_hosts")
    if not isinstance(isolated, dict):
        raise ReleaseAuditError("v1.0 candidate lacks isolated-host gate")
    isolated_pass = isolated.get("load_tests") == 2 and set(isolated.get("hosts", [])) == {
        "openclaw",
        "hermes",
    }
    if (isolated.get("status") == "PASS") != isolated_pass:
        raise ReleaseAuditError("v1.0 candidate isolated-host status/evidence disagree")

    boundaries = conformance.get("authority_boundaries")
    external = local_gates.get("external_scm")
    if not isinstance(boundaries, dict) or not isinstance(external, dict):
        raise ReleaseAuditError("v1.0 candidate external authority is malformed")
    external_pass = (
        external.get("status") == "PASS"
        and external.get("live_runs") == 2
        and external.get("evidence_files") == list(SCM_EVIDENCE_PATHS)
    )
    expected_external_boundary = {
        "dedicated_scm_identity_used": external_pass,
        "ephemeral_scm_token_used": external_pass,
        "external_scm_write_scope": (
            "GRANTED_DEDICATED_TEST_ONLY" if external_pass else "NONE"
        ),
    }
    if any(boundaries.get(field) != value for field, value in expected_external_boundary.items()):
        raise ReleaseAuditError("v1.0 candidate external SCM status/authority disagree")
    if not external_pass and (
        external.get("status") != "NOT_RUN"
        or external.get("live_runs") != 0
        or external.get("evidence_files") != []
    ):
        raise ReleaseAuditError("v1.0 candidate contains partial external SCM claims")
    return {
        "version": version,
        "metadata_sources": len(observed),
        "spdx_packages": len(packages),
        "evaluated_upstreams": len(upstreams),
        "host_claims": len(claimed_hosts),
    }


def _approval_from_report(report: dict[str, Any], plan: dict[str, Any]) -> dict[str, Any]:
    workflow = report["workflow"]
    verified = {
        "actor_id": report["actor_id"],
        "identity_provider": report["identity_provider"],
        "signature_ref": report["identity_ref"],
    }
    environment = {
        "GITHUB_RUN_ID": workflow["run_id"],
        "GITHUB_RUN_ATTEMPT": workflow["run_attempt"],
        "GITHUB_REPOSITORY": report["repository"],
    }
    issued = datetime.fromisoformat(report["approval_issued_at"].replace("Z", "+00:00"))
    return build_scm_conformance_approval(plan, verified, environment, issued)


def _validate_typed_scm_object(
    key: str, record: dict[str, Any], *, proposal_branch: str
) -> None:
    repository = EXPECTED_SCM_REPOSITORY
    provider_id = record["provider_id"]
    if key == "issue":
        pattern = rf"https://github\.com/{re.escape(repository)}/issues/[1-9][0-9]*"
        provider_pattern = r"I_[A-Za-z0-9_-]+"
    elif key == "draft_pull_request":
        pattern = rf"https://github\.com/{re.escape(repository)}/pull/[1-9][0-9]*"
        provider_pattern = r"PR_[A-Za-z0-9_-]+"
    elif key == "branch":
        pattern = (
            rf"https://api\.github\.com/repos/{re.escape(repository)}/git/refs/heads/"
            + re.escape(proposal_branch)
        )
        provider_pattern = r"REF_[A-Za-z0-9_-]+"
    elif key == "commit":
        pattern = (
            rf"https://api\.github\.com/repos/{re.escape(repository)}/git/commits/"
            + re.escape(provider_id)
        )
        provider_pattern = r"[a-f0-9]{40}"
    else:
        raise ReleaseAuditError(f"unsupported GitHub SCM object type: {key}")
    if record.get("object_type") != key:
        raise ReleaseAuditError(f"GitHub SCM object type differs from its field: {key}")
    if not re.fullmatch(pattern, str(record.get("external_ref", ""))):
        raise ReleaseAuditError(f"GitHub SCM object has the wrong typed URL: {key}")
    if not re.fullmatch(provider_pattern, str(provider_id)):
        raise ReleaseAuditError(f"GitHub SCM object has the wrong provider identity type: {key}")


def validate_scm_evidence_documents(
    profile: dict[str, Any],
    first: dict[str, Any],
    replay: dict[str, Any],
) -> dict[str, Any]:
    boundaries = profile.get("authority_boundaries")
    if not isinstance(boundaries, dict):
        raise ReleaseAuditError("v1.0 acceptance report lacks authority boundaries")
    if boundaries.get("external_scm_write_scope") != "GRANTED_DEDICATED_TEST_ONLY":
        raise ReleaseAuditError("external SCM lacks dedicated-test-only authorization")
    if any(
        boundaries.get(field) is not False
        for field in (
            "production_accounts_used",
            "automatic_merge",
            "automatic_deploy",
            "independent_writer_execution",
        )
    ):
        raise ReleaseAuditError("acceptance report unexpectedly broadens external authority")

    schema = _json("schemas/github-scm-conformance-report.schema.json")
    for label, report in (("first", first), ("replay", replay)):
        issues = validate_schema(report, schema)
        if issues:
            details = "; ".join(f"{issue.path}: {issue.message}" for issue in issues)
            raise ReleaseAuditError(f"{label} GitHub SCM report violates schema: {details}")

    same_fields = (
        "repository",
        "repository_id",
        "repository_private",
        "base_commit",
        "framework_commit",
        "framework_repository",
        "plan_digest",
        "plan_schema_version",
        "writer_topology",
        "change_digest",
        "approval_schema_version",
        "actor_id",
        "identity_provider",
        "base_branch",
        "proposal_branch",
    )
    for field in same_fields:
        if first.get(field) != replay.get(field):
            raise ReleaseAuditError(f"GitHub SCM reports disagree on {field}")
    if first.get("repository") != EXPECTED_SCM_REPOSITORY:
        raise ReleaseAuditError("GitHub SCM evidence targets an unexpected repository")
    if first.get("repository_id") != EXPECTED_SCM_REPOSITORY_ID:
        raise ReleaseAuditError("GitHub SCM evidence has an unexpected repository_id")
    if first.get("repository_private") is not True:
        raise ReleaseAuditError("GitHub SCM evidence repository was not verified Private")
    if first.get("framework_repository") != FRAMEWORK_REPOSITORY:
        raise ReleaseAuditError("GitHub SCM evidence names an unexpected framework repository")
    if first.get("actor_id") != EXPECTED_SCM_ACTOR_ID:
        raise ReleaseAuditError("GitHub SCM evidence was not dispatched by the owner identity")
    if first.get("identity_provider") != "github.actions":
        raise ReleaseAuditError("GitHub SCM evidence did not use GitHub Actions identity")
    if first["workflow"]["run_id"] == replay["workflow"]["run_id"]:
        raise ReleaseAuditError("GitHub SCM evidence must come from two distinct workflow runs")
    if first.get("approval_scope_digest") == replay.get("approval_scope_digest"):
        raise ReleaseAuditError("GitHub SCM replay must use a new short-lived approval scope")
    for report in (first, replay):
        workflow = report["workflow"]
        run_id = workflow["run_id"]
        expected_identity = (
            f"github-actions://{EXPECTED_SCM_REPOSITORY}/runs/{run_id}/attempts/1"
        )
        expected_workflow = {
            "path": SCM_WORKFLOW_PATH,
            "ref": SCM_WORKFLOW_REF,
            "sha": report["base_commit"],
            "repository_ref": f"refs/heads/{SCM_BASE_BRANCH}",
            "run_id": run_id,
            "run_attempt": "1",
            "run_url": (
                f"https://github.com/{EXPECTED_SCM_REPOSITORY}/actions/runs/{run_id}"
            ),
        }
        if workflow != expected_workflow:
            raise ReleaseAuditError("GitHub SCM workflow identity is not canonically bound")
        if report["identity_ref"] != expected_identity:
            raise ReleaseAuditError("GitHub SCM run identity is not canonically bound")
        if report["approval_id"] != f"approval-github-run-{run_id}-attempt-1":
            raise ReleaseAuditError("GitHub SCM approval ID is not bound to its workflow run")
        if report["approval_nonce"] != f"github-run-{run_id}-attempt-1-nonce":
            raise ReleaseAuditError("GitHub SCM approval nonce is not bound to its workflow run")
        if report["approval_evidence_ref"] != (
            f"github-actions://{EXPECTED_SCM_REPOSITORY}/runs/{run_id}"
        ):
            raise ReleaseAuditError("GitHub SCM approval evidence is not bound to its run")
        if report.get("merge_performed") is not False:
            raise ReleaseAuditError("GitHub SCM evidence reports a merge")
        if report.get("deployment_performed") is not False:
            raise ReleaseAuditError("GitHub SCM evidence reports a deployment")

    for key in SCM_OBJECT_KEYS:
        created = first.get(key)
        reconciled = replay.get(key)
        if not isinstance(created, dict) or not isinstance(reconciled, dict):
            raise ReleaseAuditError(f"GitHub SCM report lacks object evidence: {key}")
        expected_keys = {"object_type", "external_ref", "provider_id", "created"}
        if set(created) != expected_keys or set(reconciled) != expected_keys:
            raise ReleaseAuditError(f"GitHub SCM object evidence is not minimal: {key}")
        if created.get("created") is not True or reconciled.get("created") is not False:
            raise ReleaseAuditError(f"GitHub SCM create/replay flags are invalid: {key}")
        if created.get("external_ref") != reconciled.get("external_ref"):
            raise ReleaseAuditError(f"GitHub SCM replay changed the external reference: {key}")
        if created.get("provider_id") != reconciled.get("provider_id"):
            raise ReleaseAuditError(f"GitHub SCM replay changed the provider identity: {key}")
        _validate_typed_scm_object(
            key, created, proposal_branch=str(first["proposal_branch"])
        )

    framework_commit = first.get("framework_commit")
    if not isinstance(framework_commit, str) or not COMMIT_ID.fullmatch(framework_commit):
        raise ReleaseAuditError("GitHub SCM framework commit is malformed")
    expected_plan = build_scm_conformance_plan(
        repository_id=EXPECTED_SCM_REPOSITORY_ID,
        base_commit=str(first.get("base_commit", "")),
        framework_commit=framework_commit,
    )
    expected_change = build_scm_conformance_change(expected_plan, EXPECTED_SCM_REPOSITORY)
    if first.get("plan_digest") != expected_plan["plan_digest"]:
        raise ReleaseAuditError("GitHub SCM evidence is not bound to the canonical v1.0 plan")
    if first.get("change_digest") != digest_value(expected_change):
        raise ReleaseAuditError("GitHub SCM evidence is not bound to the canonical change set")
    if first.get("base_branch") != expected_change["base_branch"] or first.get(
        "proposal_branch"
    ) != expected_change["proposal_branch"]:
        raise ReleaseAuditError("GitHub SCM report branch identities differ from the change set")
    for label, report in (("first", first), ("replay", replay)):
        expected_approval = _approval_from_report(report, expected_plan)
        expected_approval_fields = {
            "approval_id": expected_approval["approval_id"],
            "approval_scope_digest": expected_approval["scope_digest"],
            "approval_issued_at": expected_approval["issued_at"],
            "approval_expires_at": expected_approval["expires_at"],
            "approval_nonce": expected_approval["nonce"],
            "approval_evidence_ref": expected_approval["evidence_ref"],
        }
        if any(report.get(field) != value for field, value in expected_approval_fields.items()):
            raise ReleaseAuditError(
                f"{label} GitHub SCM approval is not the canonical v1.1 authority"
            )
    return {
        "scm_evidence_repository": EXPECTED_SCM_REPOSITORY,
        "scm_evidence_objects": len(SCM_OBJECT_KEYS),
        "scm_evidence_framework_commit": framework_commit,
    }


def _git_output(arguments: list[str]) -> str:
    try:
        return subprocess.run(
            ["git", *arguments],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
            timeout=60,
            shell=False,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        raise ReleaseAuditError("cannot verify Git state for external evidence") from None


def validate_external_scm_evidence() -> dict[str, Any]:
    missing = [relative for relative in SCM_EVIDENCE_PATHS if not (ROOT / relative).is_file()]
    if missing:
        raise ReleaseAuditError("GitHub SCM evidence is missing: " + ", ".join(missing))
    profile = _json(SCM_PROFILE_PATH)
    first = _json(SCM_EVIDENCE_PATHS[0])
    replay = _json(SCM_EVIDENCE_PATHS[1])
    report = validate_scm_evidence_documents(profile, first, replay)
    if _git_output(["status", "--porcelain", "--untracked-files=all"]):
        raise ReleaseAuditError("release evidence must be audited from a clean Git worktree")
    for relative in SCM_EVIDENCE_PATHS:
        _git_output(["ls-files", "--error-unmatch", relative])
    framework_commit = report["scm_evidence_framework_commit"]
    _git_output(["cat-file", "-e", f"{framework_commit}^{{commit}}"])
    _git_output(["merge-base", "--is-ancestor", framework_commit, "HEAD"])
    if _git_output(["cat-file", "-t", EXTERNAL_EVIDENCE_BASELINE_TAG]) != "tag":
        raise ReleaseAuditError("external evidence baseline must be an annotated tag")
    baseline_commit = _git_output(
        ["rev-list", "-n", "1", EXTERNAL_EVIDENCE_BASELINE_TAG]
    )
    if baseline_commit != EXTERNAL_EVIDENCE_BASELINE_COMMIT:
        raise ReleaseAuditError("v0.9.0 external-evidence baseline tag moved")
    if framework_commit == baseline_commit:
        raise ReleaseAuditError("v1.0 SCM evidence cannot reuse the v0.9.0 implementation")
    _git_output(["merge-base", "--is-ancestor", baseline_commit, framework_commit])

    evidence_commits = {
        _git_output(["log", "-1", "--format=%H", "--", relative])
        for relative in SCM_EVIDENCE_PATHS
    }
    if len(evidence_commits) != 1:
        raise ReleaseAuditError(
            "external SCM first-run and replay must share one evidence-only commit"
        )
    evidence_commit = evidence_commits.pop()
    if COMMIT_ID.fullmatch(evidence_commit) is None:
        raise ReleaseAuditError("external SCM evidence commit is malformed")
    commit_line = _git_output(
        ["rev-list", "--parents", "-n", "1", evidence_commit]
    ).split()
    if len(commit_line) != 2 or commit_line[1] != framework_commit:
        raise ReleaseAuditError(
            "external SCM evidence must be the direct child of its evidenced implementation"
        )
    evidence_changes = set(
        filter(
            None,
            _git_output(
                ["diff-tree", "--no-commit-id", "--name-only", "-r", evidence_commit]
            ).splitlines(),
        )
    )
    if evidence_changes != SCM_EVIDENCE_RECORD_PATHS:
        raise ReleaseAuditError(
            "external SCM evidence commit must change exactly the two evidence reports"
        )
    _git_output(["merge-base", "--is-ancestor", evidence_commit, "HEAD"])
    protected_changes = set(
        filter(
            None,
            _git_output(
                ["diff", "--name-only", f"{evidence_commit}..HEAD"]
            ).splitlines(),
        )
    ) & EXTERNAL_EVIDENCE_PROTECTED_PATHS
    if protected_changes:
        raise ReleaseAuditError(
            "external SCM implementation changed after the evidenced v1.0 commit: "
            + ", ".join(sorted(protected_changes))
        )
    gates = profile.get("local_gates")
    boundaries = profile.get("authority_boundaries")
    external_gate = gates.get("external_scm") if isinstance(gates, dict) else None
    if (
        profile.get("status") != "PRE_RELEASE"
        or not isinstance(external_gate, dict)
        or not isinstance(boundaries, dict)
    ):
        raise ReleaseAuditError("v1.0 candidate report has invalid source-state semantics")
    if external_gate.get("status") != "PASS" or external_gate.get("live_runs") != 2:
        raise ReleaseAuditError("v1.0 acceptance report lacks exactly two live SCM runs")
    if boundaries.get("dedicated_scm_identity_used") is not True:
        raise ReleaseAuditError("v1.0 acceptance report lacks dedicated SCM identity evidence")
    if boundaries.get("ephemeral_scm_token_used") is not True:
        raise ReleaseAuditError("v1.0 acceptance report lacks ephemeral SCM token evidence")
    for gate_name in ("isolated_hosts", "cold_start", "release_smoke"):
        gate = gates.get(gate_name)
        if not isinstance(gate, dict) or gate.get("status") != "PASS":
            raise ReleaseAuditError(f"v1.0 release gate is incomplete: {gate_name}")
    report["post_evidence_paths"] = len(
        set(
            filter(
                None,
                _git_output(["diff", "--name-only", f"{evidence_commit}..HEAD"]).splitlines(),
            )
        )
    )
    report["scm_evidence_record_commit"] = evidence_commit
    report["external_evidence_baseline"] = EXTERNAL_EVIDENCE_BASELINE_TAG
    report["protected_paths_verified_unchanged"] = len(
        EXTERNAL_EVIDENCE_PROTECTED_PATHS
    )
    return report


def scan_git_history(since_tag: str) -> int:
    try:
        listed = subprocess.run(
            ["git", "rev-list", "--objects", f"{since_tag}..HEAD"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
            timeout=60,
            shell=False,
        )
    except (OSError, subprocess.SubprocessError):
        raise ReleaseAuditError(f"cannot enumerate Git history since {since_tag}") from None
    scanned = 0
    for line in listed.stdout.splitlines():
        object_id, _, path = line.partition(" ")
        if not path:
            continue
        kind = subprocess.run(
            ["git", "cat-file", "-t", object_id],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
            shell=False,
        ).stdout.strip()
        if kind != "blob":
            continue
        size = int(
            subprocess.run(
                ["git", "cat-file", "-s", object_id],
                cwd=ROOT,
                check=True,
                capture_output=True,
                text=True,
                timeout=10,
                shell=False,
            ).stdout.strip()
        )
        if size > 10 * 1024 * 1024:
            raise ReleaseAuditError(f"history contains an oversized blob: {path}")
        content = subprocess.run(
            ["git", "cat-file", "blob", object_id],
            cwd=ROOT,
            check=True,
            capture_output=True,
            timeout=10,
            shell=False,
        ).stdout
        scanned += 1
        if any(pattern.search(content.decode("utf-8", errors="ignore")) for pattern in CREDENTIAL_PATTERNS):
            raise ReleaseAuditError(
                f"history since {since_tag} contains a high-confidence credential pattern in {path}"
            )
    return scanned


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--since-tag", default="v0.9.0")
    parser.add_argument("--require-external-evidence", action="store_true")
    arguments = parser.parse_args()
    try:
        report = validate_release_assets()
        if arguments.require_external_evidence:
            report.update(validate_external_scm_evidence())
        report["history_blobs_scanned"] = scan_git_history(arguments.since_tag)
    except ReleaseAuditError as error:
        print(f"release audit failed: {error}", file=sys.stderr)
        return 1
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
