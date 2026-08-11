# v0.8 replaceable adapter port SDK

Status: unreleased W2 reference implementation. It uses deterministic fakes only and does not install an external platform, connect an account, run generated code, or write to a real repository.

## Contract surface

`core/adapter_ports.py` exposes ten narrow Python `Protocol` interfaces backed by portable `AdapterDescriptor` data:

| Port | Method | Owns one bounded interaction; it never owns |
|---|---|---|
| Ingress | `receive` | External event intake; never approval or workflow state |
| Identity | `verify` | Identity proof; never business approval decisions |
| SCM | `apply` | Repository/branch/commit/Draft PR operations; never internal WorkItem truth |
| AgentExecutor | `execute` | One bounded role session; never long-term state or self-approval |
| Sandbox | `run` | Isolated workspace execution/collection; never plan meaning |
| CI | `check` | Check trigger/read and evidence; never merge/deploy permission |
| StateStore | `transact` | Events, revisions, idempotency and leases; never context or secrets |
| Evidence | `record` | Sanitized content-addressed evidence; never plaintext secrets |
| Notification | `notify` | Status projection; never a state transition |
| Secret | `lease` | Short-lived reference/lease metadata; never a value in logs or evidence |

Every implementation supplies `health()` and `cancel(request_id)`. Composition code explicitly calls `PortRegistry.register()` with trusted implementation objects, then explicitly binds an adapter ID to each required port. Descriptor strings never become imports or executable entrypoints.

## Capability negotiation

Binding checks three layers before a call is possible:

1. The descriptor is valid and the requested core version is inside its `[minimum, maximum_exclusive)` range.
2. The descriptor declares the requested port and every required capability.
3. The live health report is not `UNAVAILABLE` and still advertises those required capabilities.

Failure returns/raises a `CapabilityReport` with required, provided, missing, limitations and stable errors. Its schema is [`capability-report.schema.json`](../../schemas/capability-report.schema.json). Selection is not automatic: a richer or newer adapter cannot silently replace an owner-approved binding.

The descriptor’s `core_contract_versions` is the SDK/core protocol range, not a claim that every entity schema shares one major number. Individual documents continue to carry their own `$schema` and `schema_version`.

## Call and result invariants

`PortCall` binds a stable idempotency key to operation and sanitized strict-JSON payload. It also carries request/correlation IDs and a hard deadline. Inline credential-like values, secret-named keys, duplicate/non-JSON values and payloads over 1 MiB are rejected before the adapter.

`PortResult` distinguishes:

| Outcome | Retry meaning | Side-effect rule |
|---|---|---|
| `SUCCEEDED` | Do not repeat; replay the stable result | `NONE`, `NOT_ATTEMPTED`, or explicitly `APPLIED` |
| `RETRYABLE_FAILURE` | Controller policy may retry after the declared delay | Must not claim applied; fake failures are not cached |
| `PERMANENT_FAILURE` | Human/plan/configuration change required | Must not claim applied |
| `UNKNOWN` | Do not blindly retry; reconcile or require human action | Must be `UNKNOWN` and is stable for the idempotency key |
| `CANCELLED` | A new command is required to resume | Side effect was not attempted |

Reusing an idempotency key with a changed operation or payload raises `ADAPTER_IDEMPOTENCY_CONFLICT`. Adapter exceptions and provider payloads must be converted into stable error codes and sanitized evidence outside the core event log.

## Reference fakes and conformance

`DeterministicFakePort` performs no network, filesystem, process, model, SCM, secret, or database operation. It supports scripted failures, health changes, deadlines, cancellation, stable replay and unknown-side-effect simulation. The same port tests are the minimum contract an external adapter must pass.

```bash
python3 -m unittest tests.test_v08_adapter_ports -v
```

Passing these tests proves interface behavior only. It does not prove a real provider, identity, SCM write, or sandbox is safe; those remain behind Gate B/C and platform-specific threat/exit tests.
