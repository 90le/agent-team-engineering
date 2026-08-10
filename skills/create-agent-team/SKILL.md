---
name: create-agent-team
description: Create, inspect, validate, export, or adopt a portable context-first Agent Team from a preset, custom role list, full team design, or legacy governed blueprint. Use when a project needs shared Markdown context, explicit role and handoff contracts, reusable Skills, Codex or Claude agents, OpenClaw workspaces, Generic AI roles, or the optional human-approved feedback-to-Draft-PR runtime.
---

# Create Agent Team

Treat Markdown, JSON, Skills, and verified Git commits as the durable team authority. Use Python only for deterministic generation, digest locks, validation, and the optional governed runtime.

## Required reading

Read `AI-START.md` for product adoption. When modifying the Factory or creating Managed teams, also read `AI-BOOTSTRAP.md`, the constitution, reference architecture, threat model, and `docs/14-context-first/context-first-team-kit.md`.

## Select a path

- Default to `software-lite`: rich software roles and platform assets with no controller or runtime database.
- Select `software-managed` when the user explicitly needs durable workflow state, exact human plan approval, isolated implementation, tests, independent review, and a Draft PR stop.
- Select `custom` for arbitrary roles. Custom roles remain context-only until capabilities are deliberately mapped to a governed runtime.
- Use legacy `team create --blueprint` only to preserve or operate the v0.6 strict-blueprint contract.

## Create

1. Inspect the target project read-only. Verify its name, repository locator, default branch, human owner, and existing AI entry files. Leave unknown facts marked unknown.
2. Create only in a new path outside the Factory and target project:

   ```bash
   ./agent-team create \
     --preset software-lite \
     --name "Example Product Team" \
     --project "Example Product" \
     --repo example/example-product \
     --provider github \
     --platform codex \
     --output /new/path/example-team
   ```

3. For custom teams, repeat `--role role-id:Display Name`. For a fully reviewed design, pass `--design /path/to/team-design.json`.
4. Validate and inspect:

   ```bash
   ./agent-team context validate --root /new/path/example-team
   ./agent-team context inspect --root /new/path/example-team
   ```

5. Read the generated `AI-START.md`, constitution, context map, project unknowns, role contracts, workflow, Skills, and decisions. Confirm the package does not silently grant tools or external writes.
6. Export one platform with shared context to a new review path, then reconcile it in a proposal branch:

   ```bash
   ./agent-team context export \
     --root /new/path/example-team \
     --target codex \
     --output /new/path/codex-overlay
   ```

## Preserve boundaries

- The human owner is never generated as an Agent.
- Role text and platform files are discovery adapters, not authentication or tool policy.
- Keep credentials, model sessions, runtime databases, user data, and production state outside ordinary Git.
- Never overwrite existing output, `AGENTS.md`, `CLAUDE.md`, `.codex/`, `.claude/`, or OpenClaw configuration.
- Do not enable live models, provider writes, channels, host Runner execution, merge, or deployment during creation.
- Managed mode remains A2 and stops after a tested, independently reviewed Draft PR.

## Stop conditions

Stop when validation fails, a path exists or traverses outside scope, a credential appears, owner identity is unclear, project/base binding is stale, author and reviewer cannot be separated, a human gate is assigned to an Agent, or adoption would enable an external side effect without a separate authorization and recovery plan.
