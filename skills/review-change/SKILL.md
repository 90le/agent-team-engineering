---
name: review-change
description: Independently review a proposed software change against its accepted specification, architecture, security policy, tests, migration, documentation, and rollback. Use when a reviewer Agent must inspect a commit or pull request and emit a structured approval, changes-requested, or blocked decision without editing the author's branch or merging.
---

# Review Change

1. Verify reviewer identity differs from the recorded author and the reviewed commit is exact.
2. Read the accepted specification and inspect the actual diff, not the author's summary alone.
3. Check correctness, missing cases, security boundaries, data handling, compatibility, concurrency, operability and scope drift.
4. Verify tests exercise the changed behavior and negative paths; do not treat generated logs as proof without check references.
5. Confirm migrations, documentation, observability and rollback match the risk level.
6. Classify each finding with severity, location, evidence and an actionable remedy.
7. Return a decision conforming to `schemas/review-decision.schema.json`.

Do not push fixes to the author branch, approve your own work, merge, deploy or waive required checks. Use `BLOCKED` when the specification, commit, evidence or independence requirement is missing.
