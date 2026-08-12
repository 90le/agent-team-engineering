# ADR-0013: Portable independent-writer topology

- Status: Accepted for v1.0 contract design
- Date: 2026-08-12
- Decision owners: Agent Team Engineering maintainers
- Extends: ADR-0007, ADR-0009, ADR-0011

## Context

The existing Managed reference controller intentionally has one source-writing `builder`. A native host projection can create several named roles, Skills, and context files, but names do not prove that two agents have separate write authority, isolated Git state, independent review identities, or a durable scheduler. Mapping frontend and backend to one writer is safe but does not satisfy a genuine independent multi-writer team. Mapping several display roles and calling that a multi-writer runtime would overstate the evidence.

The desired topology must remain portable across AI products while preserving exact human approval and a reviewed Draft PR stop. A standalone topology digest is not enough: the immutable plan must select that exact topology, and the human approval must bind both the exact plan and topology. The design also needs an honest degradation record for hosts that can import role files but cannot enforce repository ownership, orchestration, or identity separation.

## Decision

Add `WriterTopology` as a strict portable core contract with schema `urn:agent-team:schema:writer-topology:1.0.0`. Its complete content is bound by `topology_digest`.

For the v1.0 product release, extend the existing PlanRevision and ApprovalGrant schema files to `$id` `1.1.0`. Each unified schema file remains compatible with `1.0.0` documents while accepting `1.1.0` documents. Semantic validation enforces the version boundary:

- `1.1.0` PlanRevision and ApprovalGrant documents must explicitly include `writer_topology` as either the exact identity/digest object or `null`;
- `null` means no WriterTopology authority is claimed and must not be inferred from role names;
- compatible `1.0.0` documents must omit `writer_topology` and cannot claim the `1.1.0` binding;
- upgrading a legacy document requires a new plan digest and a new human approval.

When independent-writer authority is selected, validate the complete chain:

```text
WriterTopology topology_digest
        → PlanRevision writer_topology + plan_digest
        → ApprovalGrant writer_topology + plan_digest + scope_digest
```

The canonical trio binds:

- topology: `sha256:b4b3e8ad868889082a871e3ecc7588b00ced58a0555da299061c0aae758de0dd`;
- plan: `sha256:e8b43d51e503d3cd453627aa0249775a301e1ae14336ef866eb1cfd6980ede7a`;
- approval scope: `sha256:57137766d7f2c13c1b5eaecba648a67deab6d888400b609cfb1b210dc90c3b00`.

The topology contract requires:

- at least two distinct source-writing identities;
- normalized, non-overlapping repository subtrees for each writer;
- worktree and branch templates containing both work-item and writer identities;
- an integrator identity distinct from every writer;
- exactly one read-only tester and one read-only reviewer, both distinct from writers and integrator and unable to review their own work;
- human approval binding `exact-plan-and-topology-digests` before any writer phase;
- a deterministic phase sequence from approval through isolated implementation, integration, independent testing, independent review, and Draft PR handoff;
- idempotency identity containing `topology_digest`, same-revision-and-approval retry, cancellation, partial-result retention, and resume rules;
- default `automatic_merge=false`, `automatic_release=false`, and `automatic_deploy=false`;
- explicit per-host projection and degradation records with `topology_enforced=false` and `automatic_execution=false` until live conformance proves otherwise.

The schema supplies structural validation. `core/contracts.py` adds semantic validation for digest integrity, identity separation, path ownership overlap, template isolation, dangerous-action denials, phase ordering, producer independence, retry identity, unique host records, and evidence-tier/projection consistency. The cross-document validator additionally checks the exact topology binding, repository/base commit, writer task coverage, allowed-path ownership, and approval equality. Unknown fields and versions fail closed.

The public validation command is:

```bash
./agent-team native writer-authority-validate \
  --topology examples/v08-contracts/valid/writer-topology.json \
  --plan examples/v08-contracts/valid/plan-revision.json \
  --approval examples/v08-contracts/valid/approval-grant.json
```

## Authority and execution boundary

`WriterTopology` is portable design authority, not an execution grant or scheduler. Its status is deliberately `DESIGN_ONLY`. Passing the three-document validator proves digest-bound document coherence; its report explicitly returns `automatic_execution: false` and `identity_or_signature_verified: false`. Offline validation does not authenticate the approval actor or verify a digital signature, so `VALID` is not production identity authority.

