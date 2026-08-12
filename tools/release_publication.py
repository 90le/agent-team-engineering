#!/usr/bin/env python3
"""Finalize a v1 release from independently observed post-publication facts.

The finalizer is intentionally read-only toward GitHub.  It verifies live PR,
workflow, tag, artifact and Release identities, downloads the tag-workflow
artifact, and performs a fresh anonymous exact-tag installation before it can
emit an ACCEPTED/RELEASED index outside the tagged source tree.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
import zipfile
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.json_support import loads_strict  # noqa: E402
from core.security import find_inline_secret  # noqa: E402
from tools.release_evidence import (  # noqa: E402
    EVIDENCE_ASSETS,
    GATE_IDS,
    ReleaseEvidenceError,
    validate_release_evidence,
)

COMMIT = re.compile(r"^[a-f0-9]{40}$")
DIGEST = re.compile(r"^sha256:[a-f0-9]{64}$")
CHECKSUM_LINE = re.compile(r"^([a-f0-9]{64})  ([A-Za-z0-9._/-]+)$")
REPOSITORY = "90le/agent-team-engineering"
GITHUB_API = "https://api.github.com"
GITHUB_WEB = "https://github.com"
ANONYMOUS_COMMANDS = (
    "git clone --no-local --branch <tag> https://github.com/90le/agent-team-engineering.git <temporary>",
    "git verify annotated tag object and peeled commit",
    "factory install; factory verify; doctor",
    "create and validate portable team",
    "host plan; preview; confirm; apply; verify; uninstall-preview; uninstall; replay",
    "native writer-authority-validate",
)


class ReleasePublicationError(RuntimeError):
    pass


def _now(value: datetime | None = None) -> str:
    observed = (value or datetime.now(timezone.utc)).replace(microsecond=0)
    return observed.isoformat().replace("+00:00", "Z")


def _sha256(content: bytes) -> str:
    return "sha256:" + hashlib.sha256(content).hexdigest()


def _require_url(value: Any, prefix: str, label: str) -> str:
    if not isinstance(value, str) or not value.startswith(prefix):
        raise ReleasePublicationError(f"{label} URL is missing or outside the expected repository")
    return value


def _require_commit(value: Any, label: str) -> str:
    if not isinstance(value, str) or COMMIT.fullmatch(value) is None:
        raise ReleasePublicationError(f"{label} is not a full commit identity")
    return value


def load_finalization_request(path: Path) -> dict[str, Any]:
    try:
        value = loads_strict(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ReleasePublicationError(f"cannot read strict finalization request: {error}") from None
    if not isinstance(value, dict):
        raise ReleasePublicationError("finalization request root must be an object")
    allowed = {
        "repository",
        "release",
        "commit",
        "pull_request",
        "independent_review",
        "merged_main_workflow_url",
        "tag_workflow_url",
        "github_release_url",
    }
    if set(value) != allowed:
        raise ReleasePublicationError("finalization request fields differ from the exact public contract")
    if value.get("repository") != REPOSITORY:
        raise ReleasePublicationError("finalization request repository differs")
    release = value.get("release")
    if not isinstance(release, str) or re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+", release) is None:
        raise ReleasePublicationError("finalization request release is invalid")
    _require_commit(value.get("commit"), "accepted commit")
    pull_request = value.get("pull_request")
    if not isinstance(pull_request, dict) or set(pull_request) != {"number", "head_commit", "checks_url"}:
        raise ReleasePublicationError("finalization request pull_request is malformed")
    if not isinstance(pull_request.get("number"), int) or pull_request["number"] < 1:
        raise ReleasePublicationError("pull request number is invalid")
    _require_commit(pull_request.get("head_commit"), "pull request head")
    _require_url(
        pull_request.get("checks_url"),
        f"{GITHUB_WEB}/{REPOSITORY}/actions/runs/",
        "pull request checks",
    )
    review = value.get("independent_review")
    if not isinstance(review, dict) or set(review) != {"reviewer", "url"}:
        raise ReleasePublicationError("finalization request independent_review is malformed")
    if not isinstance(review.get("reviewer"), str) or not review["reviewer"].strip():
        raise ReleasePublicationError("independent reviewer is missing")
    _require_url(
        review.get("url"),
        f"{GITHUB_WEB}/{REPOSITORY}/pull/",
        "independent review",
    )
    for field, prefix in (
        ("merged_main_workflow_url", f"{GITHUB_WEB}/{REPOSITORY}/actions/runs/"),
        ("tag_workflow_url", f"{GITHUB_WEB}/{REPOSITORY}/actions/runs/"),
        ("github_release_url", f"{GITHUB_WEB}/{REPOSITORY}/releases/tag/{release}"),
    ):
        _require_url(value.get(field), prefix, field)
    if find_inline_secret(value) is not None:
        raise ReleasePublicationError("finalization request contains secret-like material")
    return value


def _github_json(path: str, token: str) -> Any:
    request = urllib.request.Request(
        f"{GITHUB_API}{path}",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "agent-team-release-finalizer",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return loads_strict(response.read())
    except (OSError, ValueError, urllib.error.HTTPError) as error:
        raise ReleasePublicationError(f"GitHub read failed for {path}: {error}") from None


def _github_download(url: str, token: str) -> bytes:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "agent-team-release-finalizer",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.read()
    except (OSError, urllib.error.HTTPError) as error:
        raise ReleasePublicationError(f"GitHub artifact download failed: {error}") from None


def fetch_publication_snapshot(request: dict[str, Any], token: str) -> dict[str, Any]:
    release = request["release"]
    commit = request["commit"]
    number = request["pull_request"]["number"]
    pull = _github_json(f"/repos/{REPOSITORY}/pulls/{number}", token)
    reviews = _github_json(f"/repos/{REPOSITORY}/pulls/{number}/reviews?per_page=100", token)
    tag_ref = _github_json(f"/repos/{REPOSITORY}/git/ref/tags/{release}", token)
    if not isinstance(tag_ref, dict) or not isinstance(tag_ref.get("object"), dict):
        raise ReleasePublicationError("annotated tag ref response is malformed")
    tag_object = _github_json(
        f"/repos/{REPOSITORY}/git/tags/{tag_ref['object'].get('sha', '')}", token
    )
    release_record = _github_json(f"/repos/{REPOSITORY}/releases/tags/{release}", token)
    tag_run_id = request["tag_workflow_url"].rstrip("/").rsplit("/", 1)[-1]
    main_run_id = request["merged_main_workflow_url"].rstrip("/").rsplit("/", 1)[-1]
    checks_run_id = request["pull_request"]["checks_url"].rstrip("/").rsplit("/", 1)[-1]
    tag_run = _github_json(f"/repos/{REPOSITORY}/actions/runs/{tag_run_id}", token)
    main_run = _github_json(f"/repos/{REPOSITORY}/actions/runs/{main_run_id}", token)
    checks_run = _github_json(f"/repos/{REPOSITORY}/actions/runs/{checks_run_id}", token)
    artifacts = _github_json(f"/repos/{REPOSITORY}/actions/runs/{tag_run_id}/artifacts", token)
    return {
        "pull_request": pull,
        "reviews": reviews,
        "tag_ref": tag_ref,
        "tag_object": tag_object,
        "release": release_record,
        "tag_workflow": tag_run,
        "main_workflow": main_run,
        "checks_workflow": checks_run,
        "artifacts": artifacts,
        "expected_commit": commit,
    }


def _parse_datetime(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ReleasePublicationError(f"invalid GitHub date-time: {value}") from None
    if parsed.tzinfo is None:
        raise ReleasePublicationError(f"GitHub date-time lacks timezone: {value}")
    return parsed


def _retention_days(created: str, expires: str) -> int:
    seconds = (_parse_datetime(expires) - _parse_datetime(created)).total_seconds()
    if seconds <= 0:
        raise ReleasePublicationError("artifact expiry does not follow creation")
    return max(1, int(round(seconds / 86400)))


def verify_publication_snapshot(
    request: dict[str, Any], snapshot: dict[str, Any]
) -> dict[str, Any]:
    commit = request["commit"]
    release = request["release"]
    pull = snapshot.get("pull_request")
    if not isinstance(pull, dict):
        raise ReleasePublicationError("pull request evidence is missing")
    expected_pr_url = f"{GITHUB_WEB}/{REPOSITORY}/pull/{request['pull_request']['number']}"
    if (
        pull.get("html_url") != expected_pr_url
        or pull.get("state") != "closed"
        or pull.get("merged") is not True
        or pull.get("merge_commit_sha") != commit
        or not isinstance(pull.get("head"), dict)
        or pull["head"].get("sha") != request["pull_request"]["head_commit"]
    ):
        raise ReleasePublicationError("pull request does not bind head and accepted merge commit")
    checks_run = snapshot.get("checks_workflow")
    if not _successful_run(checks_run, request["pull_request"]["head_commit"], request["pull_request"]["checks_url"]):
        raise ReleasePublicationError("pull request checks are not successful for the exact head")
    main_run = snapshot.get("main_workflow")
    if not _successful_run(main_run, commit, request["merged_main_workflow_url"]):
        raise ReleasePublicationError("merged-main workflow is not successful for the accepted commit")

    reviews = snapshot.get("reviews")
    if not isinstance(reviews, list):
        raise ReleasePublicationError("independent review evidence is missing")
    reviewer = request["independent_review"]["reviewer"]
    review_url = request["independent_review"]["url"]
    pull_author = pull.get("user", {}).get("login") if isinstance(pull.get("user"), dict) else None
    if not isinstance(pull_author, str) or not pull_author:
        raise ReleasePublicationError("pull request author identity is missing")
    if reviewer.casefold() == pull_author.casefold() or not any(
        isinstance(record, dict)
        and record.get("state") == "APPROVED"
        and isinstance(record.get("user"), dict)
        and record["user"].get("login") == reviewer
        and record["user"].get("type") == "User"
        and record.get("author_association") in {"COLLABORATOR", "MEMBER", "OWNER"}
        and record.get("html_url") == review_url
        and record.get("commit_id") == request["pull_request"]["head_commit"]
        for record in reviews
    ):
        raise ReleasePublicationError("independent APPROVED review of the exact head was not observed")

    tag_ref = snapshot.get("tag_ref")
    tag_object = snapshot.get("tag_object")
    if (
        not isinstance(tag_ref, dict)
        or tag_ref.get("ref") != f"refs/tags/{release}"
        or not isinstance(tag_ref.get("object"), dict)
        or tag_ref["object"].get("type") != "tag"
        or not isinstance(tag_object, dict)
        or tag_object.get("sha") != tag_ref["object"].get("sha")
        or not isinstance(tag_object.get("object"), dict)
        or tag_object["object"].get("type") != "commit"
        or tag_object["object"].get("sha") != commit
    ):
        raise ReleasePublicationError("remote tag is not one annotated tag peeled to the accepted commit")
    tag_object_id = _require_commit(tag_ref["object"].get("sha"), "annotated tag object")

    tag_run = snapshot.get("tag_workflow")
    if not _successful_run(tag_run, commit, request["tag_workflow_url"]):
        raise ReleasePublicationError("tag workflow is not successful for the accepted commit")
    if (
        tag_run.get("event") != "push"
        or tag_run.get("head_branch") != release
        or tag_run.get("path") != ".github/workflows/release-verify.yml"
    ):
        raise ReleasePublicationError("exact release-verify workflow was not triggered by the release tag")

    github_release = snapshot.get("release")
    if (
        not isinstance(github_release, dict)
        or github_release.get("tag_name") != release
        or github_release.get("html_url") != request["github_release_url"]
        or github_release.get("draft") is not False
        or github_release.get("prerelease") is not False
        or github_release.get("published_at") is None
    ):
        raise ReleasePublicationError("GitHub Release is missing, draft, prerelease, or identity-mismatched")

    artifact_collection = snapshot.get("artifacts")
    records = artifact_collection.get("artifacts") if isinstance(artifact_collection, dict) else None
    expected_name = f"release-evidence-{release}"
    matching = [record for record in records or [] if isinstance(record, dict) and record.get("name") == expected_name]
    if len(matching) != 1:
        raise ReleasePublicationError("exactly one release evidence artifact is required")
    artifact = matching[0]
    if artifact.get("expired") is not False or artifact.get("workflow_run", {}).get("id") != tag_run.get("id"):
        raise ReleasePublicationError("release evidence artifact is expired or belongs to another run")
    digest = artifact.get("digest")
    if not isinstance(digest, str) or DIGEST.fullmatch(digest) is None:
        raise ReleasePublicationError("GitHub artifact digest is missing or invalid")
    archive_url = _require_url(
        artifact.get("archive_download_url"),
        f"{GITHUB_API}/repos/{REPOSITORY}/actions/artifacts/",
        "artifact archive",
    )
    artifact_id = artifact.get("id")
    if not isinstance(artifact_id, int) or artifact_id < 1:
        raise ReleasePublicationError("artifact ID is invalid")
    created_at = artifact.get("created_at")
    expires_at = artifact.get("expires_at")
    if not isinstance(created_at, str) or not isinstance(expires_at, str):
        raise ReleasePublicationError("artifact retention dates are missing")
    return {
        "pull_request": {
            "status": "PASS",
            "number": request["pull_request"]["number"],
            "url": expected_pr_url,
            "head_commit": request["pull_request"]["head_commit"],
            "checks_url": request["pull_request"]["checks_url"],
        },
        "independent_review": {
            "status": "PASS",
            "reviewer": reviewer,
            "url": review_url,
        },
        "merged_main": {
            "status": "PASS",
            "commit": commit,
            "workflow_url": request["merged_main_workflow_url"],
        },
        "annotated_tag": {
            "status": "PASS",
            "name": release,
            "object_type": "tag",
            "object_id": tag_object_id,
            "peeled_commit": commit,
        },
        "tag_workflow": {
            "status": "PASS",
            "provider": "github.actions",
            "run_id": str(tag_run["id"]),
            "run_attempt": str(tag_run["run_attempt"]),
            "url": request["tag_workflow_url"],
        },
        "evidence_artifact": {
            "status": "PASS",
            "name": expected_name,
            "id": artifact_id,
            "url": _require_url(artifact.get("url"), f"{GITHUB_API}/repos/{REPOSITORY}/actions/artifacts/", "artifact"),
            "archive_download_url": archive_url,
            "digest": digest,
            "retention_days": _retention_days(created_at, expires_at),
            "created_at": created_at,
            "expires_at": expires_at,
            "download_status": "NOT_RUN",
            "downloaded_at": None,
            "downloaded_archive_digest": None,
            "tag_evidence_sha256": None,
            "checksums_sha256": None,
        },
        "github_release": {
            "status": "PASS",
            "url": request["github_release_url"],
            "tag": release,
            "draft": False,
            "prerelease": False,
        },
    }


def _successful_run(record: Any, commit: str, url: str) -> bool:
    return (
        isinstance(record, dict)
        and record.get("status") == "completed"
        and record.get("conclusion") == "success"
        and record.get("head_sha") == commit
        and record.get("html_url") == url
    )


def verify_downloaded_artifact(
    archive: bytes,
    publication: dict[str, Any],
    request: dict[str, Any],
    *,
    downloaded_at: datetime | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    artifact = publication["evidence_artifact"]
    archive_digest = _sha256(archive)
    if artifact["digest"] != archive_digest:
        raise ReleasePublicationError("downloaded archive digest differs from GitHub metadata")
    try:
        with tempfile.TemporaryDirectory() as temporary:
            archive_path = Path(temporary) / "artifact.zip"
            archive_path.write_bytes(archive)
            with zipfile.ZipFile(archive_path) as bundle:
                names = bundle.namelist()
                if any(
                    name.startswith("/") or ".." in Path(name).parts or name.endswith("/")
                    for name in names
                ):
                    raise ReleasePublicationError("release evidence archive contains an unsafe path")
                if len(names) != len(set(names)):
                    raise ReleasePublicationError("release evidence archive contains duplicate paths")
                contents = {name: bundle.read(name) for name in names}
    except (OSError, zipfile.BadZipFile, KeyError) as error:
        raise ReleasePublicationError(f"release evidence archive is invalid: {error}") from None
    required = {"release-evidence.json", "SHA256SUMS"} | {
        f"bundle/{path}" for path in EVIDENCE_ASSETS.values()
    }
    if set(contents) != required:
        raise ReleasePublicationError("release evidence archive file set differs")
    checksum_records: dict[str, str] = {}
    try:
        lines = contents["SHA256SUMS"].decode("utf-8").splitlines()
    except UnicodeDecodeError:
        raise ReleasePublicationError("SHA256SUMS is not UTF-8") from None
    for line in lines:
        match = CHECKSUM_LINE.fullmatch(line)
        if match is None or match.group(2) in checksum_records:
            raise ReleasePublicationError("SHA256SUMS contains an invalid or duplicate record")
        checksum_records[match.group(2)] = match.group(1)
    expected_checked = required - {"SHA256SUMS"}
    if set(checksum_records) != expected_checked:
        raise ReleasePublicationError("SHA256SUMS does not cover the exact artifact file set")
    for path, digest in checksum_records.items():
        if hashlib.sha256(contents[path]).hexdigest() != digest:
            raise ReleasePublicationError(f"SHA256SUMS mismatch: {path}")
    try:
        tag_evidence = loads_strict(contents["release-evidence.json"])
    except ValueError as error:
        raise ReleasePublicationError(f"tag evidence JSON is invalid: {error}") from None
    if not isinstance(tag_evidence, dict):
        raise ReleasePublicationError("tag evidence root is not an object")
    try:
        validate_release_evidence(tag_evidence)
    except ReleaseEvidenceError as error:
        raise ReleasePublicationError(str(error)) from None
    expected_identity = {
        "evidence_kind": "TAG_WORKFLOW_EVIDENCE",
        "status": "PARTIAL",
        "release_status": "NOT_PUBLISHED",
        "release": request["release"],
        "repository": REPOSITORY,
        "tag": request["release"],
        "tag_object": publication["annotated_tag"]["object_id"],
        "commit": request["commit"],
    }
    if any(tag_evidence.get(key) != value for key, value in expected_identity.items()):
        raise ReleasePublicationError("downloaded tag evidence identity differs from publication")
    tag_run = publication["tag_workflow"]
    embedded_run = tag_evidence["publication"]["tag_workflow"]
    if (
        embedded_run["run_id"] != tag_run["run_id"]
        or embedded_run["run_attempt"] != tag_run["run_attempt"]
        or embedded_run["url"] != tag_run["url"]
    ):
        raise ReleasePublicationError("downloaded tag evidence belongs to another workflow run")
    assets = {record["kind"]: record for record in tag_evidence["assets"]}
    for kind, relative in EVIDENCE_ASSETS.items():
        bundled = contents[f"bundle/{relative}"]
        record = assets[kind]
        if _sha256(bundled) != record["sha256"] or len(bundled) != record["size_bytes"]:
            raise ReleasePublicationError(f"downloaded evidence asset differs: {kind}")
    artifact.update(
        {
            "download_status": "PASS",
            "downloaded_at": _now(downloaded_at),
            "downloaded_archive_digest": archive_digest,
            "tag_evidence_sha256": _sha256(contents["release-evidence.json"]),
            "checksums_sha256": _sha256(contents["SHA256SUMS"]),
        }
    )
    return tag_evidence, contents


def run_anonymous_exact_tag_install(
    release: str,
    expected_tag_object: str,
    expected_commit: str,
    *,
    observed_at: datetime | None = None,
) -> dict[str, Any]:
    source_url = f"{GITHUB_WEB}/{REPOSITORY}.git"
    environment = os.environ.copy()
    for key in tuple(environment):
        normalized = key.upper()
        if normalized in {"GITHUB_TOKEN", "GH_TOKEN"} or normalized.endswith("_TOKEN") or normalized.endswith("_PASSWORD") or normalized.endswith("_SECRET"):
            environment.pop(key, None)
    environment.update(
        {
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_TERMINAL_PROMPT": "0",
        }
    )
    with tempfile.TemporaryDirectory() as temporary:
        temporary_root = Path(temporary)
        source = temporary_root / "source"
        installed = temporary_root / "installed"
        team = temporary_root / "team"
        projection = temporary_root / "projection"
        plan = temporary_root / "host-plan.json"
        commands: list[list[str]] = [
            ["git", "clone", "--quiet", "--no-local", "--branch", release, source_url, str(source)],
            ["git", "rev-parse", f"refs/tags/{release}"],
            ["git", "cat-file", "-t", f"refs/tags/{release}"],
            ["git", "rev-parse", f"{release}^{{}}"],
        ]
        results = [_run(command, source if source.exists() else temporary_root, environment) for command in commands]
        if results[1] != expected_tag_object or results[2] != "tag" or results[3] != expected_commit:
            raise ReleasePublicationError("anonymous clone tag identity differs from accepted release")
        workflow = [
            ["python3", "tools/agent_team.py", "factory", "install", "--output", str(installed)],
            ["python3", str(installed / "tools/agent_team.py"), "factory", "verify", "--root", str(installed)],
            ["python3", str(installed / "tools/agent_team.py"), "doctor"],
            [str(installed / "agent-team"), "create", "--design", str(installed / "examples/context-first/team-design.json"), "--output", str(team)],
            [str(installed / "agent-team"), "context", "validate", "--root", str(team)],
            [str(installed / "agent-team"), "host", "plan", "--team", str(team), "--target", "generic-ai", "--destination", str(projection), "--output", str(plan)],
            [str(installed / "agent-team"), "host", "preview", "--plan", str(plan)],
        ]
        for command in workflow:
            _run(command, source, environment)
        plan_document = loads_strict(plan.read_text(encoding="utf-8"))
        digest = plan_document.get("proposal_digest") if isinstance(plan_document, dict) else None
        if not isinstance(digest, str) or DIGEST.fullmatch(digest) is None:
            raise ReleasePublicationError("anonymous host plan lacks an exact digest")
        remainder = [
            [str(installed / "agent-team"), "host", "confirm", "--plan", str(plan), "--digest", digest, "--approved-by", "Anonymous Release Verifier"],
            [str(installed / "agent-team"), "host", "apply", "--plan", str(plan)],
            [str(installed / "agent-team"), "host", "verify", "--root", str(projection)],
            [str(installed / "agent-team"), "host", "uninstall-preview", "--root", str(projection)],
            [str(installed / "agent-team"), "host", "uninstall", "--root", str(projection), "--digest", digest],
            [str(installed / "agent-team"), "host", "uninstall-preview", "--root", str(projection)],
            [str(installed / "agent-team"), "host", "uninstall", "--root", str(projection), "--digest", digest],
            [str(installed / "agent-team"), "native", "writer-authority-validate", "--topology", str(installed / "examples/v08-contracts/valid/writer-topology.json"), "--plan", str(installed / "examples/v08-contracts/valid/plan-revision.json"), "--approval", str(installed / "examples/v08-contracts/valid/approval-grant.json")],
        ]
        last = ""
        for command in remainder:
            last = _run(command, source, environment)
        try:
            writer = loads_strict(last)
        except ValueError:
            raise ReleasePublicationError("anonymous writer-authority output is invalid") from None
        if not isinstance(writer, dict) or writer.get("status") != "VALID" or writer.get("automatic_execution") is not False or writer.get("identity_or_signature_verified") is not False:
            raise ReleasePublicationError("anonymous writer-authority boundary differs")
    return {
        "status": "PASS",
        "workflow_url": None,
        "source_url": source_url,
        "tag": release,
        "tag_object": expected_tag_object,
        "commit": expected_commit,
        "verified_at": _now(observed_at),
        "commands": list(ANONYMOUS_COMMANDS),
        "maintainer_credentials_available": False,
        "external_writes": False,
    }


def _run(arguments: list[str], cwd: Path, environment: dict[str, str]) -> str:
    try:
        return subprocess.run(
            arguments,
            cwd=cwd,
            env=environment,
            check=True,
            capture_output=True,
            text=True,
            timeout=300,
            shell=False,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError) as error:
        label = " ".join(arguments[:4])
        raise ReleasePublicationError(f"anonymous verification command failed: {label}: {error}") from None


def build_final_release_index(
    request: dict[str, Any],
    publication: dict[str, Any],
    tag_evidence: dict[str, Any],
    anonymous_install: dict[str, Any],
    *,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    if publication["evidence_artifact"]["download_status"] != "PASS":
        raise ReleasePublicationError("cannot finalize before actual artifact download verification")
    if anonymous_install.get("status") != "PASS":
        raise ReleasePublicationError("cannot finalize before anonymous exact-tag installation")
    if any(
        anonymous_install.get(key) != value
        for key, value in {
            "tag": request["release"],
            "tag_object": publication["annotated_tag"]["object_id"],
            "commit": request["commit"],
            "maintainer_credentials_available": False,
            "external_writes": False,
        }.items()
    ):
        raise ReleasePublicationError("anonymous installation identity or boundary differs")
    gates = [dict(record) for record in tag_evidence["gates"]]
    gate_map = {record["id"]: record for record in gates}
    evidence_by_gate = {
        "pull-request": [publication["pull_request"]["url"], publication["pull_request"]["checks_url"]],
        "independent-review": [publication["independent_review"]["url"]],
        "merged-main": [publication["merged_main"]["workflow_url"], request["commit"]],
        "annotated-tag": [f"refs/tags/{request['release']}@{publication['annotated_tag']['object_id']}", request["commit"]],
        "tag-workflow": [publication["tag_workflow"]["url"]],
        "evidence-artifact-download": [publication["evidence_artifact"]["url"], publication["evidence_artifact"]["downloaded_archive_digest"]],
        "github-release": [publication["github_release"]["url"]],
        "anonymous-install": [anonymous_install["source_url"], anonymous_install["verified_at"]],
    }
    for gate_id, evidence in evidence_by_gate.items():
        gate_map[gate_id] = {"id": gate_id, "status": "PASS", "evidence": evidence}
    final_gates = [gate_map[gate_id] for gate_id in GATE_IDS]
    final_publication = dict(publication)
    final_publication["anonymous_install"] = anonymous_install
    document = {
        "$schema": "schemas/release-evidence.schema.json",
        "schema_version": "2.0.0",
        "evidence_kind": "FINAL_RELEASE_INDEX",
        "status": "ACCEPTED",
        "release_status": "RELEASED",
        "release": request["release"],
        "repository": REPOSITORY,
        "tag": request["release"],
        "tag_object": publication["annotated_tag"]["object_id"],
        "commit": request["commit"],
        "generated_at": _now(generated_at),
        "environment": {
            "runner_os": platform.system() or "unknown",
            "python_version": platform.python_version(),
        },
        "commands": [
            {"command": "GitHub REST read-only publication verification", "exit_code": 0},
            {"command": "download and verify release-evidence artifact", "exit_code": 0},
            {"command": "verify SHA256SUMS and bundled evidence", "exit_code": 0},
            {"command": "anonymous exact-tag install and lifecycle verification", "exit_code": 0},
        ],
        "assets": tag_evidence["assets"],
        "publication": final_publication,
        "gates": final_gates,
        "boundaries": {
            "automatic_merge": False,
            "automatic_deploy": False,
            "production_credentials_read": False,
            "tagged_source_modified": False,
            "github_api_writes": False,
        },
    }
    try:
        validate_release_evidence(document)
    except ReleaseEvidenceError as error:
        raise ReleasePublicationError(str(error)) from None
    return document


def write_final_index(document: dict[str, Any], output: Path) -> None:
    try:
        validate_release_evidence(document)
    except ReleaseEvidenceError as error:
        raise ReleasePublicationError(str(error)) from None
    source_root = ROOT.resolve()
    destination = output.resolve()
    if destination == source_root or source_root in destination.parents:
        raise ReleasePublicationError("final release index must be written outside tagged source")
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        raise ReleasePublicationError("final release index output already exists")
    content = json.dumps(document, indent=2, sort_keys=True) + "\n"
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=output.parent,
        prefix=f".{output.name}.",
        delete=False,
    ) as handle:
        stage = Path(handle.name)
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())
    try:
        os.replace(stage, output)
    except BaseException:
        stage.unlink(missing_ok=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    try:
        request = load_finalization_request(arguments.request)
        token = os.environ.get("GITHUB_TOKEN", "") or os.environ.get("GH_TOKEN", "")
        if not token:
            raise ReleasePublicationError("a read-only GitHub token is required for live verification")
        snapshot = fetch_publication_snapshot(request, token)
        publication = verify_publication_snapshot(request, snapshot)
        archive = _github_download(publication["evidence_artifact"]["archive_download_url"], token)
        tag_evidence, _ = verify_downloaded_artifact(archive, publication, request)
        anonymous = run_anonymous_exact_tag_install(
            request["release"],
            publication["annotated_tag"]["object_id"],
            request["commit"],
        )
        document = build_final_release_index(request, publication, tag_evidence, anonymous)
        write_final_index(document, arguments.output)
    except (OSError, ValueError, ReleasePublicationError) as error:
        print(f"release publication refused or failed: {error}", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "status": document["status"],
                "release_status": document["release_status"],
                "tag": document["tag"],
                "commit": document["commit"],
                "output": str(arguments.output),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
