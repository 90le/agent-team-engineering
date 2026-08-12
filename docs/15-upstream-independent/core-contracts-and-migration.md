# Portable core contracts, v0.7 import, and the v1 writer authority chain

Status: the v0.8 L1 authority model, `1.0.0` PlanRevision/ApprovalGrant compatibility, and v0.9 history remain preserved; the v1.0 release adds a design-only WriterTopology → PlanRevision → ApprovalGrant authority chain. This document does not authorize a production Runner, multi-writer scheduler, merge, release, or deployment.

## Why this layer exists

Markdown, JSON, Skills, and Git remain the durable team-context authority. The v0.8 contract layer handles the smaller set of facts that must be deterministic: versions, state transitions, revisions, exact approvals, adapter capabilities, evidence integrity, idempotency, and recovery. It does not replace context engineering with Python and it does not make an external agent platform the team authority.

The machine registry is [`contracts/core-contracts.json`](../../contracts/core-contracts.json). `core/contracts.py` is a dependency-free validator and digest implementation for that registry; the JSON documents remain portable authority.

The replaceable implementation boundary is specified separately in [the v0.8 adapter port SDK](adapter-port-sdk.md).

## Entity authority

| Contract | Owns | Must not contain as a required core field |
|---|---|---|
| `TeamSpec` | Team identity, mission, autonomy ceiling, stop point, role/workflow references, context digest | External company, chat, model, or platform identity |
| `RoleContract` | Responsibilities, non-responsibilities, minimum context, inputs/outputs, actions, limits, handoff, evidence, stop conditions | Session memory or a provider prompt format |
| `WorkflowSpec` | States, legal events, transition roles, approval/evidence gates, retries, timeouts | External UI or database states |
| `WorkItem` | Normalized untrusted intake and deduplication facts | An Issue number as internal identity |
| `PlanRevision` | Immutable repository baseline, task DAG, paths, actions, tests, risk, rollback, budget and time; document `1.1.0` explicitly binds a WriterTopology identity/digest or `null` | A mutable “latest plan” or topology inferred from role names |
| `ApprovalGrant` | A time-bound human grant over the exact plan, execution scope, and document `1.1.0` topology binding | Natural-language “approved” without verified identity or a topology not bound by the plan |
| `Run` | One bounded attempt, revision, lease, sessions, cost, artifacts and evidence references | A long-lived agent persona |
| `EvidenceBundle` | Content-addressed evidence index, producer, time, classification, redaction and retention | Secrets or an unbounded raw model transcript |
| `AdapterDescriptor` | Ports, supported core range, capabilities, permissions, limits, timeouts, idempotency and health | External SDK types inside core contracts |
| Command/event envelopes | Optimistic revision, idempotency, causation, actor, time and evidence links | Permission inferred from a prompt |
| `WriterTopology` | Independent writer identities, disjoint ownership, Git isolation templates, approval-first phases, assurance identities, recovery, safe stop and host degradation | A claim that the current host or Managed runtime enforces the topology |

## Validation and version rules

- Contract files use strict JSON: duplicate keys, non-finite numbers, unknown fields, unknown schema versions, states, permissions, and side-effect types fail closed.
- The portable validator intentionally implements a small, declared JSON Schema subset. A keyword it does not implement is an error, not silently ignored documentation.
- `PlanRevision.plan_digest` binds every other plan field, including `writer_topology` when present. Any plan edit creates a new revision and digest.
- `ApprovalGrant.scope_digest` binds actor/provider, work item, plan revision/digest, repository/base commit, paths/actions, runner/capabilities, budget/time, merge/deploy booleans, issuance/expiry, nonce, and `writer_topology` when present.
- v0.8 approval always has `merge_allowed=false` and `deploy_allowed=false`; the default autonomy stop is `DRAFT_PR_READY`.
- `EvidenceBundle.bundle_digest` binds its complete index. Original evidence may live outside Git, but its content reference and digest remain verifiable.
- `WriterTopology.topology_digest` binds the complete design. Semantic validation rejects overlapping writer roots, shared identities, missing worktree/branch isolation, self-review, unsafe default effects, phase drift, an idempotency identity without `topology_digest`, and overstated host projection.
- The current PlanRevision and ApprovalGrant schema files have `$id` `1.1.0` and remain compatible with `1.0.0` documents. A `1.1.0` document must explicitly set `writer_topology` to the exact identity/digest object or `null`; a `1.0.0` document must omit it. `null` never implies independent-writer authority.
- `validate_writer_authority` binds the exact topology into both plan and approval, matches repository/base commit, requires a task for every writer, keeps every allowed path inside one writer root, and checks the approval against the exact plan. The topology declares approval binding `exact-plan-and-topology-digests`, and retry identity includes `topology_digest`.
- Adapters negotiate a common core version and required capabilities before use. No adapter or core package downloads another implementation at runtime.

The v1.0 product version, WriterTopology schema `1.0.0`, and PlanRevision/ApprovalGrant schema-file `$id` `1.1.0` are distinct version domains. PlanRevision is also unrelated to host installation plan `1.1.0`. The `v0.9.0` tag predates this authority chain; its historical claims and artifacts must not be rewritten as if they already provided it.

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

./agent-team native contract-validate \
  --contract writer_topology \
  --file examples/v08-contracts/valid/writer-topology.json

./agent-team native writer-authority-validate \
  --topology examples/v08-contracts/valid/writer-topology.json \
  --plan examples/v08-contracts/valid/plan-revision.json \
  --approval examples/v08-contracts/valid/approval-grant.json
```

The single-contract command validates only the topology document. The three-file command validates the canonical digest chain `b4b3e8… → 573616… → 2457ab…` and returns `automatic_execution: false`.

Valid examples are under [`examples/v08-contracts/valid`](../../examples/v08-contracts/valid/). The negative mutation suite proves unknown fields, version mismatch, authority conflict, approval bypass, topology/plan/approval digest tampering, unsafe grants, invalid leases, evidence tampering, undeclared adapter ports, revision errors, and writer-ownership overlap are rejected. See the [independent-writer guide](independent-writer-topology.md) for the exact compatibility and design/runtime boundaries.