A host projection may carry roles, Skills, ownership rules, and workflow into OpenClaw, Hermes Agent, Codex, Claude, Multica, or another AI product, but the projection must not claim runtime enforcement unless a separately versioned adapter and live conformance report prove it. Validation does not create identities, worktrees, branches, repository writes, PRs, merges, releases, or deployments.

The current Managed reference runtime remains single-writer. It may enforce this topology in a future version only after persistent writer leases, worktree/branch ownership, identity-bound evidence, deterministic integration, cancellation, replay, and crash recovery are implemented and tested. v1.0 does not silently widen that runtime.

The canonical degradation matrix therefore says:

- Codex and Claude: verified role/context export only;
- OpenClaw and Hermes Agent: verified native team-file installation, without a verified durable multi-writer scheduler;
- Multica: experimental leader/Squad overlay; Squad role labels do not enforce writer ownership or independent approval;
- Generic AI: portable documents that the receiving AI must map without weakening the contract.

## Compatibility and history

The v1.0 product change must not rewrite v0.9 history. The `v0.9.0` tag did not contain the WriterTopology → PlanRevision → ApprovalGrant authority chain. Existing `1.0.0` PlanRevision and ApprovalGrant documents remain valid legacy inputs under the unified `1.1.0` schema files, but they have no topology field and no implicit topology authority.

PlanRevision `1.1.0` is also unrelated to host installation plan schema `1.1.0`; they are separate contracts with separate confirmation and lifecycle boundaries.

## Consequences

### Positive

- A human or AI can distinguish a real independent-writer design from several role names sharing one writer.
- A plan and human approval cannot silently drift from the topology they claim to authorize.
- A topology change creates a new plan, approval, and retry identity instead of reusing stale authority.
- Ownership conflicts and self-review identities are rejected before any runtime mapping.
- Host-specific limitations travel with the portable design instead of being hidden in prose.
- The complete authority chain can be validated without a network, model account, host process, or external SDK.
- A future runtime has a precise conformance target rather than an informal feature request.

### Costs

- v1.0 does not execute this topology automatically; it defines and validates it.
- A `1.1.0` PlanRevision or ApprovalGrant must choose an explicit topology object or `null`.
- Repository ownership must be expressed as disjoint subtrees. Cross-cutting files require an explicit replan or integrator-owned policy in a later contract revision.
- A native host that lacks durable identity and Git isolation degrades to role/context projection and must say so.

## Rejected alternatives

### Validate only WriterTopology

Rejected because a valid topology does not prove that a plan selected it or that a human approved the exact topology-plan pair.

### Infer topology from roles or omit it in document 1.1.0

Rejected because role names are not authority. `null` is the only explicit `1.1.0` declaration that no topology is bound.

### Treat several prompts as independent writers

Rejected because prompt names do not create filesystem, Git, identity, approval, or recovery isolation.

### Map all writers to the existing Managed builder

Rejected as a false capability claim. The safe v1.0 behavior is to retain the single-writer boundary and expose the chain as design authority.

### Make a specific agent platform the core authority

Rejected because it would make the team non-portable and place host-specific identifiers and failure semantics in the vendor-neutral contract.

### Allow automatic merge, release, or deployment by default

Rejected because those effects exceed the approved feedback-to-reviewed-Draft-PR objective and require separate human authorization and conformance evidence.

## Acceptance

- the canonical topology, plan, and approval pass strict schema, semantic, digest, and cross-document authority validation;
- the CLI returns the exact canonical topology digest, plan digest, and approval scope digest plus `automatic_execution: false` and `identity_or_signature_verified: false`;
- `1.1.0` plan/approval documents fail without explicit `writer_topology`, while compatible `1.0.0` documents remain valid only without it;
- topology drift invalidates the bound plan/approval and changes retry identity;
- overlapping writer subtrees, duplicate identities, self-review, missing isolation tokens, unsafe action grants, phase drift, digest drift, and overstated host enforcement fail closed;
- every supported host in the canonical example has an explicit degradation record;
- public documentation calls the artifact design-only, preserves v0.9 as history, and continues to describe Managed as single-writer;
- no model, host, repository writer, merge, release, or deployment is started while validating the chain.

## References

- [Portable core contracts](../15-upstream-independent/core-contracts-and-migration.md)
- [Independent-writer topology guide](../15-upstream-independent/independent-writer-topology.md)
- [v1.0 release acceptance contract](../16-release/v1.0-acceptance.md)
- [Native-host conversation workflow](../18-native-hosts/conversation-workflow.md)
- [GitHub issue #13](https://github.com/90le/agent-team-engineering/issues/13)
