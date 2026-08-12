from __future__ import annotations

import hashlib
import io
import json
import os
import tempfile
import unittest
import urllib.error
import urllib.request
import zipfile
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from tools.release_evidence import (
    EVIDENCE_ASSETS,
    LOCAL_GATE_IDS,
    ReleaseEvidenceError,
    build_release_evidence,
    validate_release_evidence,
    write_release_evidence,
)
from tools.release_publication import (
    ANONYMOUS_COMMANDS,
    REVIEW_AGENT_ID,
    REVIEW_RUNTIME,
    REVIEW_WORKFLOW_COMMIT,
    ReleasePublicationError,
    _anonymous_environment,
    _require_artifact_redirect_url,
    _require_public_https_url,
    _review_archive_contents,
    _github_download,
    _github_run_artifacts,
    _review_input_bytes,
    _review_rubric_bytes,
    run_anonymous_exact_tag_install,
    build_final_release_index,
    load_finalization_request,
    verify_downloaded_artifact,
    verify_live_external_scm_artifacts,
    verify_publication_snapshot,
    write_final_index,
)


class ReleaseEvidenceTests(unittest.TestCase):
    maxDiff = None

    def _environment(self) -> dict[str, str]:
        return {
            "GITHUB_REPOSITORY": "90le/agent-team-engineering",
            "GITHUB_REF_TYPE": "tag",
            "GITHUB_REF_NAME": "v1.0.0",
            "GITHUB_RUN_ID": "123456",
            "GITHUB_RUN_ATTEMPT": "1",
            "RUNNER_OS": "Linux",
        }

    def _asset_fixture(self) -> tuple[list[dict], dict[str, bytes]]:
        contents = {
            path: json.dumps({"fixture": kind}, sort_keys=True).encode("utf-8")
            for kind, path in EVIDENCE_ASSETS.items()
        }
        assets = [
            {
                "kind": kind,
                "path": path,
                "bundle_path": f"bundle/{path}",
                "sha256": "sha256:" + hashlib.sha256(contents[path]).hexdigest(),
                "size_bytes": len(contents[path]),
            }
            for kind, path in EVIDENCE_ASSETS.items()
        ]
        return assets, contents

    def _local_gate_fixture(self) -> dict[str, list[str]]:
        assets, _ = self._asset_fixture()
        by_kind = {record["kind"]: record for record in assets}
        candidate = by_kind["v10-candidate-conformance"]
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
                f"{by_kind['external-scm-first-run']['path']}@{by_kind['external-scm-first-run']['sha256']}",
                f"{by_kind['external-scm-replay']['path']}@{by_kind['external-scm-replay']['sha256']}",
            ],
            "supply-chain": [
                f"{by_kind['sbom']['path']}@{by_kind['sbom']['sha256']}",
                f"{by_kind['source-provenance']['path']}@{by_kind['source-provenance']['sha256']}",
            ],
            "public-documentation": ["./agent-team validate"],
        }

    def _tag_evidence(self) -> tuple[dict, dict[str, bytes]]:
        assets, contents = self._asset_fixture()
        document = build_release_evidence(
            self._environment(),
            generated_at=datetime(2026, 8, 12, 0, 0, tzinfo=timezone.utc),
            tag_object="a" * 40,
            commit="b" * 40,
            artifacts=assets,
            local_gate_evidence=self._local_gate_fixture(),
        )
        return document, contents

    def _live_scm_fixture(self) -> dict[str, object]:
        return {
            "status": "PASS",
            "evidence": [
                "https://github.com/90le/agent-team-v10-conformance-private/actions/runs/101",
                "https://api.github.com/repos/90le/agent-team-v10-conformance-private/actions/artifacts/1001@sha256:"
                + "1" * 64,
                "https://github.com/90le/agent-team-v10-conformance-private/actions/runs/102",
                "https://api.github.com/repos/90le/agent-team-v10-conformance-private/actions/artifacts/1002@sha256:"
                + "2" * 64,
            ],
        }

    def _request(self) -> dict:
        checks = [
            {
                "name": "validate",
                "url": "https://github.com/90le/agent-team-engineering/actions/runs/111/job/11",
                "app_id": 15368,
            },
            {
                "name": "conformance",
                "url": "https://github.com/90le/agent-team-engineering/actions/runs/112/job/12",
                "app_id": 15368,
            },
        ]
        return {
            "repository": "90le/agent-team-engineering",
            "release": "v1.0.0",
            "commit": "b" * 40,
            "pull_request": {
                "number": 13,
                "head_commit": "c" * 40,
                "checks": checks,
            },
            "technical_review": {
                "head_commit": "c" * 40,
                "workflow_commit": REVIEW_WORKFLOW_COMMIT,
                "reviewer_kind": "independent-ai",
                "reviewer_runtime": REVIEW_RUNTIME,
                "evidence_url": "https://github.com/90le/agent-team-v10-review-private/actions/runs/333",
                "evidence_sha256": "sha256:" + "0" * 64,
                "decision": "PASS",
                "authenticated_human": False,
            },
            "owner_approval": {
                "head_commit": "c" * 40,
                "reviewer": "90le",
                "reviewer_kind": "github-user",
                "url": "https://github.com/90le/agent-team-engineering/pull/13#pullrequestreview-99",
                "decision": "APPROVED",
            },
            "merged_main": {
                "checks": [
                    {
                        "name": "validate",
                        "url": "https://github.com/90le/agent-team-engineering/actions/runs/221/job/21",
                        "app_id": 15368,
                    },
                    {
                        "name": "conformance",
                        "url": "https://github.com/90le/agent-team-engineering/actions/runs/222/job/22",
                        "app_id": 15368,
                    },
                ]
            },
            "tag_workflow_url": "https://github.com/90le/agent-team-engineering/actions/runs/123456",
            "github_release_url": "https://github.com/90le/agent-team-engineering/releases/tag/v1.0.0",
        }

    def _snapshot(self, request: dict | None = None) -> dict:
        request = request if request is not None else self._request()

        def check_runs(commit: str, checks: list[dict]) -> list[dict]:
            hour = 1 if commit == "c" * 40 else 4
            return [
                {
                    "id": index,
                    "name": check["name"],
                    "head_sha": commit,
                    "status": "completed",
                    "conclusion": "success",
                    "started_at": f"2026-08-12T{hour:02d}:00:{index:02d}Z",
                    "completed_at": f"2026-08-12T{hour:02d}:01:{index:02d}Z",
                    "app": {"id": check["app_id"]},
                    "html_url": check["url"],
                    "details_url": check["url"],
                }
                for index, check in enumerate(checks, start=1)
            ]

        return {
            "pull_request": {
                "html_url": "https://github.com/90le/agent-team-engineering/pull/13",
                "state": "closed",
                "merged": True,
                "merge_commit_sha": "b" * 40,
                "head": {"sha": "c" * 40},
                "base": {
                    "ref": "main",
                    "repo": {"full_name": "90le/agent-team-engineering"},
                },
                "user": {"login": "change-author", "type": "User"},
                "merged_at": "2026-08-12T03:30:00Z",
            },
            "main_ref": {
                "ref": "refs/heads/main",
                "object": {"type": "commit", "sha": "b" * 40},
            },
            "merged_main_git_commit": {"tree": {"sha": "d" * 40}},
            "reviews": [
                {
                    "id": 99,
                    "state": "APPROVED",
                    "user": {
                        "login": "90le",
                        "id": 68719118,
                        "type": "User",
                    },
                    "author_association": "OWNER",
                    "html_url": request["owner_approval"]["url"],
                    "commit_id": "c" * 40,
                    "submitted_at": "2026-08-12T03:10:00Z",
                }
            ],
            "tag_ref": {
                "ref": "refs/tags/v1.0.0",
                "object": {"type": "tag", "sha": "a" * 40},
            },
            "tag_object": {
                "sha": "a" * 40,
                "tag": "v1.0.0",
                "object": {"type": "commit", "sha": "b" * 40},
                "tagger": {
                    "name": "Release Owner",
                    "email": "release-owner@example.invalid",
                    "date": "2026-08-12T05:00:00Z",
                },
                "verification": {"verified": False, "reason": "unsigned"},
            },
            "release": {
                "tag_name": "v1.0.0",
                "html_url": request["github_release_url"],
                "draft": False,
                "prerelease": False,
                "published_at": "2026-08-12T06:00:00Z",
                "author": {"login": "90le", "id": 68719118, "type": "User"},
            },
            "tag_workflow": {
                "id": 123456,
                "run_attempt": 1,
                "status": "completed",
                "conclusion": "success",
                "head_sha": "b" * 40,
                "head_branch": "v1.0.0",
                "event": "push",
                "path": ".github/workflows/release-verify.yml",
                "html_url": request["tag_workflow_url"],
                "created_at": "2026-08-12T05:01:00Z",
                "updated_at": "2026-08-12T05:30:00Z",
                "actor": {"login": "90le", "id": 68719118, "type": "User"},
                "triggering_actor": {
                    "login": "90le",
                    "id": 68719118,
                    "type": "User",
                },
            },
            "required_status_checks": {
                "strict": True,
                "contexts": ["validate", "conformance"],
                "checks": [
                    {"context": "validate", "app_id": 15368},
                    {"context": "conformance", "app_id": 15368},
                ],
            },
            "active_main_rules": [],
            "pull_request_check_runs": check_runs(
                "c" * 40, request["pull_request"]["checks"]
            ),
            "pull_request_statuses": [],
            "merged_main_check_runs": check_runs(
                "b" * 40, request["merged_main"]["checks"]
            ),
            "merged_main_statuses": [],
            "artifacts": {
                "artifacts": [
                    {
                        "id": 555,
                        "name": "release-evidence-v1.0.0",
                        "expired": False,
                        "workflow_run": {"id": 123456},
                        "url": "https://api.github.com/repos/90le/agent-team-engineering/actions/artifacts/555",
                        "archive_download_url": "https://api.github.com/repos/90le/agent-team-engineering/actions/artifacts/555/zip",
                        "digest": "sha256:" + "0" * 64,
                        "created_at": "2026-08-12T05:20:00Z",
                        "expires_at": "2026-09-11T01:00:00Z",
                    }
                ]
            },
            **self._technical_review_fixture(request),
        }

    def _technical_review_fixture(self, request: dict) -> dict:
        patch_digest = "sha256:" + "2" * 64
        document = {
            "schema_version": "1.0.0",
            "evidence_kind": "INDEPENDENT_AI_TECHNICAL_REVIEW",
            "repository": "90le/agent-team-engineering",
            "base_commit": "a286cfadbfb6f387a4f1fb94c244f57d4dd089e6",
            "head_commit": "c" * 40,
            "head_tree": "d" * 40,
            "reviewer_kind": "independent-ai",
            "reviewer_runtime": request["technical_review"]["reviewer_runtime"],
            "agent_id": REVIEW_AGENT_ID,
            "session_id": "openclaw-review-session-1",
            "prompt_sha256": "sha256:" + "0" * 64,
            "patch_sha256": patch_digest,
            "decision": "PASS",
            "findings": [],
            "authenticated_human": False,
            "generated_at": "2026-08-12T03:00:00Z",
            "boundaries": {
                "source_repository_writes": False,
                "human_approval_substitute": False,
                "production_credentials_read": False,
                "gateway_required": False,
            },
            "workflow_commit": REVIEW_WORKFLOW_COMMIT,
            "workflow_run_id": "333",
            "workflow_url": request["technical_review"]["evidence_url"],
            "review_input_sha256": "sha256:" + "3" * 64,
            "deterministic_gates_passed": True,
        }
        document["prompt_sha256"] = "sha256:" + hashlib.sha256(
            _review_rubric_bytes("c" * 40, "d" * 40, patch_digest)
        ).hexdigest()
        document["review_input_sha256"] = "sha256:" + hashlib.sha256(
            _review_input_bytes(document)
        ).hexdigest()
        content = (json.dumps(document, indent=2, sort_keys=True) + "\n").encode()
        checksum = hashlib.sha256(content).hexdigest() + "  independent-ai-review.json\n"
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_STORED) as bundle:
            bundle.writestr("independent-ai-review.json", content)
            bundle.writestr("independent-ai-review.sha256", checksum.encode())
        archive = output.getvalue()
        request["technical_review"]["evidence_sha256"] = "sha256:" + hashlib.sha256(content).hexdigest()
        return {
            "technical_review_run": {
                "id": 333,
                "run_attempt": 1,
                "status": "completed",
                "conclusion": "success",
                "event": "workflow_dispatch",
                "head_sha": REVIEW_WORKFLOW_COMMIT,
                "path": ".github/workflows/independent-review.yml",
                "html_url": request["technical_review"]["evidence_url"],
                "repository": {"full_name": "90le/agent-team-v10-review-private"},
                "created_at": "2026-08-12T03:01:00Z",
                "run_started_at": "2026-08-12T03:02:00Z",
                "updated_at": "2026-08-12T03:05:00Z",
            },
            "technical_review_artifacts": {
                "artifacts": [
                    {
                        "id": 777,
                        "name": "independent-ai-review-" + "c" * 40,
                        "expired": False,
                        "workflow_run": {"id": 333},
                        "url": "https://api.github.com/repos/90le/agent-team-v10-review-private/actions/artifacts/777",
                        "archive_download_url": "https://api.github.com/repos/90le/agent-team-v10-review-private/actions/artifacts/777/zip",
                        "digest": "sha256:" + hashlib.sha256(archive).hexdigest(),
                        "created_at": "2026-08-12T03:04:00Z",
                    }
                ]
            },
            "technical_review_archive": archive,
            "pull_head_git_commit": {"tree": {"sha": "d" * 40}},
            "technical_review_material": {
                "head_tree": "d" * 40,
                "patch_sha256": patch_digest,
            },
        }

    def _archive(self, tag_evidence: dict, contents: dict[str, bytes]) -> bytes:
        evidence_bytes = (json.dumps(tag_evidence, indent=2, sort_keys=True) + "\n").encode("utf-8")
        bundle_files = {f"bundle/{path}": content for path, content in contents.items()}
        checksum_files = dict(bundle_files)
        checksum_files["release-evidence.json"] = evidence_bytes
        checksums = "".join(
            f"{hashlib.sha256(content).hexdigest()}  {path}\n"
            for path, content in sorted(checksum_files.items())
        ).encode("utf-8")
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
            bundle.writestr("release-evidence.json", evidence_bytes)
            bundle.writestr("SHA256SUMS", checksums)
            for path, content in bundle_files.items():
                bundle.writestr(path, content)
        return output.getvalue()

    def test_tag_evidence_is_partial_and_keeps_publication_unclaimed(self) -> None:
        document, contents = self._tag_evidence()
        self.assertEqual(document["evidence_kind"], "TAG_WORKFLOW_EVIDENCE")
        self.assertEqual(document["status"], "PARTIAL")
        self.assertEqual(document["release_status"], "NOT_PUBLISHED")
        self.assertEqual(document["publication"]["tag_workflow"]["status"], "NOT_RUN")
        self.assertEqual(document["publication"]["github_release"]["status"], "NOT_RUN")
        self.assertEqual(document["publication"]["anonymous_install"]["status"], "NOT_RUN")
        self.assertEqual(
            document["commands"][-1]["command"],
            "python3 tools/release_evidence.py --output artifacts/release-evidence.json --checksums artifacts/SHA256SUMS",
        )
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "release-evidence.json"
            checksums = Path(temporary) / "SHA256SUMS"
            write_release_evidence(document, output, checksums, asset_loader=lambda path: contents[path])
            self.assertTrue(output.is_file())
            self.assertEqual(len(checksums.read_text(encoding="utf-8").splitlines()), 6)

    def test_tag_evidence_rejects_self_reported_publication(self) -> None:
        document, _ = self._tag_evidence()
        document["publication"]["github_release"].update(
            {
                "status": "PASS",
                "url": "https://github.com/90le/agent-team-engineering/releases/tag/v1.0.0",
                "tag": "v1.0.0",
                "draft": False,
                "prerelease": False,
            }
        )
        with self.assertRaises(ReleaseEvidenceError):
            validate_release_evidence(document)

    def test_tag_evidence_rejects_hidden_future_publication_identities(self) -> None:
        document, _ = self._tag_evidence()
        mutations = (
            ("pull-request-head", "pull_request", "head_commit", "c" * 40),
            ("technical-workflow", "technical_review", "workflow_commit", "c" * 40),
            ("owner-login", "owner_approval", "reviewer", "90le"),
            ("merged-commit", "merged_main", "commit", "c" * 40),
        )
        for label, section, field, value in mutations:
            altered = deepcopy(document)
            altered["publication"][section][field] = value
            with self.subTest(label=label), self.assertRaises(ReleaseEvidenceError):
                validate_release_evidence(altered)

    def test_non_tag_or_wrong_repository_cannot_generate_release_evidence(self) -> None:
        assets, _ = self._asset_fixture()
        for field, value in (
            ("GITHUB_REF_TYPE", "branch"),
            ("GITHUB_REF_NAME", "v0.9.0"),
            ("GITHUB_REPOSITORY", "other/repository"),
        ):
            environment = self._environment()
            environment[field] = value
            with self.subTest(field=field), self.assertRaises(ReleaseEvidenceError):
                build_release_evidence(
                    environment,
                    tag_object="a" * 40,
                    commit="b" * 40,
                    artifacts=assets,
                    local_gate_evidence=self._local_gate_fixture(),
                )

    def test_publication_verification_rejects_wrong_commit_and_missing_review_url(self) -> None:
        request = self._request()
        snapshot = self._snapshot(request)
        wrong_commit = deepcopy(snapshot)
        wrong_commit["pull_request_check_runs"][0]["head_sha"] = "d" * 40
        with self.assertRaises(ReleasePublicationError):
            verify_publication_snapshot(request, wrong_commit)
        no_review = deepcopy(snapshot)
        no_review["reviews"] = []
        with self.assertRaises(ReleasePublicationError):
            verify_publication_snapshot(request, no_review)

    def test_publication_requires_exact_main_base_and_current_main_tip(self) -> None:
        request = self._request()
        snapshot = self._snapshot(request)
        verify_publication_snapshot(request, snapshot)
        cases: list[tuple[str, dict]] = []
        missing_base = deepcopy(snapshot)
        missing_base["pull_request"].pop("base")
        cases.append(("missing-base", missing_base))
        side_branch = deepcopy(snapshot)
        side_branch["pull_request"]["base"]["ref"] = "release-side-branch"
        cases.append(("non-main-base", side_branch))
        wrong_repository = deepcopy(snapshot)
        wrong_repository["pull_request"]["base"]["repo"]["full_name"] = "90le/other"
        cases.append(("wrong-base-repository", wrong_repository))
        moved_main = deepcopy(snapshot)
        moved_main["main_ref"]["object"]["sha"] = "e" * 40
        cases.append(("accepted-commit-not-main-tip", moved_main))
        malformed_main = deepcopy(snapshot)
        malformed_main["main_ref"]["object"]["type"] = "tag"
        cases.append(("main-ref-not-commit", malformed_main))
        unreviewed_merge_tree = deepcopy(snapshot)
        unreviewed_merge_tree["merged_main_git_commit"]["tree"]["sha"] = "f" * 40
        cases.append(("merged-main-tree-differs-from-reviewed-head", unreviewed_merge_tree))
        for label, altered in cases:
            with self.subTest(label=label), self.assertRaises(ReleasePublicationError):
                verify_publication_snapshot(request, altered)

    def test_every_required_check_is_unique_successful_and_app_bound_on_both_heads(self) -> None:
        request = self._request()
        snapshot = self._snapshot(request)
        publication = verify_publication_snapshot(request, snapshot)
        self.assertEqual(
            [
                {key: record[key] for key in ("name", "url", "app_id")}
                for record in publication["pull_request"]["checks"]
            ],
            sorted(request["pull_request"]["checks"], key=lambda item: item["name"]),
        )
        self.assertEqual(
            [
                {key: record[key] for key in ("name", "url", "app_id")}
                for record in publication["merged_main"]["checks"]
            ],
            sorted(request["merged_main"]["checks"], key=lambda item: item["name"]),
        )
        self.assertEqual(publication["merged_main"]["ref"], "refs/heads/main")
        self.assertTrue(
            all(
                record["completed_at"].endswith("Z")
                for record in publication["pull_request"]["checks"]
            )
        )

        successful_rerun = deepcopy(snapshot)
        rerun = deepcopy(successful_rerun["pull_request_check_runs"][0])
        rerun_url = "https://github.com/90le/agent-team-engineering/actions/runs/118/job/18"
        rerun.update(
            {
                "id": 98,
                "started_at": "2026-08-12T02:00:00Z",
                "completed_at": "2026-08-12T02:01:00Z",
                "html_url": rerun_url,
                "details_url": rerun_url,
            }
        )
        successful_rerun["pull_request_check_runs"].append(rerun)
        latest_request = deepcopy(request)
        latest_request["pull_request"]["checks"][0]["url"] = rerun_url
        verify_publication_snapshot(latest_request, successful_rerun)
        with self.assertRaises(ReleasePublicationError):
            verify_publication_snapshot(request, successful_rerun)

        cases: list[tuple[str, dict]] = []
        missing = deepcopy(snapshot)
        missing["pull_request_check_runs"].pop()
        cases.append(("missing", missing))
        duplicate_latest = deepcopy(snapshot)
        duplicate_latest["pull_request_check_runs"].append(
            deepcopy(duplicate_latest["pull_request_check_runs"][0])
        )
        cases.append(("duplicate-latest-identity", duplicate_latest))
        wrong_app = deepcopy(snapshot)
        wrong_app["pull_request_check_runs"][0]["app"]["id"] = 999
        cases.append(("wrong-app", wrong_app))
        failing_required = deepcopy(snapshot)
        failing_required["pull_request_check_runs"][0]["conclusion"] = "failure"
        cases.append(("failed", failing_required))
        latest_failure = deepcopy(snapshot)
        rerun = deepcopy(latest_failure["pull_request_check_runs"][0])
        rerun.update(
            {
                "id": 99,
                "started_at": "2026-08-12T02:00:00Z",
                "completed_at": "2026-08-12T02:01:00Z",
                "conclusion": "failure",
                "html_url": "https://github.com/90le/agent-team-engineering/actions/runs/119/job/19",
                "details_url": "https://github.com/90le/agent-team-engineering/actions/runs/119/job/19",
            }
        )
        latest_failure["pull_request_check_runs"].append(rerun)
        cases.append(("latest-rerun-fails-over-old-success", latest_failure))
        bad_main = deepcopy(snapshot)
        bad_main["merged_main_check_runs"][0]["conclusion"] = "failure"
        cases.append(("failed-main", bad_main))
        extra_required = deepcopy(snapshot)
        extra_required["required_status_checks"]["contexts"].append("release-policy")
        extra_required["required_status_checks"]["checks"].append(
            {"context": "release-policy", "app_id": 15368}
        )
        cases.append(("additional-protected-check", extra_required))
        for label, altered in cases:
            with self.subTest(label=label), self.assertRaises(ReleasePublicationError):
                verify_publication_snapshot(request, altered)

    def test_legacy_required_status_is_bound_to_exact_head_and_url(self) -> None:
        request = self._request()
        snapshot = self._snapshot(request)
        required = {"strict": True, "contexts": ["legacy-ci"], "checks": [{"context": "legacy-ci", "app_id": None}]}
        pull_url = "https://ci.example.test/pr/13"
        main_url = "https://ci.example.test/main/bbbbbbbb"
        request["pull_request"]["checks"] = [
            {"name": "legacy-ci", "url": pull_url, "app_id": None}
        ]
        request["merged_main"]["checks"] = [
            {"name": "legacy-ci", "url": main_url, "app_id": None}
        ]
        snapshot.update(
            {
                "required_status_checks": required,
                "pull_request_check_runs": [],
                "pull_request_statuses": [
                    {"id": 31, "context": "legacy-ci", "sha": "c" * 40, "state": "success", "target_url": pull_url, "created_at": "2026-08-12T01:00:00Z"}
                ],
                "merged_main_check_runs": [],
                "merged_main_statuses": [
                    {"id": 32, "context": "legacy-ci", "sha": "b" * 40, "state": "success", "target_url": main_url, "created_at": "2026-08-12T04:00:00Z"}
                ],
            }
        )
        publication = verify_publication_snapshot(request, snapshot)
        self.assertEqual(publication["pull_request"]["checks"][0]["name"], "legacy-ci")
        wrong_head = deepcopy(snapshot)
        wrong_head["pull_request_statuses"][0]["sha"] = "d" * 40
        with self.assertRaises(ReleasePublicationError):
            verify_publication_snapshot(request, wrong_head)

    def test_owner_approval_requires_trusted_exact_head_github_user(self) -> None:
        request = self._request()
        snapshot = self._snapshot(request)
        bot_review = deepcopy(snapshot)
        bot_review["reviews"][0]["user"]["type"] = "Bot"
        with self.assertRaises(ReleasePublicationError):
            verify_publication_snapshot(request, bot_review)
        untrusted_review = deepcopy(snapshot)
        untrusted_review["reviews"][0]["author_association"] = "CONTRIBUTOR"
        with self.assertRaises(ReleasePublicationError):
            verify_publication_snapshot(request, untrusted_review)
        stale_review = deepcopy(snapshot)
        stale_review["reviews"][0]["commit_id"] = "e" * 40
        with self.assertRaises(ReleasePublicationError):
            verify_publication_snapshot(request, stale_review)
        later_blocker = deepcopy(snapshot)
        later_blocker["reviews"].append(
            {
                "id": 100,
                "state": "CHANGES_REQUESTED",
                "user": {"login": "other-maintainer", "type": "User"},
                "author_association": "MEMBER",
                "html_url": "https://github.com/90le/agent-team-engineering/pull/13#pullrequestreview-100",
                "commit_id": "c" * 40,
                "submitted_at": "2026-08-12T01:11:00Z",
            }
        )
        with self.assertRaises(ReleasePublicationError):
            verify_publication_snapshot(request, later_blocker)
        approval_revoked = deepcopy(snapshot)
        approval_revoked["reviews"].append(
            {
                "id": 101,
                "state": "DISMISSED",
                "user": {"login": "90le", "id": 68719118, "type": "User"},
                "author_association": "OWNER",
                "html_url": "https://github.com/90le/agent-team-engineering/pull/13#pullrequestreview-101",
                "commit_id": "c" * 40,
                "submitted_at": "2026-08-12T03:12:00Z",
            }
        )
        with self.assertRaises(ReleasePublicationError):
            verify_publication_snapshot(request, approval_revoked)

    def test_technical_review_artifact_is_exact_and_cannot_hide_blockers(self) -> None:
        request = self._request()
        snapshot = self._snapshot(request)
        verify_publication_snapshot(request, snapshot)

        cases: list[tuple[str, dict, dict]] = []
        wrong_workflow = deepcopy(snapshot)
        wrong_workflow["technical_review_run"]["head_sha"] = "e" * 40
        cases.append(("workflow", deepcopy(request), wrong_workflow))
        rerun = deepcopy(snapshot)
        rerun["technical_review_run"]["run_attempt"] = 2
        cases.append(("rerun", deepcopy(request), rerun))
        duplicate = deepcopy(snapshot)
        duplicate["technical_review_artifacts"]["artifacts"].append(
            deepcopy(duplicate["technical_review_artifacts"]["artifacts"][0])
        )
        cases.append(("duplicate-artifact", deepcopy(request), duplicate))
        bad_digest = deepcopy(snapshot)
        bad_digest["technical_review_artifacts"]["artifacts"][0]["digest"] = (
            "sha256:" + "f" * 64
        )
        cases.append(("archive-digest", deepcopy(request), bad_digest))
        wrong_tree = deepcopy(snapshot)
        wrong_tree["pull_head_git_commit"]["tree"]["sha"] = "f" * 40
        cases.append(("tree", deepcopy(request), wrong_tree))
        forged_runtime_request = deepcopy(request)
        forged_runtime_request["technical_review"]["reviewer_runtime"] = (
            "openclaw/attacker-controlled-runtime"
        )
        forged_runtime = self._snapshot(forged_runtime_request)
        cases.append(("runtime", forged_runtime_request, forged_runtime))

        stale_patch = deepcopy(snapshot)
        with zipfile.ZipFile(
            io.BytesIO(stale_patch["technical_review_archive"])
        ) as bundle:
            stale_review = json.loads(bundle.read("independent-ai-review.json"))
        stale_review["patch_sha256"] = "sha256:" + "9" * 64
        stale_review["prompt_sha256"] = "sha256:" + hashlib.sha256(
            _review_rubric_bytes(
                "c" * 40,
                "d" * 40,
                stale_review["patch_sha256"],
            )
        ).hexdigest()
        stale_review["review_input_sha256"] = "sha256:" + hashlib.sha256(
            _review_input_bytes(stale_review)
        ).hexdigest()
        stale_review_bytes = (
            json.dumps(stale_review, indent=2, sort_keys=True) + "\n"
        ).encode()
        stale_checksum = (
            hashlib.sha256(stale_review_bytes).hexdigest()
            + "  independent-ai-review.json\n"
        )
        stale_buffer = io.BytesIO()
        with zipfile.ZipFile(
            stale_buffer, "w", compression=zipfile.ZIP_STORED
        ) as bundle:
            bundle.writestr("independent-ai-review.json", stale_review_bytes)
            bundle.writestr("independent-ai-review.sha256", stale_checksum)
        stale_archive = stale_buffer.getvalue()
        stale_patch["technical_review_archive"] = stale_archive
        stale_patch["technical_review_artifacts"]["artifacts"][0]["digest"] = (
            "sha256:" + hashlib.sha256(stale_archive).hexdigest()
        )
        stale_request = deepcopy(request)
        stale_request["technical_review"]["evidence_sha256"] = (
            "sha256:" + hashlib.sha256(stale_review_bytes).hexdigest()
        )
        cases.append(("stale-patch-with-coherent-self-digests", stale_request, stale_patch))

        for label, altered_request, altered_snapshot in cases:
            with self.subTest(label=label), self.assertRaises(ReleasePublicationError):
                verify_publication_snapshot(altered_request, altered_snapshot)

        blocking = deepcopy(snapshot)
        archive = blocking["technical_review_archive"]
        with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
            review = json.loads(bundle.read("independent-ai-review.json"))
        review["findings"] = [
            {"severity": "HIGH", "path": "core/security.py", "reason": "blocker"}
        ]
        review_bytes = (json.dumps(review, indent=2, sort_keys=True) + "\n").encode()
        checksum = hashlib.sha256(review_bytes).hexdigest() + "  independent-ai-review.json\n"
        rebuilt = io.BytesIO()
        with zipfile.ZipFile(rebuilt, "w", compression=zipfile.ZIP_STORED) as bundle:
            bundle.writestr("independent-ai-review.json", review_bytes)
            bundle.writestr("independent-ai-review.sha256", checksum)
        blocking_archive = rebuilt.getvalue()
        blocking["technical_review_archive"] = blocking_archive
        blocking["technical_review_artifacts"]["artifacts"][0]["digest"] = (
            "sha256:" + hashlib.sha256(blocking_archive).hexdigest()
        )
        blocking_request = deepcopy(request)
        blocking_request["technical_review"]["evidence_sha256"] = (
            "sha256:" + hashlib.sha256(review_bytes).hexdigest()
        )
        with self.assertRaises(ReleasePublicationError):
            verify_publication_snapshot(blocking_request, blocking)

        # The sealed document's generated_at belongs to the external OpenClaw
        # review. It cannot claim that the review happened after the later
        # sealing workflow had already started.
        late_external = deepcopy(snapshot)
        with zipfile.ZipFile(
            io.BytesIO(late_external["technical_review_archive"])
        ) as bundle:
            late_review = json.loads(bundle.read("independent-ai-review.json"))
        late_review["generated_at"] = "2026-08-12T03:03:00Z"
        late_review_bytes = (
            json.dumps(late_review, indent=2, sort_keys=True) + "\n"
        ).encode()
        late_checksum = (
            hashlib.sha256(late_review_bytes).hexdigest()
            + "  independent-ai-review.json\n"
        )
        rebuilt = io.BytesIO()
        with zipfile.ZipFile(rebuilt, "w", compression=zipfile.ZIP_STORED) as bundle:
            bundle.writestr("independent-ai-review.json", late_review_bytes)
            bundle.writestr("independent-ai-review.sha256", late_checksum)
        late_archive = rebuilt.getvalue()
        late_external["technical_review_archive"] = late_archive
        late_external["technical_review_artifacts"]["artifacts"][0]["digest"] = (
            "sha256:" + hashlib.sha256(late_archive).hexdigest()
        )
        late_request = deepcopy(request)
        late_request["technical_review"]["evidence_sha256"] = (
            "sha256:" + hashlib.sha256(late_review_bytes).hexdigest()
        )
        with self.assertRaises(ReleasePublicationError):
            verify_publication_snapshot(late_request, late_external)

    def test_every_premerge_authority_fact_precedes_merge(self) -> None:
        request = self._request()
        snapshot = self._snapshot(request)
        verify_publication_snapshot(request, snapshot)
        cases: list[tuple[str, dict]] = []
        late_check = deepcopy(snapshot)
        late_check["pull_request_check_runs"][0]["started_at"] = (
            "2026-08-12T03:31:00Z"
        )
        late_check["pull_request_check_runs"][0]["completed_at"] = (
            "2026-08-12T03:32:00Z"
        )
        cases.append(("required-check", late_check))
        late_review = deepcopy(snapshot)
        late_review["technical_review_run"]["updated_at"] = (
            "2026-08-12T03:31:00Z"
        )
        cases.append(("technical-review", late_review))
        late_approval = deepcopy(snapshot)
        late_approval["reviews"][0]["submitted_at"] = "2026-08-12T03:31:00Z"
        cases.append(("owner-approval", late_approval))
        for label, altered in cases:
            with self.subTest(label=label), self.assertRaises(ReleasePublicationError):
                verify_publication_snapshot(request, altered)

    def test_release_identity_chain_rejects_non_owner_execution(self) -> None:
        request = self._request()
        snapshot = self._snapshot(request)
        mutations = []
        wrong_actor = deepcopy(snapshot)
        wrong_actor["tag_workflow"]["actor"]["login"] = "mallory"
        mutations.append(("tag-workflow", wrong_actor))
        wrong_release = deepcopy(snapshot)
        wrong_release["release"]["author"]["id"] = 1
        mutations.append(("release-author", wrong_release))
        wrong_owner = deepcopy(snapshot)
        wrong_owner["reviews"][0]["user"]["id"] = 1
        mutations.append(("owner-review", wrong_owner))
        wrong_embedded_tag = deepcopy(snapshot)
        wrong_embedded_tag["tag_object"]["tag"] = "v9.9.9"
        mutations.append(("embedded-tag-name", wrong_embedded_tag))
        wrong_artifact_url = deepcopy(snapshot)
        wrong_artifact_url["artifacts"]["artifacts"][0]["url"] = (
            "https://api.github.com/repos/90le/agent-team-engineering/actions/artifacts/999"
        )
        mutations.append(("release-artifact-url-id", wrong_artifact_url))
        wrong_review_artifact_url = deepcopy(snapshot)
        wrong_review_artifact_url["technical_review_artifacts"]["artifacts"][0][
            "archive_download_url"
        ] = "https://api.github.com/repos/90le/agent-team-v10-review-private/actions/artifacts/999/zip"
        mutations.append(("review-artifact-url-id", wrong_review_artifact_url))
        late_artifact = deepcopy(snapshot)
        late_artifact["artifacts"]["artifacts"][0]["created_at"] = (
            "2026-08-12T05:31:00Z"
        )
        mutations.append(("release-artifact-chronology", late_artifact))
        for label, altered in mutations:
            with self.subTest(label=label), self.assertRaises(ReleasePublicationError):
                verify_publication_snapshot(request, altered)

    def test_active_ruleset_required_check_cannot_be_omitted(self) -> None:
        request = self._request()
        snapshot = self._snapshot(request)
        snapshot["active_main_rules"] = [
            {
                "type": "required_status_checks",
                "parameters": {
                    "required_status_checks": [
                        {"context": "release-policy", "integration_id": 15368}
                    ]
                },
            }
        ]
        with self.assertRaises(ReleasePublicationError):
            verify_publication_snapshot(request, snapshot)

    def test_ruleset_only_and_stricter_app_binding_are_supported(self) -> None:
        request = self._request()
        snapshot = self._snapshot(request)
        snapshot["required_status_checks"] = None
        snapshot["active_main_rules"] = [
            {
                "type": "required_status_checks",
                "parameters": {
                    "required_status_checks": [
                        {"context": "validate", "integration_id": 15368},
                        {"context": "conformance", "integration_id": 15368},
                    ]
                },
            }
        ]
        verify_publication_snapshot(request, snapshot)

        combined = self._snapshot(request)
        combined["active_main_rules"] = [
            {
                "type": "required_status_checks",
                "parameters": {
                    "required_status_checks": [
                        {"context": "validate", "integration_id": -1}
                    ]
                },
            }
        ]
        verify_publication_snapshot(request, combined)

        required_workflow = self._snapshot(request)
        required_workflow["active_main_rules"] = [
            {"type": "workflows", "parameters": {"workflows": []}}
        ]
        with self.assertRaises(ReleasePublicationError):
            verify_publication_snapshot(request, required_workflow)

    def test_any_app_context_rejects_ambiguous_legacy_and_check_run_sources(self) -> None:
        request = self._request()
        snapshot = self._snapshot(request)
        request["pull_request"]["checks"][0]["app_id"] = -1
        request["merged_main"]["checks"][0]["app_id"] = -1
        snapshot["required_status_checks"]["checks"][0]["app_id"] = -1
        snapshot["pull_request_statuses"] = [
            {
                "id": 500,
                "context": "validate",
                "sha": "c" * 40,
                "state": "failure",
                "target_url": "https://ci.example.test/failed",
                "created_at": "2026-08-12T00:30:00Z",
            }
        ]
        with self.assertRaises(ReleasePublicationError):
            verify_publication_snapshot(request, snapshot)

    def test_artifact_redirect_strips_authorization_and_limits_response(self) -> None:
        api_url = "https://api.github.com/repos/90le/agent-team-engineering/actions/artifacts/555/zip"

        class SyntheticResponse:
            def __enter__(self) -> "SyntheticResponse":
                return self

            def __exit__(self, *arguments: object) -> None:
                return None

            headers = {"Content-Length": "7"}

            def read(self, amount: int) -> bytes:
                return b"fixture"

        observed_headers: list[dict[str, str]] = []

        def fake_open(request: urllib.request.Request, timeout: int) -> SyntheticResponse:
            observed_headers.append(dict(request.header_items()))
            if len(observed_headers) == 1:
                headers = {
                    "Location": "https://productionresultssa11.blob.core.windows.net/archive"
                }
                raise urllib.error.HTTPError(request.full_url, 302, "Found", headers, None)
            return SyntheticResponse()

        with mock.patch("urllib.request.build_opener") as build_opener:
            build_opener.return_value.open.side_effect = fake_open
            self.assertEqual(_github_download(api_url, "SYNTHETIC-ONLY"), b"fixture")
        self.assertEqual(
            observed_headers[0].get("Authorization"), "Bearer SYNTHETIC-ONLY"
        )
        self.assertNotIn("Authorization", observed_headers[1])
        self.assertNotIn("X-Github-api-version", observed_headers[1])

        with self.assertRaises(ReleasePublicationError):
            _github_download("https://evil.example.test/archive", "SYNTHETIC-ONLY")
        for redirected in (
            "https://127.0.0.1/archive",
            "https://[::1]/archive",
            "https://169.254.169.254/archive",
            "https://10.0.0.1/archive",
            "https://localhost/archive",
            "https://objects.example.test:8443/archive",
        ):
            with self.subTest(redirected=redirected), self.assertRaises(
                ReleasePublicationError
            ):
                _require_public_https_url(redirected, "redirect")
        for redirected in (
            "https://example.com/archive",
            "https://blob.core.windows.net.attacker.example/archive",
        ):
            with self.subTest(redirected=redirected), self.assertRaises(
                ReleasePublicationError
            ):
                _require_artifact_redirect_url(redirected)

    def test_download_is_required_and_all_checksums_are_verified(self) -> None:
        request = self._request()
        tag_evidence, contents = self._tag_evidence()
        archive = self._archive(tag_evidence, contents)
        snapshot = self._snapshot(request)
        snapshot["artifacts"]["artifacts"][0]["digest"] = "sha256:" + hashlib.sha256(archive).hexdigest()
        publication = verify_publication_snapshot(request, snapshot)
        with self.assertRaises(ReleasePublicationError):
            build_final_release_index(
                request,
                publication,
                tag_evidence,
                {"status": "PASS"},
                {"status": "NOT_RUN", "evidence": []},
            )
        observed, _ = verify_downloaded_artifact(
            archive,
            publication,
            request,
            downloaded_at=datetime(2026, 8, 12, 6, 10, tzinfo=timezone.utc),
        )
        self.assertEqual(observed["commit"], "b" * 40)
        with self.assertRaises(ReleasePublicationError):
            verify_downloaded_artifact(
                archive,
                deepcopy(publication),
                request,
                downloaded_at=datetime(2026, 10, 12, 6, 10, tzinfo=timezone.utc),
            )
        corrupted = bytearray(archive)
        corrupted[-1] ^= 1
        with self.assertRaises(ReleasePublicationError):
            verify_downloaded_artifact(bytes(corrupted), deepcopy(publication), request)

    def test_finalizer_emits_only_all_pass_accepted_index_outside_source(self) -> None:
        request = self._request()
        tag_evidence, contents = self._tag_evidence()
        archive = self._archive(tag_evidence, contents)
        snapshot = self._snapshot(request)
        snapshot["artifacts"]["artifacts"][0]["digest"] = "sha256:" + hashlib.sha256(archive).hexdigest()
        publication = verify_publication_snapshot(request, snapshot)
        tag_evidence, _ = verify_downloaded_artifact(
            archive,
            publication,
            request,
            downloaded_at=datetime(2026, 8, 12, 6, 10, tzinfo=timezone.utc),
        )
        anonymous = {
            "status": "PASS",
            "workflow_url": None,
            "source_url": "https://github.com/90le/agent-team-engineering.git",
            "tag": "v1.0.0",
            "tag_object": "a" * 40,
            "commit": "b" * 40,
            "verified_at": "2026-08-12T06:20:00Z",
            "commands": list(ANONYMOUS_COMMANDS),
            "unauthenticated_git_transport": True,
            "caller_credentials_inherited": False,
            "same_uid_filesystem_isolated": False,
            "write_isolation": False,
            "external_writes_verified": False,
        }
        final = build_final_release_index(
            request,
            publication,
            tag_evidence,
            anonymous,
            self._live_scm_fixture(),
            generated_at=datetime(2026, 8, 12, 6, 21, tzinfo=timezone.utc),
        )
        self.assertEqual(final["status"], "ACCEPTED")
        self.assertEqual(final["release_status"], "RELEASED")
        self.assertTrue(all(gate["status"] == "PASS" for gate in final["gates"]))
        self.assertFalse(final["boundaries"]["standalone_tamper_evident"])
        self.assertFalse(final["boundaries"]["cryptographically_authenticated"])
        for label, mutation in (
            (
                "runtime",
                lambda value: value["publication"]["technical_review"].update(
                    {"reviewer_runtime": "openclaw/attacker-controlled-runtime"}
                ),
            ),
            (
                "post-merge-review",
                lambda value: value["publication"]["technical_review"].update(
                    {"completed_at": "2026-08-12T03:31:00Z"}
                ),
            ),
            (
                "release-author",
                lambda value: value["publication"]["github_release"].update(
                    {"author_id": 1}
                ),
            ),
            (
                "missing-artifact-url",
                lambda value: value["publication"]["evidence_artifact"].update(
                    {"url": None}
                ),
            ),
            (
                "missing-artifact-digest",
                lambda value: value["publication"]["evidence_artifact"].update(
                    {"digest": None}
                ),
            ),
            (
                "missing-pull-request-url",
                lambda value: value["publication"]["pull_request"].update(
                    {"url": None}
                ),
            ),
            (
                "wrong-artifact-name",
                lambda value: value["publication"]["evidence_artifact"].update(
                    {"name": "release-evidence-v9.9.9"}
                ),
            ),
            (
                "wrong-release-tag",
                lambda value: value["publication"]["github_release"].update(
                    {"tag": "v9.9.9"}
                ),
            ),
            (
                "empty-gate-evidence",
                lambda value: [record.update({"evidence": []}) for record in value["gates"]],
            ),
            (
                "fabricated-check-time",
                lambda value: value["publication"]["merged_main"]["checks"][0].update(
                    {"completed_at": "2026-08-12T04:59:00Z"}
                ),
            ),
            (
                "service-vs-downloaded-digest",
                lambda value: (
                    value["publication"]["evidence_artifact"].update(
                        {"downloaded_archive_digest": "sha256:" + "f" * 64}
                    ),
                    next(
                        gate
                        for gate in value["gates"]
                        if gate["id"] == "evidence-artifact-download"
                    )["evidence"].__setitem__(1, "sha256:" + "f" * 64),
                ),
            ),
            (
                "download-after-expiry",
                lambda value: value["publication"]["evidence_artifact"].update(
                    {"expires_at": "2026-08-12T06:05:00Z", "retention_days": 1}
                ),
            ),
            (
                "fabricated-retention-days",
                lambda value: value["publication"]["evidence_artifact"].update(
                    {"retention_days": 29}
                ),
            ),
            (
                "artifact-before-tag",
                lambda value: value["publication"]["evidence_artifact"].update(
                    {"created_at": "2026-08-12T04:59:59Z"}
                ),
            ),
            (
                "false-standalone-tamper-claim",
                lambda value: value["boundaries"].update(
                    {"standalone_tamper_evident": True}
                ),
            ),
            (
                "false-cryptographic-authentication-claim",
                lambda value: value["boundaries"].update(
                    {"cryptographically_authenticated": True}
                ),
            ),
        ):
            altered = deepcopy(final)
            mutation(altered)
            with self.subTest(label=label), self.assertRaises(ReleaseEvidenceError):
                validate_release_evidence(altered)
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "v1.0.0-final-release-index.json"
            write_final_index(final, output)
            self.assertTrue(output.is_file())
            with self.assertRaises(ReleasePublicationError):
                write_final_index(final, output)

    def test_request_requires_exact_urls_and_no_unknown_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "request.json"
            value = self._request()
            value["github_release_url"] = None
            path.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaises(ReleasePublicationError):
                load_finalization_request(path)

            for field, suffix in (
                ("tag_workflow_url", "/extra"),
                ("tag_workflow_url", "?query=1"),
                ("github_release_url", "/extra"),
                ("github_release_url", "?query=1"),
            ):
                value = self._request()
                value[field] += suffix
                path.write_text(json.dumps(value), encoding="utf-8")
                with self.subTest(field=field, suffix=suffix), self.assertRaises(
                    ReleasePublicationError
                ):
                    load_finalization_request(path)

            for nested, suffix in (
                (("technical_review", "evidence_url"), "/extra"),
                (("owner_approval", "url"), "/extra"),
            ):
                value = self._request()
                value[nested[0]][nested[1]] += suffix
                path.write_text(json.dumps(value), encoding="utf-8")
                with self.subTest(nested=nested), self.assertRaises(
                    ReleasePublicationError
                ):
                    load_finalization_request(path)

    def test_archive_member_count_and_name_length_are_bounded(self) -> None:
        with io.BytesIO() as buffer:
            with zipfile.ZipFile(buffer, "w", zipfile.ZIP_STORED) as bundle:
                for index in range(129):
                    bundle.writestr(f"empty-{index}", b"")
            too_many = buffer.getvalue()
        with self.assertRaises(ReleasePublicationError):
            _review_archive_contents(too_many)

        with io.BytesIO() as buffer:
            with zipfile.ZipFile(buffer, "w", zipfile.ZIP_STORED) as bundle:
                bundle.writestr("x" * 1025, b"")
            long_name = buffer.getvalue()
        with self.assertRaises(ReleasePublicationError):
            _review_archive_contents(long_name)

    def test_run_artifacts_are_fully_paginated_and_identity_checked(self) -> None:
        first_page = {
            "total_count": 101,
            "artifacts": [{"id": index} for index in range(1, 101)],
        }
        second_page = {"total_count": 101, "artifacts": [{"id": 101}]}
        with mock.patch(
            "tools.release_publication._github_json",
            side_effect=[first_page, second_page],
        ) as github_json:
            result = _github_run_artifacts("90le/example", "123", "TOKEN")
        self.assertEqual(result["total_count"], 101)
        self.assertEqual(len(result["artifacts"]), 101)
        self.assertIn("page=2", github_json.call_args_list[1].args[0])

        with mock.patch(
            "tools.release_publication._github_json",
            side_effect=[first_page, {"total_count": 102, "artifacts": [{"id": 101}]}],
        ), self.assertRaises(ReleasePublicationError):
            _github_run_artifacts("90le/example", "123", "TOKEN")

        duplicate = {"total_count": 2, "artifacts": [{"id": 1}, {"id": 1}]}
        with mock.patch(
            "tools.release_publication._github_json", return_value=duplicate
        ), self.assertRaises(ReleasePublicationError):
            _github_run_artifacts("90le/example", "123", "TOKEN")

    def test_live_scm_artifacts_must_match_tagged_report_bytes(self) -> None:
        _, contents = self._tag_evidence()
        first_path = "acceptance/github-scm-v10-first-run.json"
        replay_path = "acceptance/github-scm-v10-replay.json"
        reports = []
        for run_id, path in (("101", first_path), ("102", replay_path)):
            report = {
                "base_commit": "a" * 40,
                "workflow": {
                    "run_id": run_id,
                    "run_url": (
                        "https://github.com/90le/agent-team-v10-conformance-private/"
                        f"actions/runs/{run_id}"
                    ),
                },
            }
            encoded = (json.dumps(report, sort_keys=True) + "\n").encode()
            contents[f"bundle/{path}"] = encoded
            reports.append(encoded)

        runs = []
        artifact_pages = []
        archives = []
        for index, (run_id, encoded) in enumerate(zip((101, 102), reports), start=1):
            runs.append(
                {
                    "id": run_id,
                    "run_attempt": 1,
                    "status": "completed",
                    "conclusion": "success",
                    "event": "workflow_dispatch",
                    "head_branch": "main",
                    "head_sha": "a" * 40,
                    "path": ".github/workflows/agent-team-v10-conformance.yml",
                    "html_url": (
                        "https://github.com/90le/agent-team-v10-conformance-private/"
                        f"actions/runs/{run_id}"
                    ),
                    "repository": {
                        "full_name": "90le/agent-team-v10-conformance-private",
                        "private": True,
                    },
                    "actor": {"login": "90le", "id": 68719118, "type": "User"},
                    "triggering_actor": {
                        "login": "90le",
                        "id": 68719118,
                        "type": "User",
                    },
                }
            )
            with io.BytesIO() as buffer:
                with zipfile.ZipFile(buffer, "w", zipfile.ZIP_STORED) as bundle:
                    bundle.writestr("github-scm-conformance.json", encoded)
                archive = buffer.getvalue()
            archives.append(archive)
            artifact_id = 1000 + index
            artifact_pages.append(
                {
                    "total_count": 1,
                    "artifacts": [
                        {
                            "id": artifact_id,
                            "name": f"github-scm-conformance-{run_id}-1",
                            "expired": False,
                            "workflow_run": {"id": run_id},
                            "url": (
                                "https://api.github.com/repos/90le/"
                                "agent-team-v10-conformance-private/actions/artifacts/"
                                f"{artifact_id}"
                            ),
                            "archive_download_url": (
                                "https://api.github.com/repos/90le/"
                                "agent-team-v10-conformance-private/actions/artifacts/"
                                f"{artifact_id}/zip"
                            ),
                            "digest": "sha256:"
                            + hashlib.sha256(archive).hexdigest(),
                        }
                    ],
                }
            )

        side_effect = [runs[0], artifact_pages[0], runs[1], artifact_pages[1]]
        with mock.patch(
            "tools.release_publication._github_json", side_effect=side_effect
        ), mock.patch(
            "tools.release_publication._github_download", side_effect=archives
        ):
            observed = verify_live_external_scm_artifacts(contents, "TOKEN")
        self.assertEqual(observed["status"], "PASS")
        self.assertEqual(len(observed["evidence"]), 4)

        forged = deepcopy(contents)
        forged[f"bundle/{first_path}"] += b" "
        with mock.patch(
            "tools.release_publication._github_json", side_effect=side_effect
        ), mock.patch(
            "tools.release_publication._github_download", side_effect=archives
        ), self.assertRaises(ReleasePublicationError):
            verify_live_external_scm_artifacts(forged, "TOKEN")

    def test_anonymous_environment_is_literal_minimal_allowlist(self) -> None:
        injected = {
            "GITHUB_TOKEN": "github-token-must-not-pass",
            "GH_TOKEN": "gh-token-must-not-pass",
            "GIT_CONFIG_COUNT": "2",
            "GIT_CONFIG_KEY_0": "credential.helper",
            "GIT_CONFIG_VALUE_0": "!exfiltrate",
            "GIT_ASKPASS": "/tmp/askpass",
            "SSH_ASKPASS": "/tmp/ssh-askpass",
            "SSH_AUTH_SOCK": "/tmp/agent.sock",
            "AWS_SECRET_ACCESS_KEY": "cloud-secret",
            "PYTHONPATH": "/tmp/injected-python",
            "CUSTOM_PASSWORD": "password-must-not-pass",
        }
        with tempfile.TemporaryDirectory() as temporary, mock.patch.dict(
            os.environ, injected, clear=False
        ):
            home = Path(temporary) / "anonymous-home"
            environment = _anonymous_environment(home)
        self.assertEqual(
            set(environment),
            {
                "HOME",
                "PATH",
                "LANG",
                "LC_ALL",
                "PYTHONNOUSERSITE",
                "PYTHONDONTWRITEBYTECODE",
                "GIT_CONFIG_NOSYSTEM",
                "GIT_CONFIG_GLOBAL",
                "GIT_CONFIG_SYSTEM",
                "GIT_TERMINAL_PROMPT",
                "GCM_INTERACTIVE",
                "SSH_ASKPASS_REQUIRE",
            },
        )
        self.assertEqual(environment["HOME"], str(home))
        self.assertEqual(environment["GIT_CONFIG_GLOBAL"], os.devnull)
        self.assertEqual(environment["GIT_CONFIG_SYSTEM"], os.devnull)
        self.assertEqual(environment["SSH_ASKPASS_REQUIRE"], "never")
        for key in injected:
            self.assertNotIn(key, environment)

    def test_anonymous_install_detaches_to_peeled_tag_before_running_candidate(self) -> None:
        tag_object = "a" * 40
        peeled = "b" * 40
        calls: list[list[str]] = []

        def fake_run(
            arguments: list[str], cwd: Path, environment: dict[str, str]
        ) -> str:
            calls.append([str(item) for item in arguments])
            if arguments[:2] == ["git", "clone"]:
                Path(arguments[-1]).mkdir(parents=True)
                return ""
            if arguments[:2] == ["git", "rev-parse"]:
                target = str(arguments[2])
                if target.startswith("refs/tags/"):
                    return tag_object
                if target.endswith("^{}"):
                    return peeled
                if target == "HEAD":
                    return peeled
            if arguments[:3] == ["git", "cat-file", "-t"]:
                return "tag"
            if arguments[:3] == ["git", "status", "--porcelain"]:
                return ""
            if "host" in arguments and "plan" in arguments:
                plan_path = Path(arguments[arguments.index("--output") + 1])
                plan_path.write_text(
                    json.dumps({"proposal_digest": "sha256:" + "1" * 64}),
                    encoding="utf-8",
                )
                return ""
            if "writer-authority-validate" in arguments:
                return json.dumps(
                    {
                        "status": "VALID",
                        "automatic_execution": False,
                        "identity_or_signature_verified": False,
                    }
                )
            return ""

        with mock.patch("tools.release_publication._run", side_effect=fake_run):
            run_anonymous_exact_tag_install("v1.0.0", tag_object, peeled)
        clone = next(call for call in calls if call[:2] == ["git", "clone"])
        self.assertIn("--no-checkout", clone)
        self.assertNotIn("--branch", clone)
        checkout_index = next(
            index
            for index, call in enumerate(calls)
            if call[:4] == ["git", "-c", "advice.detachedHead=false", "checkout"]
        )
        first_candidate_index = next(
            index
            for index, call in enumerate(calls)
            if call and (call[0].endswith("python") or call[0].endswith("python3"))
        )
        self.assertLess(checkout_index, first_candidate_index)
        self.assertIn(
            ["git", "rev-parse", "HEAD"],
            calls[checkout_index:first_candidate_index],
        )


if __name__ == "__main__":
    unittest.main()
