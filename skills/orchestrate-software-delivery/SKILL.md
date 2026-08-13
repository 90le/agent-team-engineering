---
name: orchestrate-software-delivery
description: Coordinate a governed software work item across intake, triage, specification, implementation, independent review, verification, staging, approval, deployment, and rollback. Use when an AI or controller must route a work item through the software-delivery team pack while enforcing revisions, evidence, budgets, role separation, stop conditions, and human gates.
---

# Orchestrate Software Delivery

Read `AI-BOOTSTRAP.md` and all policy JSON files in `team-packs/software-delivery/` before routing work.

## Run the workflow

1. Require a task envelope containing the work item ID, expected revision, role, context commits, allowed capabilities, budget and idempotency key.
2. Re-read the current work item. Reject stale revisions, expired leases, missing authority or a context commit mismatch.
3. Select exactly one next transition from `workflow.json`; do not ask a model to invent workflow state.
4. Invoke only the role Skill assigned to that transition and expose only its allowlisted tools.
5. Validate the result against its output Schema and required quality evidence.
6. Persist actor, transition, revision, evidence references, skill version and outcome before dispatching another step.
7. Pause at every human or risk-policy gate. Resume only with approval bound to the exact work item revision and artifact digest.

## Refuse unsupported independent-writer dispatch

If a PlanRevision `1.1.0` carries a non-null `writer_topology`, require the exact WriterTopology, PlanRevision, and ApprovalGrant files and run:

```bash
./agent-team native writer-authority-validate \
  --topology <writer-topology.json> \
  --plan <plan-revision.json> \
  --approval <approval-grant.json>
```

Treat success as `DESIGN_ONLY` document validation with `automatic_execution: false` and `identity_or_signature_verified: false`. The offline command does not authenticate an approver or verify a digital signature. The current Managed controller and host mappings do not enforce independent writer identities, ownership roots, worktrees, or scheduling. Stop before dispatch rather than map multiple writers to one `builder` or writable workspace. A future runtime may proceed only after separate authenticated authority and live conformance are available.

For PlanRevision/ApprovalGrant `1.1.0`, require `writer_topology` to be explicit in both documents, as the same exact object or `null`. Compatible `1.0.0` documents omit it. Reject stale approval or retry identity after any topology digest change; `topology_digest` is part of the complete retry identity.

## Enforce ownership

- Keep one active lease per work item and one writable workspace per implementation task.
- Keep author, reviewer and releaser identities distinct.
- Treat GitHub labels, chat messages and Agent prose as projections, not authoritative workflow state.
- Use event-driven wakeups plus a scheduled reconciliation sweep; never run an unbounded autonomous loop.

## Stop safely

Stop and record `BLOCKED` when permissions, evidence, rollback, budget, current state or required owner decisions are missing. Never convert a failed or timed-out step into success.

Verify changes with `python3 tools/agent_team.py validate`, the unit tests and the side-effect-free simulator.
