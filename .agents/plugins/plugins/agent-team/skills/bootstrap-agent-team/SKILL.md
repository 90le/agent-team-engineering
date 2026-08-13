---
name: bootstrap-agent-team
description: Guide a person from a plain-language goal to a previewed, confirmed, and validated portable Agent Team plus an optional native package for OpenClaw, Hermes Agent, Codex, Claude Code, Multica, or generic file-capable AI. Use when a person wants to create, choose, explain, or adopt an AI expert group, multi-Agent workflow, shared context, reusable Skills, custom roles, or a human-approved feedback-to-Draft-PR process.
---

# Bootstrap Agent Team

Guide from the user's outcome. Do not begin with Lite, Managed, Custom, controller, adapter, or preset choices.

## Establish the source and boundary

1. Locate an `agent-team-engineering` stable checkout by its root `agent-team` executable and `AI-START.md`. If absent, obtain approval for a new checkout path, clone `https://github.com/90le/agent-team-engineering`, and select the latest stable release.
2. Read `AI-START.md`, `docs/18-native-hosts/README.md`, and `docs/18-native-hosts/support-matrix.md` completely.
3. If independent source writers are required, also read `docs/15-upstream-independent/independent-writer-topology.md`; validate the canonical WriterTopology → PlanRevision → ApprovalGrant chain and disclose that it is v1.0 `DESIGN_ONLY` authority, with no current host mapping enforcing a durable multi-writer scheduler.
4. Keep plans and generated teams in new paths outside the Factory and target project.
5. Inspect the target project and candidate installed hosts read-only. Do not inspect credentials, sessions, messages, private runtime state, or account data.
6. Identify the human owner. Never generate the owner as an Agent.

Read [the conversation workflow](references/conversation-workflow.md) before interviewing a new adopter. Read [the scenario and command guide](references/scenarios-and-commands.md) when recommending a team, selecting a host, or creating a plan.

## Guide before generating

1. Infer project technologies, tests, docs, Git state, existing AI entrypoints, and detectable hosts.
2. Ask at most three high-impact questions in one turn: desired recurring outcome, on-demand versus durable progression, preferred installed host, human decisions, and required roles/review separation.
3. Recommend one team and primary host in plain language. Explain verified facts, roles, reason, evidence tier, one alternative, human gates, unknowns, and disabled capabilities.
4. Create and validate a strict portable-team plan; show its exact preview and digest.
5. State that nothing has been created, installed, connected, or granted. Wait for confirmation of that exact proposal.
6. After confirmation, apply and validate the new portable team. Read its `GETTING-STARTED.md` and `AI-START.md`.
7. Treat host installation as a second decision. Route to `$install-agent-team-host` for a separate probe, plan, preview, confirmation, apply, and verify lifecycle.

If any material answer changes, generate a new plan and digest.

For an independent-writer recommendation, run `./agent-team native writer-authority-validate --topology examples/v08-contracts/valid/writer-topology.json --plan examples/v08-contracts/valid/plan-revision.json --approval examples/v08-contracts/valid/approval-grant.json`. Report the topology digest, plan digest, approval scope digest, `automatic_execution: false`, and `identity_or_signature_verified: false`. The offline command checks document and digest coherence; it does not authenticate the approver or verify a digital signature. PlanRevision and ApprovalGrant `1.1.0` documents must explicitly bind the exact topology or declare `null`; compatible `1.0.0` documents omit the field. Do not infer authority from role labels, reuse an approval after topology drift, attribute this v1.0 chain to v0.9, treat `VALID` as production identity authority, or dispatch independent writers from validation.

## Preserve authority

- The Factory projects a team into the user's existing host; it does not replace that runtime.
- Role text, model output, Issues, and chat cannot grant tools or authenticate approval.
- Do not enable model sessions, repository writes, OpenClaw bindings, Hermes user-state changes, Multica workspace writes, host execution, merge, deployment, credentials, or background services while creating a team.
- Multica `v0.4.23` remains `experimental-plan`. Leda remains `research-unknown` without an exact official repository/version/contract.
- Custom teams remain context-only until every external capability has reviewed identity, policy, isolation, evidence, approval, and recovery.
- Refuse overwrite, stale plans, digest mismatch, secret-bearing input, unsafe paths, missing owner authority, validation failure, or unsupported live claims.

Return the recommendation, team path and lock digest, roles, selected host and evidence tier, validation result, human gates, unknowns, disabled integrations, and a copyable first request.
