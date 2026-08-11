# ADR-0010: scenario-first guided adoption with digest-bound plans

- Status: ACCEPTED
- Date: 2026-08-11

## Context

v0.8.0 could deterministically compile `software-lite`, `software-managed`, and `custom` teams, but exposed those implementation categories as the first ordinary-user choice. A new user or AI had to understand architecture before receiving a recommendation. The existing interactive command also created immediately after collecting values and generated packages lacked a complete daily-use guide.

Natural-language understanding belongs in AI guidance, while schema validation, confirmation binding, non-overwrite publication and deterministic compilation belong in code. Putting all reasoning into Python would create a brittle pseudo-conversation; leaving all confirmation in Markdown would make exact scope unenforceable.

## Decision

1. Model purpose, coordination depth and target AI platforms as independent adoption dimensions.
2. Keep existing presets as backward-compatible compiler mappings, not mandatory opening questions.
3. Require adoption Skills to inspect read-only facts, ask at most three high-impact questions per turn, explain one recommendation and an alternative, expose unknowns, and wait at a strict preview.
4. Introduce a versioned adoption-plan schema whose canonical proposal digest binds discovery, intent, recommendation, paths, effects and limitations.
5. Require explicit confirmation of that exact digest before local team creation.
6. Keep team creation and target-project export as separate confirmations.
7. Generate human and AI usage entrypoints that route plain-language outcomes to roles and support start, status, continue and stop operations.
8. Reject custom/non-software Managed claims until external capabilities, identity, approval, evidence and recovery are explicitly mapped.

## Consequences

The public first-run experience becomes scenario-first while scripts using explicit presets remain compatible. Plans can be validated and resumed by another AI on the same device without chat history. The CLI remains deterministic and does not claim natural-language intelligence.

The additional plan lifecycle adds commands and a schema, but supplies enforceable preview/confirmation semantics and auditable side-effect boundaries. Team creation still grants no credentials, external writes, merge, release or deployment authority.

## Recovery

The new layer is additive. Existing v0.8.0 preset and full-design creation remain available. If the guided layer cannot represent a supported design, an advanced user may review a complete team-design JSON and use the existing deterministic compiler; this must not be used to bypass a required confirmation or external integration gate.
