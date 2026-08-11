# Native controller, recovery, and conformance

Status: unreleased v0.8 W3 reference. It proves deterministic core behavior with local SQLite and test doubles. It is not a production service, hostile-code sandbox, real SCM integration, or authorization to install an upstream platform.

## What the Native path proves

The Native path is the minimum product core that remains available if Paperclip, OpenHands, OpenClaw, a model provider, SCM provider, or runner implementation is removed. It combines:

- `contracts/native-reference-workflow.json`: portable state and transition authority;
- `core/native_controller.py`: SQLite transactions, optimistic revisions, exact approvals, single-use nonces, leases, effect claims, idempotency, budgets/time limits, content-addressed evidence and hash-chained events;
- `core/native_scenario.py`: a deterministic no-network feedback-to-Draft-PR scenario;
- `acceptance/v08-native-conformance.json`: machine-readable claims and explicit Gate B/C/D exclusions.

The controller is code because documents alone cannot atomically compare revisions, consume a nonce, commit an event, recover a lease, reconcile an uncertain external effect, or stop a budget. Team meaning, roles, workflow, schemas, migration and authority remain portable documents; Python executes only the deterministic invariants.

## Persisted authority

| SQLite record | Purpose | Not stored |
|---|---|---|
| `native_work_items` | Current validated WorkItem plus immutable current plan, approval and run snapshot | Provider SDK objects, prompts, secret values |
| `native_commands` | Idempotency key → exact command digest and stable result | A second workflow truth |
| `native_events` | Immutable event envelope, content digest and predecessor hash | Unbounded logs or provider raw responses |
| `native_approval_nonces` | Globally single-use nonce/approval ID within the authoritative database | Signature or credential value |
| `native_leases` | Worker, role, work revision and bounded expiry | Long-lived Agent ownership |
| `native_effects` | Outbox request binding, claim, attempts, classified result and provider/evidence refs | Direct external credentials |
| `native_evidence_bundles` | Validated content-addressed index | Secret or unredacted arbitrary transcript |

The database pins its schema version, workflow digest, Draft-PR stop and disabled merge/deploy flags. Opening it with a different workflow fails closed.

## Exact plan approval

Approval is a transaction, not a Boolean. Before `APPROVED`, the controller verifies:

1. `ApprovalGrant` structure and canonical scope digest;
2. exact WorkItem, plan revision/digest, repository, base commit, paths, actions, runner profile, Agent capabilities, budget and time;
3. active issuance/expiry, `merge_allowed=false`, `deploy_allowed=false`;
4. an IdentityPort result bound to the same approval ID, actor, provider, signature reference and scope;
5. a nonce and approval ID that have never been consumed in this authoritative database.

The nonce is consumed in the same transaction as state, Run and event. A crash before commit consumes nothing; a crash after commit replays the saved command result. A plan, base, path, action, runner, capability, budget or time change requires a new grant.

## Leases, limits, and effects

- Worker transitions require a lease bound to worker ID, role, WorkItem and exact revision. Each transition consumes its lease. Expired leases are cleared and audited before reassignment.
- Every transition compares `expected_revision`. Conflicts and undeclared state/event combinations fail closed.
- Run cost and elapsed time are checked before each run transition. Exceeding the grant moves the item to `BLOCKED`; an Agent cannot extend its own budget or expiry.
- Effects are queued transactionally and invoked outside the state transaction through an explicitly bound port.
- A retryable, not-attempted failure may retry within policy. A permanent/cancelled result dies. `UNKNOWN` never retries blindly.
- If the controller crashes after a provider applies an effect but before local confirmation, the claim expires and the same idempotency key is replayed. The fake provider proves only one execution; a real adapter must provide provider idempotency or reconcile-before-retry.

## Fault and replay evidence

The automated suite covers:

- every reference workflow transition interrupted before commit and after commit, with the controller closed, reopened, retried and invariant-checked;
- effect interruption after claim, before invocation, after invocation and before finalization;
- expired worker leases and effect claims;
- ten duplicate deliveries, changed payload under the same idempotency key, stale revision and workflow-digest drift;
- exact approval mismatch matrix, expiry, identity mismatch, nonce uniqueness, budget and time stops;
- audit/evidence tamper detection, backup/reopen, complete scenario replay, and unknown side-effect stop.

No test relaxes the Draft-PR ceiling. There is no merge or deploy transition or port operation.

## Native CLI

Validate any core document:

```bash
./agent-team native contract-validate \
  --contract team_spec \
  --file examples/v08-contracts/valid/team-spec.json
```

Run the no-network reference scenario into a new local database:

```bash
./agent-team native demo --database /tmp/agent-team-native.sqlite3
./agent-team native status --database /tmp/agent-team-native.sqlite3
./agent-team native verify --database /tmp/agent-team-native.sqlite3
./agent-team native recover --database /tmp/agent-team-native.sqlite3
./agent-team native backup \
  --database /tmp/agent-team-native.sqlite3 \
  --output /tmp/agent-team-native.backup.sqlite3
```

`demo` performs no network request, model invocation, process execution, untrusted code execution, or real SCM write. Its Draft PR and identity are deterministic fakes. Do not point this reference database at production data or treat it as Gate B/C evidence.

Run focused acceptance:

```bash
python3 -m unittest \
  tests.test_v08_contracts \
  tests.test_v08_adapter_ports \
  tests.test_native_controller \
  tests.test_native_scenario -v
```

Gate B is still required for a disposable isolated Worker; Gate C for a dedicated Private test repository and minimum external write identity; Gate D for merge, version bump, tag, Release, or public capability claims.
