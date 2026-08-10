---
name: specify-change
description: Turn an accepted software work item into an implementable, testable, and reviewable change specification. Use when product or architecture work must define scope, non-scope, acceptance criteria, interfaces, risks, documentation impact, migration, rollout, rollback, and required owner decisions before coding begins.
---

# Specify Change

1. Read the accepted work item, product principles, current architecture, relevant ADRs and project commands at pinned commits.
2. Describe the user-visible problem and desired outcome without prescribing unnecessary implementation detail.
3. State in-scope and out-of-scope behavior, assumptions, dependencies and compatibility requirements.
4. Write objective acceptance criteria, including negative cases and observability.
5. Identify architecture, security, privacy, data, deployment and documentation impact.
6. Define test strategy, rollout, rollback and any database expand-contract sequence.
7. Mark unresolved product or architecture decisions; request the correct owner rather than inventing approval.
8. Produce a scope hash so approval binds to the exact specification.

Do not start implementation until the state machine records a valid plan approval. Stop if rollback is impossible, destructive data behavior is unclear or required external facts are unavailable.
