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
import re
import subprocess
import sys
import tempfile
import urllib.parse
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
    "python3 tools/release_evidence.py --output artifacts/release-evidence.json --checksums artifacts/SHA256SUMS",
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
    "technical-review",
    "owner-approval",
    "merged-main",
    "annotated-tag",
    "tag-workflow",
    "evidence-artifact-download",
    "github-release",
    "anonymous-install",
)
LOCAL_GATE_IDS = GATE_IDS[:12]
POST_TAG_GATE_IDS = GATE_IDS[12:]
REVIEW_WORKFLOW_COMMIT = "3e4de527cf6a721c16f3b4c93527ca3b3ae99a66"
REVIEW_RUNTIME = "openclaw/relay/gpt-5.6-sol"
RELEASE_OWNER_LOGIN = "90le"
RELEASE_OWNER_ID = 68719118
DIGEST = re.compile(r"^sha256:[a-f0-9]{64}$")
COMMIT = re.compile(r"^[a-f0-9]{40}$")
FINAL_COMMANDS = (
    "GitHub REST read-only publication verification",
    "download and verify release-evidence artifact",
    "verify SHA256SUMS and bundled evidence",
    "download and byte-verify live external SCM artifacts",
    "anonymous exact-tag install and lifecycle verification",
)
ANONYMOUS_COMMANDS = (
    "git clone --no-local --no-checkout https://github.com/90le/agent-team-engineering.git <temporary>",
    "git verify annotated tag object and peeled commit",
    "git checkout --detach <peeled-tag-commit>; verify clean exact HEAD",
    "factory install; factory verify; doctor",
    "create and validate portable team",
    "host plan; preview; confirm; apply; verify; uninstall-preview; uninstall; replay",
    "native writer-authority-validate",
)


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
            "checks": [],
            "merged_at": None,
        },
        "technical_review": {
            "status": "NOT_RUN",
            "head_commit": None,
            "head_tree": None,
            "workflow_commit": None,
            "reviewer_kind": None,
            "reviewer_runtime": None,
            "evidence_url": None,
            "evidence_sha256": None,
            "decision": "NOT_RUN",
            "authenticated_human": False,
            "generated_at": None,
            "completed_at": None,
        },
        "owner_approval": {
            "status": "NOT_RUN",
            "head_commit": None,
            "reviewer": None,
            "reviewer_kind": None,
            "url": None,
            "decision": "NOT_RUN",
            "submitted_at": None,
        },
        "merged_main": {
            "status": "NOT_RUN",
            "ref": None,
            "commit": None,
            "tree": None,
            "checks": [],
        },
        "annotated_tag": {
            "status": "PASS",
            "name": tag,
            "object_type": "tag",
            "object_id": tag_object,
            "peeled_commit": commit,
            "tagger_name": None,
            "tagger_email": None,
            "tagged_at": None,
            "signature_verified": None,
            "signature_reason": None,
        },
        "tag_workflow": {
            "status": "NOT_RUN",
            "provider": "github.actions",
            "run_id": run_id,
            "run_attempt": run_attempt,
            "url": run_url,
            "actor": None,
            "actor_id": None,
            "completed_at": None,
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
            "author": None,
            "author_id": None,
            "published_at": None,
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
            "unauthenticated_git_transport": None,
            "caller_credentials_inherited": None,
            "same_uid_filesystem_isolated": None,
            "write_isolation": None,
            "external_writes_verified": None,
        },
    }


def _valid_app_id(value: Any) -> bool:
    """Accept an exact App, explicit any-App rule, or legacy unbound context."""

    return value is None or (
        isinstance(value, int) and not isinstance(value, bool) and (value == -1 or value > 0)
    )


def _evidence_time(value: Any, label: str) -> datetime:
    if not isinstance(value, str):
        raise ReleaseEvidenceError(f"{label} time is missing")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ReleaseEvidenceError(f"{label} time is invalid") from None
    if parsed.tzinfo is None:
        raise ReleaseEvidenceError(f"{label} time lacks timezone")
    return parsed


