---
name: verify-release
description: Independently verify a software release candidate using clean-runner tests, acceptance criteria, security checks, provenance, and an immutable artifact digest. Use when QA must produce test evidence, accept or reject staging, or verify that the reviewed commit and staged artifact are identical before production approval.
---

# Verify Release

1. Use a clean, isolated Runner without production secrets, data mounts or Docker Socket access.
2. Check out the exact reviewed commit and execute required lint, unit, integration, contract, security and acceptance suites.
3. Record commands, runner identity, timestamps, results and evidence references without leaking sensitive output.
4. Build or select the release candidate once and record its immutable digest.
5. Deploy that digest to staging through the permitted release interface and run smoke, health and acceptance checks.
6. Confirm the release candidate, review decision and all required checks reference the same commit and digest.
7. Emit evidence conforming to `schemas/test-evidence.schema.json` and the applicable quality gates.

Do not waive failures, mutate source, use author-supplied success claims as sole evidence or approve production. Stop on flaky unresolved tests, provenance gaps, digest mismatch or unavailable rollback verification.
