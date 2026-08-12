# ADR-0011: Host capability contracts and native team projection

- Status: Accepted
- Date: 2026-08-12
- Decision owners: Agent Team Engineering maintainers
- Supersedes: none
- Extends: ADR-0008, ADR-0009, ADR-0010

## Context

The project already compiles portable roles, context, Skills, workflows, locks, and static platform overlays. Its optional vendor-neutral controller can govern a feedback-to-reviewed-Draft-PR workflow. Those are valuable but answer two different questions:

1. What is the durable, portable team authority?
2. How can work progress through an optional governed controller?

Adopters ask a third question: **How do I create this team inside the AI host I already use?**

A static folder named after a platform is insufficient evidence. OpenClaw, Hermes Agent, Codex, Claude Code, Multica, and future hosts expose different discovery, role, Skill, workspace, profile, scheduling, and lifecycle concepts. Presenting them as interchangeable causes users and AI guides to overstate support. Building the Factory itself into another runtime would duplicate host responsibilities and weaken portability.

The same term “adapter” was also overloaded: existing adapters connect workflow ingress, execution, SCM, and notification ports, whereas a host-native projection packages team authority for an AI runtime. These need separate contracts and lifecycle boundaries.

## Decision

Position Agent Team Engineering as a **host-native Agent Team Factory**.

Maintain one host-neutral Team Intent and portable authority source. Introduce versioned Host Capability Contracts that describe safe detection, native extension surfaces, generated artifacts, lifecycle operations, evidence tier, limitations, and official upstream anchors. Compile the authority into a separate host-native projection without allowing the projection to modify the source of truth.

Use a digest-bound lifecycle:

```text
list/probe → plan → preview → confirm → apply → verify → uninstall
```

Apply may use a new destination or preserve unrelated content in an existing directory, but first apply creates only absent declared files. Only the exact same proposal-bound `APPLYING` record may resume deterministic recovery after interruption. It must not silently merge existing user configuration or infer permission for accounts, credentials, bindings, external writes, merge, release, or deployment.

Keep host projectors separate from the existing runtime `adapters/` ports. Preserve the existing Managed controller as an optional automation layer for adopters who explicitly need durable progression. It is not the primary product identity and does not replace the target host.

Report support using evidence tiers: `native-verified`, `native-install-verified`, `verified-export`, `experimental-plan`, `portable`, and `research-unknown`. A generated artifact does not imply host load; isolated host validation does not imply a live authenticated or production workflow.

Treat OpenClaw and Hermes Agent as first-class native targets, Codex and Claude Code as native export targets, Multica `v0.4.23` as `experimental-plan` until disposable authenticated acceptance exists, Generic AI as `portable`, and “Leda” as `research-unknown` until an exact upstream identity and contract are supplied.

## Consequences

### Positive

- Users begin with their desired outcome and existing host instead of internal modes.
- Markdown/JSON/Git authority remains portable across models, devices, and runtimes.
- Each host can use its real concepts rather than a lowest-common-denominator fiction.
- Detection, generation, installation, and live operation become separately auditable claims.
- New hosts can be added through data/contract-driven projection without coupling the vendor-neutral controller to a vendor SDK.
- Optional Managed automation remains available without dominating ordinary adoption.

### Costs

- Each native host needs version anchors, negative tests, lifecycle ownership, and maintenance.
- Support language is more conservative and may be downgraded when an upstream contract changes.
- Real authenticated services require disposable acceptance environments and cannot be proven by offline tests alone.
- Some team concepts do not map one-to-one across hosts and must remain explicit limitations.

## Rejected alternatives

### Make the Factory a universal runtime

Rejected because it would duplicate mature host schedulers, profiles, workspaces, channels, and model integrations; require credentials and long-running state; and turn portability into a migration between runtimes.

### Keep only Markdown and let every AI improvise installation

Rejected because prose alone cannot enforce exact paths, non-overwrite behavior, digest binding, ownership, drift detection, verification, deterministic crash recovery, or replay-safe uninstall.

### Treat every platform folder as “supported”

Rejected because generation, structural validation, host loading, authenticated execution, and production use are different evidence levels.

### Bind directly to vendor SDKs in the core

Rejected because SDK churn and vendor identities would contaminate the portable authority and vendor-neutral controller. Version-pinned projectors and external operators keep those dependencies replaceable.

## Acceptance

- Public positioning describes a host-native team factory, not an autonomous replacement runtime.
- Human and AI onboarding starts with outcome, project, existing host, and authority.
- Host claims use the documented evidence tiers and identify limitations.
- Host plans are separately previewed and digest-confirmed after portable team creation.
- OpenClaw and Hermes packages are tested only in isolated homes unless a separate live plan is approved.
- Multica remains experimental and does not receive live workspace writes in the normal lifecycle.
- Unknown names such as Leda are not guessed into compatibility claims.
- Existing Managed controller and runtime adapters remain optional and architecturally separate.
- Concurrent mutation, proposal-bound recovery, legacy read-only verification, and replay-safe uninstall follow [ADR-0012](ADR-0012-concurrent-host-lifecycle-and-replay-safe-uninstall.md).

## References

- [Native-host architecture](../18-native-hosts/README.md)
- [Support matrix](../18-native-hosts/support-matrix.md)
- [ADR-0008](ADR-0008-context-first-team-kits-and-discovery-bundles.md)
- [ADR-0009](ADR-0009-vendor-neutral-core-and-replaceable-ports.md)
- [ADR-0010](ADR-0010-scenario-first-guided-adoption.md)
