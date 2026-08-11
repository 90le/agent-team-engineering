# v0.8 core contracts and v0.7 import

Status: unreleased v0.8 candidate on `proposal/upstream-independent-v0.8`. This document does not change the current `v0.7.0` release or authorize a real runner, external write identity, merge, deployment, or release.

## Why this layer exists

Markdown, JSON, Skills, and Git remain the durable team-context authority. The v0.8 contract layer handles the smaller set of facts that must be deterministic: versions, state transitions, revisions, exact approvals, adapter capabilities, evidence integrity, idempotency, and recovery. It does not replace context engineering with Python and it does not make an external agent platform the team authority.

The machine registry is [`contracts/core-contracts.json`](../../contracts/core-contracts.json). `core/contracts.py` is a dependency-free validator and digest implementation for that registry; the JSON documents remain portable authority.

## Entity authority

| Contract | Owns | Must not contain as a required core field |
|---|---|---|
| `TeamSpec` | Team identity, mission, autonomy ceiling, stop point, role/workflow references, context digest | External company, chat, model, or platform identity |
| `RoleContract` | Responsibilities, non-responsibilities, minimum context, inputs/outputs, actions, limits, handoff, evidence, stop conditions | Session memory or a provider prompt format |
| `WorkflowSpec` | States, legal events, transition roles, approval/evidence gates, retries, timeouts | External UI or database states |
| `WorkItem` | Normalized untrusted intake and deduplication facts | An Issue number as internal identity |
| `PlanRevision` | Immutable repository baseline, task DAG, paths, actions, tests, risk, rollback, budget and time | A mutable “latest plan” |
| `ApprovalGrant` | A time-bound human grant over the exact plan and execution scope | Natural-language “approved” without verified identity |
| `Run` | One bounded attempt, revision, lease, sessions, cost, artifacts and evidence references | A long-lived agent persona |
| `EvidenceBundle` | Content-addressed evidence index, producer, time, classification, redaction and retention | Secrets or an unbounded raw model transcript |
| `AdapterDescriptor` | Ports, supported core range, capabilities, permissions, limits, timeouts, idempotency and health | External SDK types inside core contracts |
| Command/event envelopes | Optimistic revision, idempotency, causation, actor, time and evidence links | Permission inferred from a prompt |

## Validation and version rules

- Contract files use strict JSON: duplicate keys, non-finite numbers, unknown fields, unknown schema versions, states, permissions, and side-effect types fail closed.
- The portable validator intentionally implements a small, declared JSON Schema subset. A keyword it does not implement is an error, not silently ignored documentation.
- `PlanRevision.plan_digest` binds every other plan field. Any plan edit creates a new revision and digest.
- `ApprovalGrant.scope_digest` binds actor/provider, work item, plan revision/digest, repository/base commit, paths/actions, runner/capabilities, budget/time, merge/deploy booleans, issuance/expiry, and nonce.
- v0.8 approval always has `merge_allowed=false` and `deploy_allowed=false`; the default autonomy stop is `DRAFT_PR_READY`.
- `EvidenceBundle.bundle_digest` binds its complete index. Original evidence may live outside Git, but its content reference and digest remain verifiable.
- Adapters negotiate a common core version and required capabilities before use. No adapter or core package downloads another implementation at runtime.

## v0.7 import and rollback

The migration authority is [`contracts/v07-to-v08-migration.json`](../../contracts/v07-to-v08-migration.json). Import is one-way and never edits the v0.7 source:

1. Keep annotated `v0.7.0`, source documents, database export, and evidence as the recovery baseline.
2. `core.contract_migration:migrate_work_item_v1` can convert the reviewed pre-Draft-PR subset of a v0.7 WorkItem into a new v0.8 WorkItem.
3. Team blueprints and adapter manifests require a reviewed recompile because v0.7 did not express every v0.8 authority, evidence, capability, retry, health, and stop rule.
4. A v0.7 approval is never migrated. A human must issue a new v0.8 `ApprovalGrant` over the complete exact scope.
5. Any legacy state after `DRAFT_PR_READY`, unknown state, or ambiguous external side effect is rejected.
6. Rollback discards/reverts only newly imported v0.8 records and returns to the retained v0.7 baseline; it never rewrites history.

## Try the contracts locally

No external service or SDK is required:

```bash
python3 -m unittest tests.test_v08_contracts -v
```

Valid examples are under [`examples/v08-contracts/valid`](../../examples/v08-contracts/valid/). The negative mutation suite proves unknown fields, version mismatch, authority conflict, approval bypass, digest tampering, unsafe grants, invalid leases, evidence tampering, undeclared adapter ports, and revision errors are rejected.
