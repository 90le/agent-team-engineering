from __future__ import annotations

import hashlib
import io
import json
import tempfile
import unittest
import zipfile
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

from tools.release_evidence import (
    EVIDENCE_ASSETS,
    LOCAL_GATE_IDS,
    ReleaseEvidenceError,
    build_release_evidence,
    validate_release_evidence,
    write_release_evidence,
)
from tools.release_publication import (
    ReleasePublicationError,
    build_final_release_index,
    load_finalization_request,
    verify_downloaded_artifact,
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
        return {gate_id: [f"fixture:{gate_id}"] for gate_id in LOCAL_GATE_IDS}

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

    def _request(self) -> dict:
        return {
            "repository": "90le/agent-team-engineering",
            "release": "v1.0.0",
            "commit": "b" * 40,
            "pull_request": {
                "number": 13,
                "head_commit": "c" * 40,
                "checks_url": "https://github.com/90le/agent-team-engineering/actions/runs/111",
            },
            "independent_review": {
                "reviewer": "independent-reviewer",
                "url": "https://github.com/90le/agent-team-engineering/pull/13#pullrequestreview-99",
            },
            "merged_main_workflow_url": "https://github.com/90le/agent-team-engineering/actions/runs/222",
            "tag_workflow_url": "https://github.com/90le/agent-team-engineering/actions/runs/123456",
            "github_release_url": "https://github.com/90le/agent-team-engineering/releases/tag/v1.0.0",
        }

    def _snapshot(self) -> dict:
        request = self._request()
        return {
            "pull_request": {
                "html_url": "https://github.com/90le/agent-team-engineering/pull/13",
                "state": "closed",
                "merged": True,
                "merge_commit_sha": "b" * 40,
                "head": {"sha": "c" * 40},
                "user": {"login": "change-author"},
            },
            "reviews": [
                {
                    "state": "APPROVED",
                    "user": {"login": "independent-reviewer"},
                    "html_url": request["independent_review"]["url"],
                    "commit_id": "c" * 40,
                }
            ],
            "tag_ref": {
                "ref": "refs/tags/v1.0.0",
                "object": {"type": "tag", "sha": "a" * 40},
            },
            "tag_object": {
                "sha": "a" * 40,
                "object": {"type": "commit", "sha": "b" * 40},
            },
            "release": {
                "tag_name": "v1.0.0",
                "html_url": request["github_release_url"],
                "draft": False,
                "prerelease": False,
                "published_at": "2026-08-12T02:00:00Z",
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
            },
            "main_workflow": {
                "status": "completed",
                "conclusion": "success",
                "head_sha": "b" * 40,
                "html_url": request["merged_main_workflow_url"],
            },
            "checks_workflow": {
                "status": "completed",
                "conclusion": "success",
                "head_sha": "c" * 40,
                "html_url": request["pull_request"]["checks_url"],
            },
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
                        "created_at": "2026-08-12T01:00:00Z",
                        "expires_at": "2026-09-11T01:00:00Z",
                    }
                ]
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
        snapshot = self._snapshot()
        wrong_commit = deepcopy(snapshot)
        wrong_commit["tag_workflow"]["head_sha"] = "d" * 40
        with self.assertRaises(ReleasePublicationError):
            verify_publication_snapshot(request, wrong_commit)
        no_review = deepcopy(snapshot)
        no_review["reviews"] = []
        with self.assertRaises(ReleasePublicationError):
            verify_publication_snapshot(request, no_review)

    def test_download_is_required_and_all_checksums_are_verified(self) -> None:
        request = self._request()
        tag_evidence, contents = self._tag_evidence()
        archive = self._archive(tag_evidence, contents)
        snapshot = self._snapshot()
        snapshot["artifacts"]["artifacts"][0]["digest"] = "sha256:" + hashlib.sha256(archive).hexdigest()
        publication = verify_publication_snapshot(request, snapshot)
        with self.assertRaises(ReleasePublicationError):
            build_final_release_index(
                request,
                publication,
                tag_evidence,
                {"status": "PASS"},
            )
        observed, _ = verify_downloaded_artifact(
            archive,
            publication,
            request,
            downloaded_at=datetime(2026, 8, 12, 3, 0, tzinfo=timezone.utc),
        )
        self.assertEqual(observed["commit"], "b" * 40)
        corrupted = bytearray(archive)
        corrupted[-1] ^= 1
        with self.assertRaises(ReleasePublicationError):
            verify_downloaded_artifact(bytes(corrupted), deepcopy(publication), request)

    def test_finalizer_emits_only_all_pass_accepted_index_outside_source(self) -> None:
        request = self._request()
        tag_evidence, contents = self._tag_evidence()
        archive = self._archive(tag_evidence, contents)
        snapshot = self._snapshot()
        snapshot["artifacts"]["artifacts"][0]["digest"] = "sha256:" + hashlib.sha256(archive).hexdigest()
        publication = verify_publication_snapshot(request, snapshot)
        tag_evidence, _ = verify_downloaded_artifact(archive, publication, request)
        anonymous = {
            "status": "PASS",
            "workflow_url": None,
            "source_url": "https://github.com/90le/agent-team-engineering.git",
            "tag": "v1.0.0",
            "tag_object": "a" * 40,
            "commit": "b" * 40,
            "verified_at": "2026-08-12T04:00:00Z",
            "commands": ["anonymous exact-tag verification"],
            "maintainer_credentials_available": False,
            "external_writes": False,
        }
        final = build_final_release_index(
            request,
            publication,
            tag_evidence,
            anonymous,
            generated_at=datetime(2026, 8, 12, 4, 1, tzinfo=timezone.utc),
        )
        self.assertEqual(final["status"], "ACCEPTED")
        self.assertEqual(final["release_status"], "RELEASED")
        self.assertTrue(all(gate["status"] == "PASS" for gate in final["gates"]))
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


if __name__ == "__main__":
    unittest.main()
