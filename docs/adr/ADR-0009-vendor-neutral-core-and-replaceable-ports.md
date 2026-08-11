# ADR-0009: Vendor-neutral core and replaceable ports

- Status: Accepted and implemented in v0.8.0
- Date: 2026-08-11
- Release impact: introduced by `v0.8.0`; the historical `v0.7.0` tag remains immutable

## Context

The Factory needs durable workflow, approval, recovery, and evidence semantics while still allowing OpenClaw, OpenHands, Paperclip, model CLIs, SCMs, and sandbox systems to be replaced. Forking a large upstream as the product core would bind those semantics to its internal schema and release lifecycle. Reimplementing every database, SCM, identity, and isolation primitive would create a different and larger maintenance risk.

## Decision

1. Agent Team owns versioned `TeamSpec`, `RoleContract`, `WorkflowSpec`, `WorkItem`, `PlanRevision`, `ApprovalGrant`, `Run`, `EvidenceBundle`, and `AdapterDescriptor` contracts.
2. Context files and Git own durable team meaning; the deterministic controller owns live revisions, events, leases, retries and idempotency; SCM/CI own code evidence; secret values remain external.
3. Ingress, Identity, SCM, AgentExecutor, Sandbox, CI, StateStore, Evidence, Notification, and Secret capabilities use replaceable ports.
4. The Native reference path must pass without an external agent-control platform. Optional platforms may enhance a surface but cannot become the only authority.
5. Upstream work is referenced by default. Copying files, adding runtime dependencies, or forking requires explicit provenance, license, maintenance, upgrade, and exit review.
6. v0.8 stops at an independently reviewed Draft PR. A real runner, external write identity, merge, deployment, and release remain separate gates.

## Consequences

The project must maintain its own narrow contract, validation, conformance, migration, and Native recovery layer. In return, a team package and its authority remain readable and recoverable if an optional UI, agent server, message gateway, SCM, or runner is removed.

This ADR does not select a default external platform and does not authorize installation or production execution.
