#!/usr/bin/env python3
"""Fail-closed release metadata, license, provenance, and history audit."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.json_support import loads_strict  # noqa: E402
from core.schema_validation import validate_schema  # noqa: E402
from core.security import CREDENTIAL_PATTERNS  # noqa: E402

ALLOWED_EVALUATION_LICENSES = {"Apache-2.0", "MIT"}
EXPECTED_SCM_REPOSITORY = "90le/agent-team-v08-conformance-private"
EXPECTED_SCM_REPOSITORY_ID = "repo.conformance.github.v08"
EXPECTED_SCM_ACTOR_ID = "github:68719118"
SCM_OBJECT_KEYS = ("issue", "branch", "commit", "draft_pull_request")
SCM_EVIDENCE_PATHS = (
    "acceptance/github-scm-first-run.json",
    "acceptance/github-scm-replay.json",
)
POST_EVIDENCE_ALLOWED_PATHS = frozenset(
    {
        "acceptance/github-scm-first-run.json",
        "acceptance/github-scm-replay.json",
        "acceptance/v08-native-conformance.json",
        "core/validation.py",
        "docs/16-release/v0.8-acceptance.md",
        "factory-package.json",
    }
)
COMMIT_ID = re.compile(r"^[a-f0-9]{40}$")


class ReleaseAuditError(RuntimeError):
    pass


def _json(relative: str) -> dict[str, Any]:
    value = loads_strict((ROOT / relative).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ReleaseAuditError(f"JSON root is not an object: {relative}")
    return value


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
        if record.get("license") not in ALLOWED_EVALUATION_LICENSES:
            raise ReleaseAuditError(f"unreviewed upstream license: {identity}")
        revision = str(record.get("revision", ""))
        if len(revision) != 40 or any(character not in "0123456789abcdef" for character in revision):
            raise ReleaseAuditError(f"upstream revision is not an immutable commit: {identity}")
        if record.get("runtime_dependency") is not False:
            raise ReleaseAuditError(f"upstream unexpectedly became a runtime dependency: {identity}")
    return {
        "version": version,
        "metadata_sources": len(observed),
        "spdx_packages": len(packages),
        "evaluated_upstreams": len(upstreams),
    }


def _trusted_github_ref(value: object, repository: str) -> bool:
    if not isinstance(value, str):
        return False
    parsed = urlparse(value)
    if parsed.scheme != "https" or parsed.params or parsed.query or parsed.fragment:
        return False
    if parsed.netloc == "github.com":
        return parsed.path.startswith(f"/{repository}/")
    if parsed.netloc == "api.github.com":
        return parsed.path.startswith(f"/repos/{repository}/")
    return False


def validate_scm_evidence_documents(
    profile: dict[str, Any],
    first: dict[str, Any],
    replay: dict[str, Any],
) -> dict[str, Any]:
    boundaries = profile.get("authority_boundaries")
    if not isinstance(boundaries, dict):
        raise ReleaseAuditError("v0.8 acceptance profile lacks authority boundaries")
    if boundaries.get("gate_c_external_write") != "GRANTED_DEDICATED_TEST_ONLY":
        raise ReleaseAuditError("Gate C lacks completed dedicated-test evidence")
    if boundaries.get("production_integrations") is not False:
        raise ReleaseAuditError("acceptance profile unexpectedly enables production integrations")

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
        "plan_digest",
        "actor_id",
        "identity_provider",
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
    if first.get("actor_id") != EXPECTED_SCM_ACTOR_ID:
        raise ReleaseAuditError("GitHub SCM evidence was not dispatched by the owner identity")
    if first.get("identity_provider") != "github.actions":
        raise ReleaseAuditError("GitHub SCM evidence did not use GitHub Actions identity")
    if first.get("identity_ref") == replay.get("identity_ref"):
        raise ReleaseAuditError("GitHub SCM evidence must come from two distinct workflow runs")
    if first.get("approval_scope_digest") == replay.get("approval_scope_digest"):
        raise ReleaseAuditError("GitHub SCM replay must use a new short-lived approval scope")
    for report in (first, replay):
        expected_prefix = f"github-actions://{EXPECTED_SCM_REPOSITORY}/runs/"
        if not str(report.get("identity_ref", "")).startswith(expected_prefix):
            raise ReleaseAuditError("GitHub SCM identity reference escapes the evidence repository")
        if report.get("merge_performed") is not False:
            raise ReleaseAuditError("GitHub SCM evidence reports a merge")
        if report.get("deployment_performed") is not False:
            raise ReleaseAuditError("GitHub SCM evidence reports a deployment")

    for key in SCM_OBJECT_KEYS:
        created = first.get(key)
        reconciled = replay.get(key)
        if not isinstance(created, dict) or not isinstance(reconciled, dict):
            raise ReleaseAuditError(f"GitHub SCM report lacks object evidence: {key}")
        expected_keys = {"external_ref", "provider_id", "created"}
        if set(created) != expected_keys or set(reconciled) != expected_keys:
            raise ReleaseAuditError(f"GitHub SCM object evidence is not minimal: {key}")
        if created.get("created") is not True or reconciled.get("created") is not False:
            raise ReleaseAuditError(f"GitHub SCM create/replay flags are invalid: {key}")
        if created.get("external_ref") != reconciled.get("external_ref"):
            raise ReleaseAuditError(f"GitHub SCM replay changed the external reference: {key}")
        if created.get("provider_id") != reconciled.get("provider_id"):
            raise ReleaseAuditError(f"GitHub SCM replay changed the provider identity: {key}")
        if not _trusted_github_ref(created.get("external_ref"), EXPECTED_SCM_REPOSITORY):
            raise ReleaseAuditError(f"GitHub SCM object reference is not trusted: {key}")
        provider_id = created.get("provider_id")
        if not isinstance(provider_id, str) or not provider_id or len(provider_id) > 256:
            raise ReleaseAuditError(f"GitHub SCM provider identity is malformed: {key}")

    framework_commit = first.get("framework_commit")
    if not isinstance(framework_commit, str) or not COMMIT_ID.fullmatch(framework_commit):
        raise ReleaseAuditError("GitHub SCM framework commit is malformed")
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
    profile = _json("acceptance/v08-native-conformance.json")
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
    changed = set(
        filter(
            None,
            _git_output(["diff", "--name-only", f"{framework_commit}..HEAD"]).splitlines(),
        )
    )
    unexpected = sorted(changed - POST_EVIDENCE_ALLOWED_PATHS)
    if unexpected:
        raise ReleaseAuditError(
            "implementation changed after live SCM evidence: " + ", ".join(unexpected)
        )
    report["post_evidence_paths"] = len(changed)
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
    parser.add_argument("--since-tag", default="v0.7.0")
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
