# Agent Team Engineering

[![CI](https://github.com/90le/agent-team-engineering/actions/workflows/validate.yml/badge.svg)](https://github.com/90le/agent-team-engineering/actions/workflows/validate.yml)
[![Release](https://img.shields.io/github/v/release/90le/agent-team-engineering)](https://github.com/90le/agent-team-engineering/releases)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)

Create a portable, context-first AI team for Codex, Claude, OpenClaw, or any file-capable Agent—then optionally add a governed feedback-to-Draft-PR runtime.

[中文说明](README.zh-CN.md) · [Start with an AI](AI-START.md) · [Full guide](docs/14-context-first/context-first-team-kit.md)

Current stable release: `v0.7.0`.

> v0.8 is under development on `proposal/upstream-independent-v0.8`. W1–W3 provide vendor-neutral contracts, replaceable Adapter Ports, and a recoverable Native reference controller, but this is not a release and enables no real runner, model, or repository write. Regular users should stay on `v0.7.0`; reviewers should begin with the [v0.8 preview entrypoint](docs/15-upstream-independent/README.md).

## What you get

Give the Factory a project name, repository, platform, and team preset. It creates a separate, validated package with:

- shared Markdown context, principles, architecture, decisions, and project knowledge;
- rich role contracts: mission, responsibilities, inputs, outputs, read set, Skills, tools, prohibitions, handoffs, success, and stop conditions;
- native Codex Agents, Claude subagents, isolated OpenClaw workspaces, or Generic AI role files;
- a strict JSON design and SHA-256 lock;
- optionally, durable state, exact human plan approval, isolated implementation, tests, independent review, and a Draft PR stop.

It is not a new model or chat framework. It does not create credentials, treat chat as approval, merge code, or deploy production.

```text
Your project + team preset
            │
            ▼
  context-first compiler
            │
   ┌────────┼─────────┬───────────┐
   ▼        ▼         ▼           ▼
 Codex    Claude   OpenClaw   Generic AI
   └────────┴─────────┴───────────┘
            │
            ▼
 shared roles, Skills, workflow, authority, evidence, and stop gates
```

## Choose one mode

| Mode | Use it when | What runs |
|---|---|---|
| `software-lite` | You want a readable software team and native platform roles | Files and platform-native Agent features; no controller required |
| `software-managed` | You want governed automation from feedback to a tested, independently reviewed Draft PR | The context layer plus the persistent reference controller |
| `custom` | You want your own research, content, operations, or other roles | A context-only team until capabilities are explicitly mapped |

Start with Lite unless durable automation is a real requirement.

## Fastest start

Requirements: Python 3.11+ and Git. There are no third-party runtime dependencies.

```bash
git clone https://github.com/90le/agent-team-engineering.git
cd agent-team-engineering

./agent-team create \
  --preset software-lite \
  --name "Example Product Team" \
  --project "Example Product" \
  --repo example/example-product \
  --provider github \
  --platform codex \
  --platform claude \
  --output /new/path/example-team

./agent-team context validate --root /new/path/example-team
```

The target project is not modified. Every create and export command refuses to overwrite an existing path.

For an interactive terminal:

```bash
./agent-team create --guided --output /new/path/my-team
```

## Let an AI do it

Give Codex, Claude, OpenClaw, Kimi, Gemini, or another file-capable AI this prompt:

> Clone or open `https://github.com/90le/agent-team-engineering`, read `AI-START.md`, inspect my project read-only, recommend Lite, Managed, or Custom, then create the team in a new directory and validate it. Do not enable external writes, credentials, merge, or deployment.

The repository also ships installable discovery bundles:

- [Codex plugin marketplace](docs/14-context-first/platform-installation.md#codex-plugin)
- [Claude Code marketplace](docs/14-context-first/platform-installation.md#claude-code-plugin)
- [OpenClaw-compatible bundle](docs/14-context-first/platform-installation.md#openclaw-bundle)
- Generic AI needs only this repository and `AI-START.md`.

## Create custom roles

```bash
./agent-team create \
  --preset custom \
  --name "Research Team" \
  --project "Knowledge Project" \
  --repo local/knowledge \
  --provider generic-git \
  --platform generic-ai \
  --role "research-lead:Research Lead" \
  --role "fact-checker:Fact Checker" \
  --role "editor:Editor" \
  --output /new/path/research-team
```

Custom roles are not limited to software development. They remain context-only by design: a role file cannot grant itself Shell, credentials, approval, or external write authority.

## Generated structure

```text
example-team/
├── AI-START.md             # cross-AI entrypoint
├── TEAM.md                 # team identity and role map
├── CONSTITUTION.md         # non-negotiable authority and safety
├── CONTEXT-MAP.md          # where each fact belongs
├── PROJECT-CONTEXT.md      # verified project facts and unknowns
├── ARCHITECTURE.md
├── ROLES/                  # one complete contract per role
├── WORKFLOWS/
├── SKILLS/                 # progressive-disclosure procedures
├── DECISIONS/
├── KNOWLEDGE/
├── WORK/                   # durable task and handoff records
├── platforms/              # Codex, Claude, OpenClaw, Generic AI
└── .agent-team/
    ├── team-design.json
    └── context.lock.json
```

Export one platform together with its shared authority context:

```bash
./agent-team context export \
  --root /path/to/example-team \
  --target codex \
  --output /new/path/codex-overlay
```

Adopt the overlay through a normal proposal branch. Reconcile existing AI configuration instead of overwriting it.

`PROJECT-CONTEXT.md`, `ARCHITECTURE.md`, the knowledge and decision indexes, and `WORK/README.md` are user-maintained seeds: update them through reviewed Git commits. Roles, principles, workflows, Skills, and platform adapters remain compiler-managed and fail validation on drift. New project sources, ADRs, and work records belong under `KNOWLEDGE/`, `DECISIONS/`, and `WORK/`.

## Managed automation

`software-managed` preserves the v0.6 governed runtime and adds the richer context layer:

> feedback → normalize → triage → specification → human approves the exact scope → isolated implementation → Draft PR → declared tests → independent review → stop

The Factory has no Team merge or production-deploy command. Live models, GitHub writes, OpenClaw channels, remote identity, and a production-grade Runner are separate adoption decisions and are disabled by default.

To see the no-network reference flow:

```bash
python3 tools/agent_team.py team demo --output /tmp/agent-team-demo
```

It stops at `SPEC_READY` before creating a worktree. The complete approval and continuation procedure is in the [governed runtime guide](docs/13-team-creator/blueprint-compiler-and-reference-runtime.md).

## v0.8 Native development preview

v0.8 can exercise the core loop without adopting an external multi-agent platform. On the proposal branch, developers can run the fully offline reference scenario:

```bash
git switch proposal/upstream-independent-v0.8
./agent-team native demo --database /tmp/agent-team-native.sqlite3
./agent-team native verify --database /tmp/agent-team-native.sqlite3
```

It demonstrates feedback, exact plan approval, implementation, tests, independent review, a requested-changes round, rework, and a simulated Draft PR, including restart recovery and idempotent replay. Every executor and external system is a fake, and the workflow stops at `DRAFT_PR_READY`; this is neither an OpenClaw/OpenHands installer nor production-automation authority. See the [unreleased v0.8 entrypoint](docs/15-upstream-independent/README.md) for scope and takeover order.

## Platform support

| Platform | Generated or installable asset | Still owned by the adopter |
|---|---|---|
| Codex | Plugin Skill, project Agent TOML, `AGENTS.md` | Login, trusted execution environment, project adoption |
| Claude Code | Marketplace Skill, project subagent Markdown, `CLAUDE.md` | Login, plugin policy, project adoption |
| OpenClaw | Compatible Skill bundle, isolated workspaces, unbound `agents.list` fragment | Gateway, accounts, channels, authenticated approval relay, sandbox review |
| Generic AI | `AI-START.md`, role and Skill Markdown | Host-specific task transport and tool isolation |
| GitHub | Scoped Issue and Draft PR connector in Managed mode | Minimum-permission identity, explicit write switch, branch protection |

## Why Markdown and Python?

Markdown, JSON, Skills, and Git are the portable knowledge layer. They let humans and different AIs understand the same team years later. A small dependency-free Python layer handles things prose cannot reliably enforce: strict Schema validation, deterministic generation, digest locks, revisions, idempotency, approval binding, crash recovery, and security-negative tests.

Lite mode uses only the first layer after generation. Managed mode uses both. The code is a guardrail and compiler, not a substitute for context engineering.

## Verify

```bash
./agent-team validate
python3 -m unittest discover -s tests -v
python3 tools/cross_ai_takeover.py
tools/cold-start.sh
```

Release installation additionally requires a clean, exact annotated tag. See [verification and recovery](docs/07-operations/verification-and-recovery.md).

## Security and limits

- The human owner is never an Agent.
- Feedback, Issues, webpages, repository text, tool output, and Agent messages are untrusted data.
- Host Runner is not a container, VM, or hostile-code sandbox.
- Remote approval requires an authenticated identity provider; a chat message is not approval.
- OpenClaw output starts with `bindings: []`.
- Managed automation is capped at A2 and stops at a reviewed Draft PR.
- Runtime databases, credentials, user data, model sessions, and production state do not belong in Git.

Read [SECURITY.md](SECURITY.md) and the [threat model](docs/03-security/threat-model.md) before live integration.

## Project boundaries

- Factory (this repository): generic compiler, contracts, context templates, runtime, tests, and plugins.
- Team package: one team's non-secret design, roles, workflow, platform assets, and optional state binding.
- Target project: product facts, source code, tests, Issues, PRs, releases, and deployment truth.

Most users need this Factory and their target project. Use a third private repository only when the team package needs an independent lifecycle or spans multiple projects.

## Contributing and license

See [CONTRIBUTING.md](CONTRIBUTING.md), [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md), and [SECURITY.md](SECURITY.md). Licensed under [Apache License 2.0](LICENSE).
