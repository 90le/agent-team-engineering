---
name: verify-release
description: Independently verify a software release candidate using clean-runner tests, acceptance criteria, security checks, provenance, and an immutable artifact digest. Use when QA must produce test evidence, accept or reject staging, or verify that the reviewed commit and staged artifact are identical before production approval.
---

# Verify Release

For an Agent Team Engineering v1.0 release, read `AI-BOOTSTRAP.md` and `docs/16-release/v1.0-acceptance.md` completely. The acceptance document is a required-gate contract, not proof that remote work is finished.

1. Use a clean, isolated Runner without production secrets, production data mounts, PVE/NAS paths, or Docker Socket access.
2. Check out the exact reviewed commit and execute repository validation, all unit/security/contract tests, Skill and plugin validation, cross-AI takeover, release audit from `v0.9.0` with external evidence required, cold start, and simulated exact-tag release smoke.
3. Verify WriterTopology's exact three-digest chain and both false boundary fields. Offline `identity_or_signature_verified: false` means the command does not authenticate an approver or verify a signature.
4. Verify host lifecycle crash/replay, legacy-lock, uninstall-preview, tombstone, non-overwrite, drift, and negative safety gates. Verify explicit `0.9.0 → 1.0.0` instance upgrade and rollback evidence separately from host installation.
5. Record commands, exact commit, Runner identity, timestamps, exit codes, immutable artifact digests, rollback material, and evidence references without leaking sensitive output.
6. Require external SCM first-run/replay evidence bound to the exact protected implementation. Reject stale evidence after a protected path changes; no merge or deployment may occur.
7. Require passing PR checks for the exact head, an independently authored `APPROVED` review with its URL, passing merged-main checks for the exact accepted commit, an annotated `v1.0.0` tag object peeled to that commit, passing tag workflow, and a matching non-draft GitHub Release. URL-less or cross-commit statements are not evidence.
8. Keep the two machine-evidence stages separate. The tag workflow may emit only `TAG_WORKFLOW_EVIDENCE` with `PARTIAL` / `NOT_PUBLISHED`; it must leave its own completion, artifact upload/download, Release and anonymous-install gates `NOT_RUN`. Never edit or promote that artifact in place.
9. After publication, use `tools/release_publication.py` from a reviewed copy with a minimum read-only GitHub token and an external request file. Verify live PR/review/main/tag/workflow/Release facts, then download the exact non-expired tag-run artifact. Require artifact ID, URL, service SHA-256 digest, creation/expiry and retention, plus verified archive, `SHA256SUMS`, tag-evidence, v10, SBOM, provenance and both SCM-report digests. Metadata without a successful download is `NOT_RUN`, not `PASS`.
10. Let the finalizer itself re-run anonymous HTTPS exact-tag clone, Factory install/verify/Doctor, team creation, disposable host lifecycle/replay-safe uninstall, and writer-authority validation after removing maintainer credentials and disabling Git credential prompting. A supplied anonymous-install claim is insufficient.
11. Write the resulting `FINAL_RELEASE_INDEX` outside every Factory checkout. It may say `ACCEPTED` / `RELEASED` only when all twenty gates are `PASS` and every identity binds the same commit, annotated tag object and workflow artifact. Do not modify the tagged source, create/move tags, publish a Release, or perform a GitHub write from the finalizer.
12. Confirm GitHub Actions remain pinned by full SHA and release artifact upload uses the reviewed `actions/upload-artifact` v7.0.1 commit with Node 24.
13. Record every gate as `PASS`, `FAIL`, or `NOT_RUN` with its URL or digest. Missing remote identity, missing review URL, failed/other-commit workflow, duplicate or expired artifact, skipped download, checksum mismatch, authenticated/local-clone substitution, or missing evidence is never inferred `PASS`.

Do not waive failures, mutate source while verifying, use author-supplied success claims as sole evidence, move a tag, rebuild an artifact from another commit, or approve production. Stop on a failed, flaky, skipped, stale, identity-mismatched, provenance-incomplete, or rollback-incomplete gate. This Factory release process does not itself deploy a user project.