def _https_evidence_url(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ReleaseEvidenceError(f"{label} URL is missing")
    parsed = urllib.parse.urlsplit(value)
    try:
        port = parsed.port
    except ValueError:
        raise ReleaseEvidenceError(f"{label} URL has an invalid port") from None
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or port not in {None, 443}
        or parsed.fragment
    ):
        raise ReleaseEvidenceError(f"{label} URL is not exact HTTPS evidence")
    return value


def _digest(value: Any, label: str) -> str:
    if not isinstance(value, str) or DIGEST.fullmatch(value) is None:
        raise ReleaseEvidenceError(f"{label} digest is missing or invalid")
    return value


def _retention_days(created: datetime, expires: datetime) -> int:
    """Recompute the GitHub artifact retention value recorded by the finalizer."""

    seconds = (expires - created).total_seconds()
    if seconds <= 0:
        raise ReleaseEvidenceError("release evidence artifact expiry must follow creation")
    return max(1, int(round(seconds / 86400)))


def _expected_local_gate_evidence(
    asset_map: dict[str, dict[str, Any]],
) -> dict[str, list[str]]:
    candidate = asset_map["v10-candidate-conformance"]
    candidate_ref = f"{candidate['path']}@{candidate['sha256']}"
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
            f"{asset_map['external-scm-first-run']['path']}@{asset_map['external-scm-first-run']['sha256']}",
            f"{asset_map['external-scm-replay']['path']}@{asset_map['external-scm-replay']['sha256']}",
        ],
        "supply-chain": [
            f"{asset_map['sbom']['path']}@{asset_map['sbom']['sha256']}",
            f"{asset_map['source-provenance']['path']}@{asset_map['source-provenance']['sha256']}",
        ],
        "public-documentation": ["./agent-team validate"],
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
    return _expected_local_gate_evidence(by_kind)


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
    pull_request = publication["pull_request"]
    technical_review = publication["technical_review"]
    owner_approval = publication["owner_approval"]
    merged_main = publication["merged_main"]
    anonymous_install = publication["anonymous_install"]
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
        for key in ("pull_request", "technical_review", "owner_approval", "merged_main", "evidence_artifact", "github_release", "anonymous_install"):
            if publication[key]["status"] != "NOT_RUN":
                raise ReleaseEvidenceError(f"tag workflow cannot self-report {key}")
        if pull_request["checks"] or merged_main["checks"]:
            raise ReleaseEvidenceError("tag workflow cannot self-report pull request or merged-main checks")
        if (
            any(
                pull_request[field] is not None
                for field in ("number", "url", "head_commit", "merged_at")
            )
            or any(
                technical_review[field] is not None
                for field in (
                    "head_commit",
                    "head_tree",
                    "workflow_commit",
                    "reviewer_kind",
                    "reviewer_runtime",
                    "evidence_url",
                    "evidence_sha256",
                    "generated_at",
                    "completed_at",
                )
            )
            or technical_review["decision"] != "NOT_RUN"
            or technical_review["authenticated_human"] is not False
            or any(
                owner_approval[field] is not None
                for field in (
                    "head_commit",
                    "reviewer",
                    "reviewer_kind",
                    "url",
                    "submitted_at",
                )
            )
            or owner_approval["decision"] != "NOT_RUN"
            or merged_main["ref"] is not None
            or merged_main["commit"] is not None
            or merged_main["tree"] is not None
            or any(
                tag_record[field] is not None
                for field in (
                    "tagger_name",
                    "tagger_email",
                    "tagged_at",
                    "signature_verified",
                    "signature_reason",
                )
            )
            or any(
                publication["tag_workflow"][field] is not None
                for field in ("actor", "actor_id", "completed_at")
            )
            or any(
                publication["github_release"][field] is not None
                for field in ("author", "author_id", "published_at")
            )
            or any(
                anonymous_install[field] is not None
                for field in (
                    "workflow_url",
                    "source_url",
                    "tag",
                    "tag_object",
                    "commit",
                    "verified_at",
                    "unauthenticated_git_transport",
                    "caller_credentials_inherited",
                    "same_uid_filesystem_isolated",
                    "write_isolation",
                    "external_writes_verified",
                )
            )
            or anonymous_install["commands"]
        ):
            raise ReleaseEvidenceError("tag workflow cannot self-report review, owner, or anonymous-install facts")
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
        if [record["command"] for record in document["commands"]] != list(FINAL_COMMANDS):
            raise ReleaseEvidenceError("final index command evidence differs")
        expected_pr_url = (
            f"https://github.com/90le/agent-team-engineering/pull/{pull_request['number']}"
        )
        if (
            not isinstance(pull_request["number"], int)
            or pull_request["url"] != expected_pr_url
            or COMMIT.fullmatch(str(pull_request["head_commit"])) is None
        ):
            raise ReleaseEvidenceError("final index pull-request identity differs")
        technical_url = _https_evidence_url(
            technical_review["evidence_url"], "technical review"
        )
        if re.fullmatch(
            r"https://github\.com/90le/agent-team-v10-review-private/actions/runs/[1-9][0-9]*",
            technical_url,
        ) is None:
            raise ReleaseEvidenceError("technical review run URL differs")
        _digest(technical_review["evidence_sha256"], "technical review")
        owner_url = owner_approval["url"]
        if not isinstance(owner_url, str) or re.fullmatch(
            rf"{re.escape(expected_pr_url)}#pullrequestreview-[1-9][0-9]*",
            owner_url,
        ) is None:
            raise ReleaseEvidenceError("owner approval URL differs from pull request")
        tag_workflow = publication["tag_workflow"]
        tag_run_url = _https_evidence_url(tag_workflow["url"], "tag workflow")
        if (
            not isinstance(tag_workflow["run_id"], str)
            or not tag_workflow["run_id"].isdigit()
            or tag_workflow["run_attempt"] != "1"
            or tag_run_url
            != f"https://github.com/90le/agent-team-engineering/actions/runs/{tag_workflow['run_id']}"
        ):
            raise ReleaseEvidenceError("tag workflow identity differs")
        artifact = publication["evidence_artifact"]
        artifact_id = artifact["id"]
        artifact_base = (
            "https://api.github.com/repos/90le/agent-team-engineering/"
            f"actions/artifacts/{artifact_id}"
        )
        artifact_digests = (
            "digest",
            "downloaded_archive_digest",
            "tag_evidence_sha256",
            "checksums_sha256",
        )
        if (
            not isinstance(artifact_id, int)
            or isinstance(artifact_id, bool)
            or artifact_id < 1
            or artifact["name"] != f"release-evidence-{document['tag']}"
            or artifact["url"] != artifact_base
            or artifact["archive_download_url"] != f"{artifact_base}/zip"
            or any(
                not isinstance(artifact.get(field), str)
                or DIGEST.fullmatch(artifact[field]) is None
                for field in artifact_digests
            )
            or artifact["digest"] != artifact["downloaded_archive_digest"]
            or not isinstance(artifact["retention_days"], int)
            or isinstance(artifact["retention_days"], bool)
            or artifact["retention_days"] < 1
        ):
            raise ReleaseEvidenceError("final index release-evidence artifact differs")
        github_release = publication["github_release"]
        expected_release_url = (
            "https://github.com/90le/agent-team-engineering/releases/tag/"
            + document["tag"]
        )
        if (
            github_release["url"] != expected_release_url
            or github_release["tag"] != document["tag"]
            or github_release["draft"] is not False
            or github_release["prerelease"] is not False
        ):
            raise ReleaseEvidenceError("final index GitHub Release identity differs")
        if (
            anonymous_install["unauthenticated_git_transport"] is not True
            or anonymous_install["caller_credentials_inherited"] is not False
            or anonymous_install["same_uid_filesystem_isolated"] is not False
            or anonymous_install["write_isolation"] is not False
            or anonymous_install["external_writes_verified"] is not False
        ):
            raise ReleaseEvidenceError(
                "final index anonymous installation boundary differs from the exact transport and process contract"
            )
        if (
            anonymous_install["workflow_url"] is not None
            or anonymous_install["source_url"]
            != "https://github.com/90le/agent-team-engineering.git"
            or anonymous_install["tag"] != document["tag"]
            or anonymous_install["tag_object"] != document["tag_object"]
            or anonymous_install["commit"] != document["commit"]
            or tuple(anonymous_install["commands"]) != ANONYMOUS_COMMANDS
            or not anonymous_install["verified_at"]
        ):
            raise ReleaseEvidenceError("final index anonymous-install identity differs")
        check_sets: dict[str, set[tuple[str, int | None]]] = {}
        for label, checks in (
            ("pull request", pull_request["checks"]),
            ("merged main", merged_main["checks"]),
        ):
            names = [record["name"] for record in checks]
            urls = [record["url"] for record in checks]
            if (
                not checks
                or any(not _valid_app_id(record["app_id"]) for record in checks)
                or any(not record.get("completed_at") for record in checks)
                or any(
                    not isinstance(record.get("url"), str)
                    or not record["url"].startswith("https://")
                    for record in checks
                )
                or len(set(names)) != len(checks)
                or len(set(urls)) != len(checks)
            ):
                raise ReleaseEvidenceError(f"final index requires the exact unique {label} required-check set")
            check_sets[label] = {
                (record["name"], record["app_id"]) for record in checks
            }
        if check_sets["pull request"] != check_sets["merged main"]:
            raise ReleaseEvidenceError("pull-request and merged-main required-check identities differ")
        if (
            merged_main["ref"] != "refs/heads/main"
            or merged_main["commit"] != document["commit"]
            or COMMIT.fullmatch(str(merged_main["tree"])) is None
        ):
            raise ReleaseEvidenceError("merged-main checks do not bind the accepted commit")
        if (
            tag_record["object_type"] != "tag"
            or COMMIT.fullmatch(str(tag_record["object_id"])) is None
            or COMMIT.fullmatch(str(tag_record["peeled_commit"])) is None
        ):
            raise ReleaseEvidenceError("annotated tag object identity is invalid")
        head_commit = pull_request["head_commit"]
        if (
            not head_commit
            or not pull_request["merged_at"]
            or technical_review["head_commit"] != head_commit
            or COMMIT.fullmatch(str(technical_review["head_tree"])) is None
            or technical_review["head_tree"] != merged_main["tree"]
            or technical_review["workflow_commit"] != REVIEW_WORKFLOW_COMMIT
            or technical_review["reviewer_kind"] != "independent-ai"
            or technical_review["reviewer_runtime"] != REVIEW_RUNTIME
            or not technical_review["evidence_url"]
            or not technical_review["evidence_sha256"]
            or technical_review["decision"] != "PASS"
            or technical_review["authenticated_human"] is not False
            or not technical_review["generated_at"]
            or not technical_review["completed_at"]
        ):
            raise ReleaseEvidenceError("final index lacks exact-head external technical review evidence")
        if (
            owner_approval["head_commit"] != head_commit
            or owner_approval["reviewer"] != RELEASE_OWNER_LOGIN
            or owner_approval["reviewer_kind"] != "github-user"
            or not owner_approval["url"]
            or owner_approval["decision"] != "APPROVED"
            or not owner_approval["submitted_at"]
        ):
            raise ReleaseEvidenceError("final index lacks exact-head GitHub User owner approval")
        if (
            not tag_record["tagger_name"]
            or not tag_record["tagger_email"]
            or not tag_record["tagged_at"]
            or not isinstance(tag_record["signature_verified"], bool)
            or not tag_record["signature_reason"]
            or publication["tag_workflow"]["actor"] != RELEASE_OWNER_LOGIN
            or publication["tag_workflow"]["actor_id"] != RELEASE_OWNER_ID
            or not publication["tag_workflow"]["completed_at"]
            or publication["github_release"]["author"] != RELEASE_OWNER_LOGIN
            or publication["github_release"]["author_id"] != RELEASE_OWNER_ID
            or not publication["github_release"]["published_at"]
        ):
            raise ReleaseEvidenceError("final index lacks the trusted release-owner identity chain")
        expected_gate_evidence = _expected_local_gate_evidence(asset_map)
        external_scm_evidence = gate_map["external-scm"]["evidence"]
        expected_external_prefix = expected_gate_evidence["external-scm"]
        live_external = external_scm_evidence[len(expected_external_prefix) :]
        if (
            external_scm_evidence[: len(expected_external_prefix)]
            != expected_external_prefix
            or len(live_external) != 4
            or len(set(live_external)) != 4
            or any(
                re.fullmatch(
                    r"https://github\.com/90le/agent-team-v10-conformance-private/actions/runs/[1-9][0-9]*",
                    value,
                )
                is None
                for value in live_external[::2]
            )
            or any(
                re.fullmatch(
                    r"https://api\.github\.com/repos/90le/agent-team-v10-conformance-private/actions/artifacts/[1-9][0-9]*@sha256:[a-f0-9]{64}",
                    value,
                )
                is None
                for value in live_external[1::2]
            )
        ):
            raise ReleaseEvidenceError(
                "final index lacks live byte-bound external SCM evidence"
            )
        expected_gate_evidence["external-scm"] = external_scm_evidence
        expected_gate_evidence.update(
            {
                "pull-request": [
                    pull_request["url"],
                    *(
                        f"{record['url']}@{record['completed_at']}"
                        for record in pull_request["checks"]
                    ),
                ],
                "technical-review": [
                    technical_review["evidence_url"],
                    technical_review["evidence_sha256"],
                    technical_review["head_tree"],
                ],
                "owner-approval": [owner_approval["url"]],
                "merged-main": [
                    *(
                        f"{record['url']}@{record['completed_at']}"
                        for record in merged_main["checks"]
                    ),
                    document["commit"],
                    merged_main["tree"],
                ],
                "annotated-tag": [
                    f"refs/tags/{document['tag']}@{document['tag_object']}",
                    document["commit"],
                ],
                "tag-workflow": [tag_workflow["url"]],
                "evidence-artifact-download": [
                    artifact["url"],
                    artifact["downloaded_archive_digest"],
                ],
                "github-release": [github_release["url"]],
                "anonymous-install": [
                    anonymous_install["source_url"],
                    anonymous_install["verified_at"],
                ],
            }
        )
        if any(
            gate_map[gate_id]["evidence"] != expected_gate_evidence[gate_id]
            for gate_id in GATE_IDS
        ):
            raise ReleaseEvidenceError("final index gate evidence mapping differs")
        merged_at = _evidence_time(pull_request["merged_at"], "pull request merge")
        technical_generated_at = _evidence_time(
            technical_review["generated_at"], "technical review generation"
        )
        technical_completed_at = _evidence_time(
            technical_review["completed_at"], "technical review completion"
        )
        owner_submitted_at = _evidence_time(
            owner_approval["submitted_at"], "owner approval"
        )
        tagged_at = _evidence_time(tag_record["tagged_at"], "annotated tag")
        tag_workflow_completed_at = _evidence_time(
            publication["tag_workflow"]["completed_at"], "tag workflow completion"
        )
        release_published_at = _evidence_time(
            publication["github_release"]["published_at"], "GitHub Release publication"
        )
        artifact_created_at = _evidence_time(
            artifact["created_at"], "release evidence artifact creation"
        )
        artifact_expires_at = _evidence_time(
            artifact["expires_at"], "release evidence artifact expiry"
        )
        downloaded_at = _evidence_time(
            artifact["downloaded_at"], "release evidence artifact download"
        )
        anonymous_verified_at = _evidence_time(
            anonymous_install["verified_at"], "anonymous exact-tag verification"
        )
        generated_at = _evidence_time(document["generated_at"], "final index generation")
        pull_check_times = [
            _evidence_time(record["completed_at"], "pull request required check")
            for record in pull_request["checks"]
        ]
        main_check_times = [
            _evidence_time(record["completed_at"], "merged main required check")
            for record in merged_main["checks"]
        ]
        if not (
            technical_generated_at <= technical_completed_at <= merged_at
            and all(value <= merged_at for value in pull_check_times)
            and owner_submitted_at <= merged_at <= tagged_at
            and all(merged_at <= value <= tagged_at for value in main_check_times)
            and tagged_at <= tag_workflow_completed_at <= release_published_at
            and tagged_at <= artifact_created_at <= tag_workflow_completed_at
            and artifact_created_at <= downloaded_at < artifact_expires_at
            and artifact["retention_days"]
            == _retention_days(artifact_created_at, artifact_expires_at)
            and release_published_at <= downloaded_at <= anonymous_verified_at <= generated_at
        ):
            raise ReleaseEvidenceError("final release chronology differs from the authority sequence")


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
        "schema_version": "2.1.0",
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
            "standalone_tamper_evident": False,
            "cryptographically_authenticated": False,
            "authenticity_verification": "REQUERY_GITHUB_AND_REVERIFY_ORIGINAL_ARTIFACTS",
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
