---
name: implement-change
description: Implement an approved software specification in an isolated workspace and proposal branch, add proportionate tests and documentation, and produce a draft pull request with evidence. Use for frontend, backend, API, database-compatible, documentation, or test changes after plan approval; never use for direct main pushes, self-review, or production deployment.
---

# Implement Change

1. Verify the approved specification hash, expected work-item revision, project commit and allowed paths.
2. Create a dedicated ephemeral worktree or container and a branch tied to the work item. Never share a writable checkout with another task.
3. Inspect existing architecture, conventions and tests before editing.
4. Make the smallest change satisfying the acceptance criteria; update tests and durable documentation together.
5. Run project-prescribed formatting, lint, unit and relevant integration tests in the isolated environment.
6. Scan the diff for secrets, generated files, migrations, unsafe dependencies and scope drift.
7. Commit intentionally and open a draft PR referencing the work item, specification, evidence, risk and rollback.
8. Return commit and PR references plus test evidence; do not claim checks that were not run.

Never push the protected branch, approve or merge your own PR, read production secrets, access production data, or deploy. Stop on a stale revision, failing required check, unapproved scope expansion or missing migration/rollback decision.
