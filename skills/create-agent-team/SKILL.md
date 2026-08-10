---
name: create-agent-team
description: Create, inspect, validate, export, or adopt a portable governed multi-agent software team from an Agent Team Engineering blueprint. Use when a user wants to turn a project and platform choice into OpenClaw workspaces, Codex custom agents, Claude project subagents, generic-AI role packs, or a runnable feedback-to-Draft-PR team while preserving human approval, project scope, secret, recovery, and no-overwrite boundaries.
---

# Create Agent Team

## Overview

Compile one strict, secret-free blueprint into a version-locked team instance and platform-native
assets. Keep Factory, team instance, target project, runtime state, and external credentials as
separate authorities throughout creation and adoption.

## Required reading

Read these files before changing a blueprint, compiler output, or target adoption:

- `AI-BOOTSTRAP.md`
- `docs/01-principles/project-constitution.md`
- `docs/02-architecture/reference-architecture.md`
- `docs/03-security/threat-model.md`
- `docs/08-factory/instance-lifecycle.md`
- `docs/10-adapters/sdk-isolation-and-approval.md`
- `docs/13-team-creator/blueprint-compiler-and-reference-runtime.md`
- `schemas/team-blueprint.schema.json`
- the selected blueprint and target project's own AI/bootstrap authority

## Workflow

1. Establish the exact Factory revision, blueprint path, output path, target project, platforms,
   owner, autonomy ceiling, approval identity, recovery point, and whether external writes are
   authorized. Treat unspecified provider writes as disabled.
2. Inspect the target project read-only. Do not infer test commands, default branch, repository
   locator, secrets, deployment authority, or owner identity when they can be verified.
3. Copy the example blueprint to a project-controlled proposal location and change only declared
   fields. Bind every non-human team-pack role exactly once. Keep owner human, autonomy at or below
   A2, merge forbidden, production deployment forbidden, and plan approval required.
4. Keep credentials out of the blueprint. `secret_refs` are identifiers only; actual tokens,
   passwords, private keys, model sessions and channel credentials remain external.
5. Compile only to a new path:

   ```bash
   python3 tools/agent_team.py team create \
     --blueprint /path/to/team.json \
     --output /new/path/to/team-instance
   ```

6. Validate and inspect before export or runtime initialization:

   ```bash
   python3 tools/agent_team.py team validate --root /path/to/team-instance
   python3 tools/agent_team.py team inspect --root /path/to/team-instance
   python3 tools/agent_team.py doctor --instance /path/to/team-instance
   ```

7. Export one platform to a new review directory. Never copy over an existing target project tree:

   ```bash
   python3 tools/agent_team.py team export \
     --root /path/to/team-instance \
     --target codex \
     --output /new/path/to/codex-overlay
   ```

8. Adopt an export through a target-project proposal branch and normal review. Reconcile existing
   `AGENTS.md`, `CLAUDE.md`, `.codex/`, `.claude/` and OpenClaw configuration; never overwrite them.
9. Run the no-network reference scenario and full validation before enabling a real engine or code
   host. For live use, separately prove model authentication, per-task workspace isolation, runner
   commands, Git remote scope, Draft-PR-only permissions, provider reconciliation, pause and recovery.
10. Record the Factory version, blueprint digest, team lock, target commit, tests, approval evidence
    and rollback path. Chat history is not an authority or recovery artifact.

## Platform rules

- OpenClaw: separate public intake and approval relay workspaces, accounts and bindings. Keep the
  generated bindings empty until the live schema, channel identity, sandbox and tool policy pass.
- Codex: project agents use `.codex/agents/*.toml`. Give every writer a separate Git worktree and
  use read-only agents for triage/review. AGENTS instructions do not grant authority.
- Claude: project subagents use `.claude/agents/*.md`. Do not use bypass-permission mode; owner is
  not a subagent.
- Generic AI: load one role file into one isolated session and exchange only versioned contracts.

## Stop conditions

Stop without applying or enabling the team when any of these is true:

- output or export path already exists;
- blueprint or lock fails validation, contains a secret, or has managed drift;
- a role is missing, duplicated, assigned owner authority, or exceeds its sandbox boundary;
- public feedback and approval would share an OpenClaw session, account, workspace or credential;
- target repository, branch, commit or local path differs from the declared project;
- writer and reviewer identities are not independent;
- a model, Issue comment or IM message is being treated as human approval;
- live writes, arbitrary commands, merge, deployment, secrets or production data would be enabled
  without explicit instance-specific authorization and recovery evidence.
