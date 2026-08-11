# Context-first Agent Team Kit

This guide explains the product model, generated authority, creation paths, and exact boundary between readable context and deterministic runtime code.

## Product model

Agent Team Engineering has two cooperating planes:

1. The context plane is the long-lived, portable authority: Markdown, JSON, Skills, Git, role contracts, workflows, decisions, and project sources.
2. The execution plane performs deterministic work that prose cannot safely guarantee: Schema validation, digest locking, revisions, leases, idempotent effects, approval binding, isolated worktrees, test evidence, and recovery.

Using Python for the second plane is not a replacement for context engineering. Lite mode proves that the context plane can stand alone; Managed mode adds the execution plane only when durable automation is needed.

## Start with a guided outcome

Ordinary adopters should describe the outcome and let an AI or the interactive guide separate team purpose, coordination depth, and AI platforms:

```bash
./agent-team onboard guided --output /new/path/my-team
```

An AI should follow `AI-START.md`: inspect the project read-only, ask at most three high-impact questions per turn, explain its recommendation and alternative, materialize a strict preview, and wait for exact confirmation. See the [guided adoption guide](../17-guided-adoption/README.md).

## Advanced compiler mappings

The presets below remain deterministic implementation mappings for existing scripts and reviewed designs. New users do not need to choose one before the guided interview.

| Preset | Best for | Persistent controller | Roles |
|---|---|---:|---|
| `software-lite` | A readable development team used manually or through native AI platform features | No | Feedback, product, architecture, frontend, backend, QA, independent review, release handoff |
| `software-managed` | Feedback-to-Draft-PR automation with hard gates and crash recovery | Optional/available | The governed v0.6 role map used by the state machine |
| `custom` | Research, content, operations, or any user-defined collaboration | No | Any portable role IDs supplied by the user |

Custom roles do not gain runtime authority. If a future project wants a custom role to create Issues, write code, run tests, or call external systems, it must explicitly map that capability to a reviewed adapter, state transition, identity, and recovery policy.

## Generated package

```text
my-team/
├── AI-START.md
├── TEAM.md
├── CONSTITUTION.md
├── CONTEXT-MAP.md
├── PROJECT-CONTEXT.md
├── ARCHITECTURE.md
├── ROLES/
├── WORKFLOWS/
├── SKILLS/
├── DECISIONS/
├── KNOWLEDGE/
├── WORK/
├── platforms/
│   ├── codex/
│   ├── claude/
│   ├── openclaw/
│   └── generic-ai/
└── .agent-team/
    ├── team-design.json
    └── context.lock.json
```

Managed teams additionally contain the v0.6 Team Blueprint, instance, team lock, and runtime directories. The context lock covers the context plane; the existing team and instance locks cover the managed plane.

The lock distinguishes compiler-managed files from user-maintained seeds. `PROJECT-CONTEXT.md`, `ARCHITECTURE.md`, the decision and knowledge indexes, and `WORK/README.md` may evolve through normal reviewed Git commits. New ADRs, knowledge sources, and work packets may be added only below `DECISIONS/`, `KNOWLEDGE/`, and `WORK/`; they remain subject to UTF-8, size, symlink, and credential checks. Generated roles, principles, workflows, Skills, and platform adapters must be changed through Team Design and a new compilation.

## Role contract

Each role records:

- mission and bounded responsibilities;
- required inputs and reviewable outputs;
- minimum read set and Skills loaded on demand;
- requested tool capabilities and explicit forbidden actions;
- handoff recipient, condition, and deliverable;
- success and fail-closed stop conditions;
- preferred engine, model inheritance, reasoning level, and sandbox baseline;
- optional mapping to a governed runtime role.

These fields make a role portable across products. They do not authenticate the role or grant tools. The AI host, project policy, runtime state, and human approval still decide what can execute.

## Create and validate with explicit mappings

List the built-in choices:

```bash
./agent-team presets
```

Create a Lite software team:

```bash
./agent-team create \
  --preset software-lite \
  --name "Acme Product Team" \
  --project "Acme Product" \
  --repo acme/product \
  --provider github \
  --platform codex \
  --platform claude \
  --platform openclaw \
  --output /new/path/acme-team
```

Create a Managed software team:

```bash
./agent-team create \
  --preset software-managed \
  --name "Acme Managed Team" \
  --project "Acme Product" \
  --repo acme/product \
  --provider github \
  --platform codex \
  --platform claude \
  --output /new/path/acme-managed-team
```

Create arbitrary roles:

```bash
./agent-team create \
  --preset custom \
  --name "Editorial Team" \
  --project "Documentation Library" \
  --repo local/docs \
  --provider generic-git \
  --platform generic-ai \
  --role "researcher:Researcher" \
  --role "fact-checker:Fact Checker" \
  --role "editor:Editor" \
  --output /new/path/editorial-team
```

Every path is non-overwriting. Validate before adoption:

```bash
./agent-team context validate --root /path/to/team
./agent-team context inspect --root /path/to/team
```

To fully control fields, copy `.agent-team/team-design.json`, edit it as a proposal, validate it, and compile to another new path:

```bash
./agent-team context design-validate --file /proposal/team-design.json
./agent-team create --design /proposal/team-design.json --output /new/path/team-v2
```

## Export to a project

Exporting a platform includes both the native adapter and `.agent-team/context/`; it never exports a platform file without its authority sources.

```bash
./agent-team context export \
  --root /path/to/team \
  --target codex \
  --output /new/path/codex-overlay
```

Review the overlay in a target-project proposal branch. Reconcile an existing `AGENTS.md`, `CLAUDE.md`, `.codex/`, `.claude/`, or OpenClaw configuration rather than overwriting it.

## Managed runtime boundary

Managed mode compiles the same strict v1 Team Instance used by v0.6. External adapters remain disabled. The reference path is:

`feedback → normalize → triage → specification → exact human plan approval → isolated implementation → Draft PR → declared tests → independent review → stop`

It does not merge or deploy. The local human approval CLI uses the operating-system account as its identity boundary; remote approval needs a separate authenticated provider. The host Runner is not a production sandbox.

## Before and after

Before creation, a project may have only source code and scattered chat instructions. After creation, it has a separate, versioned team package with one discovery entry, one authority map, explicit roles, reusable Skills, a workflow, known unknowns, platform adapters, and a digest lock. The target project remains unchanged until the owner reviews an export.

## Safety properties

- Output and export paths must not exist.
- Absolute, traversal, symbolic-link, secret-bearing, or drifted authority fails validation.
- Human gates must be owned by a human actor.
- Managed roles must exactly map to the governed state machine and stop at Draft PR.
- Platform files cannot expand role authority.
- Custom teams remain Lite unless a separate implementation adds governed mappings.
- User context is maintainable in declared extension locations; unexpected root or platform files fail validation.
