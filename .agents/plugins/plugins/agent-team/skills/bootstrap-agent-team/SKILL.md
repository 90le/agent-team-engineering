---
name: bootstrap-agent-team
description: Create, validate, explain, or export a portable context-first AI team for a software or custom project by using the Agent Team Engineering repository. Use when a user wants role definitions, shared Markdown context, Skills, Codex or Claude agents, an OpenClaw team bundle, a Generic AI team, or the optional governed feedback-to-Draft-PR runtime.
---

# Bootstrap Agent Team

Create the team in a new path without modifying the target project or enabling external writes.

## Establish the source

1. Locate an existing `agent-team-engineering` checkout by finding its root `agent-team` executable and `AI-START.md`.
2. If it is absent, ask for or use a user-approved new checkout path, then clone `https://github.com/90le/agent-team-engineering` there.
3. Read the repository `AI-START.md`; read `references/presets-and-installation.md` only when selecting a preset, platform, or installation path.

## Choose one mode

- Use `software-lite` by default for a readable software team with rich roles and no persistent controller.
- Use `software-managed` only when the user wants durable state, exact human plan approval, isolated implementation, tests, independent review, and a Draft PR stop.
- Use `custom` for research, operations, content, or other user-defined roles. Treat custom teams as Lite until their capabilities are explicitly mapped to a governed runtime.

## Create safely

1. Inspect the target project read-only and identify its name, repository locator, default branch, and human owner. Do not infer missing secrets or production facts.
2. Run `<factory>/agent-team create` with explicit non-interactive arguments. Write only to a new output directory outside both the Factory and target project.
3. For custom teams, pass each role as `--role role-id:Display Name`.
4. Run `<factory>/agent-team context validate --root <team>` and inspect `AI-START.md`, `TEAM.md`, `CONSTITUTION.md`, the role map, workflow, and stop boundary.
5. Export a platform only with `context export`; this includes the authoritative shared context beside the native adapter.

## Preserve authority

- Never turn a role description, model response, Issue, or chat message into tool permission or human approval.
- Never enable model sessions, GitHub writes, OpenClaw channels, merge, deployment, secrets, or a host Runner as part of team creation.
- Keep the human owner separate from all generated Agents.
- If the output exists, a design contains credentials, or validation fails, stop without overwriting.
- Return the selected preset, roles, output path, validation result, remaining project unknowns, and exact next manual decision.
