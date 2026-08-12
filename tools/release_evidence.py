#!/usr/bin/env python3
"""Build immutable evidence that is knowable inside an exact tag workflow.

This module deliberately cannot declare a release accepted.  Publication facts
that happen after the tag workflow are owned by ``release_publication.py``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
import tempfile
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.json_support import loads_strict  # noqa: E402
from core.schema_validation import validate_schema  # noqa: E402
from core.security import find_inline_secret  # noqa: E402

SCHEMA = ROOT / "schemas/release-evidence.schema.json"
EVIDENCE_ASSETS = {
    "v10-candidate-conformance": "acceptance/v10-host-native-conformance.json",
    "sbom": "sbom/agent-team-engineering.spdx.json",
    "source-provenance": "supply-chain/source-provenance.json",
    "external-scm-first-run": "acceptance/github-scm-v10-first-run.json",
    "external-scm-replay": "acceptance/github-scm-v10-replay.json",
}
VERIFIED_COMMANDS = (
    "tools/verify.sh",
    "python3 tools/release_audit.py --since-tag v0.9.0 --require-external-evidence",
    "tools/release-smoke.sh",
    "python3 tools/release_evidence.py",
)
GATE_IDS = (
    "repository-validation",
    "unit-tests",
    "writer-authority",
    "host-lifecycle",
    "instance-migration",
    "skills-plugins",
    "isolated-hosts",
    "cold-start",
    "release-smoke",
    "external-scm",
    "supply-chain",
    "public-documentation",
    "pull-request",
    "independent-review",
    "merged-main",
    "annotated-tag",
    "tag-workflow",
    "evidence-artifact-download",
    "github-release",
    "anonymous-install",
)
LOCAL_GATE_IDS = GATE_IDS[:12]
POST_TAG_GATE_IDS = GATE_IDS[12:]


class ReleaseEvidenceError(RuntimeError):
    pass


def _git(*arguments: str) -> str:
    try:
        return subprocess.run(
            ["git", *arguments],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
            shell=False,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        raise ReleaseEvidenceError("cannot verify exact release Git identity") from None


def _tracked_asset_bytes(relative: str) -> bytes:
    path = ROOT / relative
    if not path.is_file() or path.is_symlink():
        raise ReleaseEvidenceError(f"release evidence asset is missing or unsafe: {relative}")
    try:
        tagged = subprocess.run(
            ["git", "show", f"HEAD:{relative}"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            timeout=30,
            shell=False,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        raise ReleaseEvidenceError(f"release evidence asset is not bound to HEAD: {relative}") from None
    if path.read_bytes() != tagged:
        raise ReleaseEvidenceError(f"release evidence asset differs from HEAD: {relative}")
    return tagged


def _artifact(kind: str, relative: str) -> dict[str, Any]:
    content = _tracked_asset_bytes(relative)
    return {
        "kind": kind,
        "path": relative,
        "bundle_path": f"bundle/{relative}",
        "sha256": "sha256:" + hashlib.sha256(content).hexdigest(),
        "size_bytes": len(content),
    }


def _empty_publication(tag: str, tag_object: str, commit: str, environment: dict[str, str]) -> dict[str, Any]:
    run_id = environment["GITHUB_RUN_ID"]
    run_attempt = environment["GITHUB_RUN_ATTEMPT"]
    run_url = f"https://github.com/90le/agent-team-engineering/actions/runs/{run_id}"
    return {
        "pull_request": {
            "status": "NOT_RUN",
            "number": None,
            "url": None,
            "head_commit": None,
            "checks_url": None,
        },
        "independent_review": {
            "status": "NOT_RUN",
            "reviewer": None,
            "url": None,
        },
        "merged_main": {
            "status": "NOT_RUN",
            "commit": None,
            "workflow_url": None,
        },
        "annotated_tag": {
            "status": "PASS",
            "name": tag,
            "object_type": "tag",
            "object_id": tag_object,
            "peeled_commit": commit,
        },
        "tag_workflow": {
            "status": "NOT_RUN",
            "provider": "github.actions",
            "run_id": run_id,
            "run_attempt": run_attempt,
            "url": run_url,
        },
        "evidence_artifact": {
            "status": "NOT_RUN",
            "name": f"release-evidence-{tag}",
            "id": None,
            "url": None,
            "archive_download_url": None,
            "digest": None,
            "retention_days": None,
            "created_at": None,
            "expires_at": None,
            "download_status": "NOT_RUN",
            "downloaded_at": None,
            "downloaded_archive_digest": None,
            "tag_evidence_sha256": None,
            "checksums_sha256": None,
        },
        "github_release": {
            "status": "NOT_RUN",
            "url": None,
            "tag": None,
            "draft": None,
            "prerelease": None,
        },
        "anonymous_install": {
            "status": "NOT_RUN",
            "workflow_url": None,
            "source_url": None,
            "tag": None,
            "tag_object": None,
            "commit": None,
            "verified_at": None,
            "commands": [],
            "maintainer_credentials_available": None,
            "external_writes": None,
        },
    }


def _default_local_gate_evidence(assets: list[dict[str, Any]]) -> dict[str, list[str]]:
    by_kind = {record["kind"]: record for record in assets}
    if set(by_kind) != set(EVIDENCE_ASSETS):
        raise ReleaseEvidenceError("release evidence asset kinds are incomplete")
    candidate_record = by_kind["v10-candidate-conformance"]
    candidate_content = _tracked_asset_bytes(candidate_record["path"])
    candidate = loads_strict(candidate_content)
    if not isinstance(candidate, dict) or candidate.get("status") != "PRE_RELEASE":
        raise ReleaseEvidenceError("v1.0 candidate conformance is malformed")
    local = candidate.get("local_gates")
    if not isinstance(local, dict):
        raise ReleaseEvidenceError("v1.0 candidate conformance lacks local gates")
    required = {
        "repository_validation",
        "unit_tests",
        "writer_authority",
        "host_lifecycle",
        "instance_migration",
        "skills_and_plugins",
        "isolated_hosts",
        "cold_start",
        "release_smoke",
        "external_scm",
    }
    if set(local) != required or any(
        not isinstance(local[name], dict) or local[name].get("status") != "PASS"
        for name in required
    ):
        raise ReleaseEvidenceError("tag workflow requires every source candidate gate to be PASS")
    expected_scm = {
        EVIDENCE_ASSETS["external-scm-first-run"],
        EVIDENCE_ASSETS["external-scm-replay"],
    }
    if set(local["external_scm"].get("evidence_files", [])) != expected_scm:
        raise ReleaseEvidenceError("candidate external SCM evidence paths are incomplete")
    candidate_ref = f"{candidate_record['path']}@{candidate_record['sha256']}"
    return {
        "repository-validation": ["tools/verify.sh", candidate_ref],
        "unit-tests": ["tools/verify.sh", candidate_ref],
        "writer-authority": [candidate_ref],
        "host-lifecycle": [candidate_ref],
        "instance-migration": [candidate_ref],
        "skills-plugins": [candidate_ref],
        "isolated-hosts": [candidate_ref],
        "cold-start": [candidate_ref],
        "release-smoke": ["tools/release-smoke.sh", candidate_ref],
        "external-scm": [
            f"{by_kind['external-scm-first-run']['path']}@{by_kind['external-scm-first-run']['sha256']}",
            f"{by_kind['external-scm-replay']['path']}@{by_kind['external-scm-replay']['sha256']}",
        ],
        "supply-chain": [
            f"{by_kind['sbom']['path']}@{by_kind['sbom']['sha256']}",
            f"{by_kind['source-provenance']['path']}@{by_kind['source-provenance']['sha256']}",
        ],
        "public-documentation": ["./agent-team validate"],
    }


def validate_release_evidence(document: dict[str, Any]) -> None:
    schema = loads_strict(SCHEMA.read_text(encoding="utf-8"))
    issues = validate_schema(document, schema)
    if issues:
        details = "; ".join(f"{issue.path}: {issue.message}" for issue in issues)
        raise ReleaseEvidenceError(f"release evidence violates schema: {details}")
    secret_path = find_inline_secret(document)
    if secret_path is not None:
        raise ReleaseEvidenceError(f"release evidence contains secret-like data at {secret_path}")

    if document["release"] != document["tag"]:
        raise ReleaseEvidenceError("release and tag identity differ")
    gate_map = {record["id"]: record for record in document["gates"]}
    if len(gate_map) != len(document["gates"]) or tuple(gate_map) != GATE_IDS:
        raise ReleaseEvidenceError("release evidence gate set or order differs")
    asset_map = {record["kind"]: record for record in document["assets"]}
    if len(asset_map) != len(document["assets"]) or set(asset_map) != set(EVIDENCE_ASSETS):
        raise ReleaseEvidenceError("release evidence asset set differs")
    for kind, relative in EVIDENCE_ASSETS.items():
        if asset_map[kind]["path"] != relative or asset_map[kind]["bundle_path"] != f"bundle/{relative}":
            raise ReleaseEvidenceError(f"release evidence asset identity differs: {kind}")

    publication = document["publication"]
    tag_record = publication["annotated_tag"]
    if (
        tag_record["name"] != document["tag"]
        or tag_record["object_id"] != document["tag_object"]
        or tag_record["peeled_commit"] != document["commit"]
    ):
        raise ReleaseEvidenceError("annotated tag fields do not bind the release identity")

    if document["evidence_kind"] == "TAG_WORKFLOW_EVIDENCE":
        if document["status"] != "PARTIAL" or document["release_status"] != "NOT_PUBLISHED":
            raise ReleaseEvidenceError("tag workflow evidence cannot declare publication accepted")
        if any(gate_map[name]["status"] != "PASS" for name in LOCAL_GATE_IDS):
            raise ReleaseEvidenceError("tag workflow local gates must all be PASS")
        if gate_map["annotated-tag"]["status"] != "PASS":
            raise ReleaseEvidenceError("tag workflow must verify the annotated tag locally")
        not_yet = set(POST_TAG_GATE_IDS) - {"annotated-tag"}
        if any(gate_map[name]["status"] != "NOT_RUN" for name in not_yet):
            raise ReleaseEvidenceError("tag workflow cannot self-report post-tag gates")
        if publication["tag_workflow"]["status"] != "NOT_RUN":
            raise ReleaseEvidenceError("a running tag workflow cannot self-report completion")
        for key in ("pull_request", "independent_review", "merged_main", "evidence_artifact", "github_release", "anonymous_install"):
            if publication[key]["status"] != "NOT_RUN":
                raise ReleaseEvidenceError(f"tag workflow cannot self-report {key}")
    else:
        if document["status"] != "ACCEPTED" or document["release_status"] != "RELEASED":
            raise ReleaseEvidenceError("final release index must be ACCEPTED and RELEASED")
        if any(record["status"] != "PASS" for record in document["gates"]):
            raise ReleaseEvidenceError("final release index contains a non-PASS gate")
        for key, record in publication.items():
            if key == "anonymous_install" and record["status"] == "PASS":
                continue
            if record["status"] != "PASS":
                raise ReleaseEvidenceError(f"final publication evidence is incomplete: {key}")
        if publication["evidence_artifact"]["download_status"] != "PASS":
            raise ReleaseEvidenceError("final index requires an actually downloaded evidence artifact")


def build_release_evidence(
    environment: dict[str, str],
    *,
    generated_at: datetime | None = None,
    tag_object: str | None = None,
    commit: str | None = None,
    artifacts: list[dict[str, Any]] | None = None,
    local_gate_evidence: dict[str, list[str]] | None = None,
) -> dict[str, Any]:
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    tag = f"v{version}"
    repository = environment.get("GITHUB_REPOSITORY", "")
    if repository != "90le/agent-team-engineering":
        raise ReleaseEvidenceError("release evidence repository identity differs")
    if environment.get("GITHUB_REF_TYPE") != "tag" or environment.get("GITHUB_REF_NAME") != tag:
        raise ReleaseEvidenceError("release evidence requires the exact version tag ref")
    run_id = environment.get("GITHUB_RUN_ID", "")
    run_attempt = environment.get("GITHUB_RUN_ATTEMPT", "")
    if not run_id.isdigit() or not run_attempt.isdigit():
        raise ReleaseEvidenceError("release evidence lacks GitHub Actions run identity")

    actual_tag_object = tag_object if tag_object is not None else _git("rev-parse", f"refs/tags/{tag}")
    actual_commit = commit if commit is not None else _git("rev-parse", f"{tag}^{{}}")
    if tag_object is None and _git("cat-file", "-t", f"refs/tags/{tag}") != "tag":
        raise ReleaseEvidenceError("release ref is not an annotated tag")
    if commit is None and actual_commit != _git("rev-parse", "HEAD"):
        raise ReleaseEvidenceError("release tag does not peel to the checked-out commit")

    observed = (generated_at or datetime.now(timezone.utc)).replace(microsecond=0)
    asset_records = artifacts if artifacts is not None else [
        _artifact(kind, path) for kind, path in EVIDENCE_ASSETS.items()
    ]
    if any(not isinstance(record, dict) or "kind" not in record for record in asset_records):
        raise ReleaseEvidenceError("release evidence asset record lacks a declared kind")
    local_evidence = local_gate_evidence or _default_local_gate_evidence(asset_records)
    if set(local_evidence) != set(LOCAL_GATE_IDS):
        raise ReleaseEvidenceError("local release gate evidence is incomplete")
    publication = _empty_publication(tag, actual_tag_object, actual_commit, environment)
    gates = [
        {"id": gate_id, "status": "PASS", "evidence": local_evidence[gate_id]}
        for gate_id in LOCAL_GATE_IDS
    ]
    gates.extend(
        {
            "id": gate_id,
            "status": "PASS" if gate_id == "annotated-tag" else "NOT_RUN",
            "evidence": [f"refs/tags/{tag}@{actual_tag_object}", actual_commit]
            if gate_id == "annotated-tag"
            else [],
        }
        for gate_id in POST_TAG_GATE_IDS
    )
    document = {
        "$schema": "schemas/release-evidence.schema.json",
        "schema_version": "2.0.0",
        "evidence_kind": "TAG_WORKFLOW_EVIDENCE",
        "status": "PARTIAL",
        "release_status": "NOT_PUBLISHED",
        "release": tag,
        "repository": repository,
        "tag": tag,
        "tag_object": actual_tag_object,
        "commit": actual_commit,
        "generated_at": observed.isoformat().replace("+00:00", "Z"),
        "environment": {
            "runner_os": environment.get("RUNNER_OS", "unknown"),
            "python_version": platform.python_version(),
        },
        "commands": [{"command": command, "exit_code": 0} for command in VERIFIED_COMMANDS],
        "assets": asset_records,
        "publication": publication,
        "gates": gates,
        "boundaries": {
            "automatic_merge": False,
            "automatic_deploy": False,
            "production_credentials_read": False,
            "tagged_source_modified": False,
            "github_api_writes": False,
        },
    }
    validate_release_evidence(document)
    return document


def write_release_evidence(
    document: dict[str, Any],
    output: Path,
    checksums: Path,
    *,
    asset_loader: Callable[[str], bytes] = _tracked_asset_bytes,
) -> None:
    validate_release_evidence(document)
    loaded: list[tuple[dict[str, Any], bytes]] = []
    for record in document["assets"]:
        content = asset_loader(record["path"])
        digest = hashlib.sha256(content).hexdigest()
        if record["sha256"] != f"sha256:{digest}" or record["size_bytes"] != len(content):
            raise ReleaseEvidenceError(f"release evidence asset changed: {record['path']}")
        bundle_relative = Path(record["bundle_path"])
        if bundle_relative.is_absolute() or ".." in bundle_relative.parts:
            raise ReleaseEvidenceError("release evidence bundle path is unsafe")
        loaded.append((record, content))

    output.parent.mkdir(parents=True, exist_ok=True)
    checksums.parent.mkdir(parents=True, exist_ok=True)
    if output.parent.resolve() != checksums.parent.resolve():
        raise ReleaseEvidenceError("release evidence and SHA256SUMS must share one bundle root")
    document_bytes = (json.dumps(document, indent=2, sort_keys=True) + "\n").encode("utf-8")
    records = [
        (hashlib.sha256(content).hexdigest(), record["bundle_path"])
        for record, content in loaded
    ]
    records.append((hashlib.sha256(document_bytes).hexdigest(), output.name))
    checksum_bytes = "".join(
        f"{digest}  {path}\n" for digest, path in sorted(records, key=lambda item: item[1])
    ).encode("utf-8")

    with tempfile.TemporaryDirectory(dir=output.parent) as temporary:
        stage = Path(temporary)
        for record, content in loaded:
            bundled = stage / record["bundle_path"]
            bundled.parent.mkdir(parents=True, exist_ok=True)
            bundled.write_bytes(content)
        (stage / output.name).write_bytes(document_bytes)
        (stage / checksums.name).write_bytes(checksum_bytes)
        for path in sorted(stage.rglob("*")):
            if path.is_dir():
                continue
            relative = path.relative_to(stage)
            destination = output.parent / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            os.replace(path, destination)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--checksums", type=Path, required=True)
    arguments = parser.parse_args()
    try:
        document = build_release_evidence(dict(os.environ))
        write_release_evidence(document, arguments.output, arguments.checksums)
    except (OSError, ValueError, ReleaseEvidenceError) as error:
        print(f"release evidence refused or failed: {error}", file=sys.stderr)
        return 2
    print(json.dumps({"status": document["status"], "tag": document["tag"], "commit": document["commit"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
