# Agent Team Engineering

[![CI](https://github.com/90le/agent-team-engineering/actions/workflows/validate.yml/badge.svg)](https://github.com/90le/agent-team-engineering/actions/workflows/validate.yml)
[![Release](https://img.shields.io/github/v/release/90le/agent-team-engineering)](https://github.com/90le/agent-team-engineering/releases)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)

Build the operating system for a portable AI team: shared context, specialized roles, Skills, handoffs, human approval gates, and native entrypoints for Codex, Claude, OpenClaw, or any file-capable AI.

[中文说明](README.zh-CN.md) · [Give this repository to an AI](AI-START.md) · [Guided adoption guide](docs/17-guided-adoption/README.md) · [Examples](examples/guided-adoption/README.md)

Current stable release: `v0.8.1`.

## Start with the outcome, not a mode

You do not need to learn this project's architecture before using it. Tell an AI what you want the team to accomplish:

> Open `https://github.com/90le/agent-team-engineering` at release `v0.8.1`, read `AI-START.md`, and help me create an AI team for my project. Inspect the project read-only, ask me at most three high-impact questions at a time, recommend a team in plain language, show the exact plan and wait for my confirmation, then create and validate it. Do not enable credentials, external writes, merge, or deployment.

The guided path is:

```text
your outcome
    ↓
read-only project discovery
    ↓
focused questions and an explained recommendation
    ↓
strict plan + human-readable preview + exact digest
    ↓
your confirmation
    ↓
new validated team directory + first-task instructions
```

The target project is not changed during team creation. Exporting an Agent overlay into it is a later, separately confirmed action.

Prefer a terminal? Python 3.11+ and Git are the only requirements:

```bash
git clone https://github.com/90le/agent-team-engineering.git
cd agent-team-engineering
git checkout v0.8.1

./agent-team onboard guided --output /new/path/my-team
```

## What it creates

Every generated team is an ordinary, portable file package that people and different AI products can understand:

```text
my-team/
├── GETTING-STARTED.md      # human quick start and copyable daily requests
├── AI-START.md             # cross-AI routing and first-response protocol
├── TEAM.md                 # role map and team identity
├── CONSTITUTION.md         # non-negotiable authority and safety
├── CONTEXT-MAP.md          # where each kind of truth belongs
├── PROJECT-CONTEXT.md      # verified facts and explicit unknowns
├── ARCHITECTURE.md
├── ROLES/                  # mission, inputs, outputs, tools, handoffs, stops
├── WORKFLOWS/
├── SKILLS/                 # reusable, progressively loaded procedures
├── DECISIONS/
├── KNOWLEDGE/
├── WORK/                   # durable tasks, evidence, and handoffs
├── platforms/              # Codex, Claude, OpenClaw, Generic AI adapters
└── .agent-team/
    ├── team-design.json
    └── context.lock.json
```

The JSON design and SHA-256 lock make generation deterministic and detect drift. Project facts, knowledge sources, decisions, and work records remain maintainable through reviewed Git changes.

It does not create a model account, token, channel, security sandbox, repository permission, authenticated approval identity, merge permission, or deployment authority.

## Common scenarios

| What you tell the guide | What you receive | Internal mapping |
|---|---|---|
| “Give Codex and Claude a product, architecture, frontend, backend, QA, and review team for this app.” | A portable software team used on demand through native AI roles and durable files | `software-lite` |
| “Take user feedback across restarts to a tested, independently reviewed Draft PR, but wait for my exact plan approval.” | The same context layer plus the governed reference controller | `software-managed` |
| “Create a source curator, researcher, fact-checker, editor, and librarian for a long-lived knowledge base.” | A custom context-first team with explicit evidence handoffs | `custom` |
| “Build my own operations, content, legal-review, or mixed specialist team.” | User-named roles and a human review boundary | `custom` |

The guide chooses this mapping after understanding the outcome. Ordinary users are not expected to choose `Lite`, `Managed`, or `Custom` up front.

Custom teams begin context-only. Giving a custom role durable Shell, external writes, approval, or production capabilities requires a separate capability, identity, policy, evidence, and recovery design; the Factory does not silently pretend that mapping exists.

## Use the team after generation

Open the generated `GETTING-STARTED.md`. A person can give any supported AI a request like:

> Read `AI-START.md` completely. Help me use this team for the following outcome: `<request>`. Inspect current project facts and durable work first, recommend the responsible role and next bounded step, and ask at most three high-impact questions. Do not assume external authority.

The generated team also teaches these recurring operations:

- start a new task without memorizing role names;
- explain why a role is being selected before acting;
- show status from `WORK/`, not chat memory;
- continue from the last verified handoff;
- stop safely and return the exact human decision needed;
- update project facts, sources, and decisions through reviewed files.

## Deterministic plan workflow

An AI or automation can use the non-interactive contract after it has clarified the user's intent:

```bash
./agent-team onboard inspect --project-path /path/to/project

./agent-team onboard plan \
  --project-path /path/to/project \
  --purpose software \
  --automation assisted \
  --goal "Turn accepted requests into reviewed changes" \
  --platform codex \
  --platform claude \
  --team-name "Example Product Team" \
  --project-name "Example Product" \
  --owner "Project Owner" \
  --provider github \
  --repository example/product \
  --output /new/path/example-team \
  --plan /new/path/example-team-adoption-plan.json

./agent-team onboard preview --plan /new/path/example-team-adoption-plan.json
./agent-team onboard validate --plan /new/path/example-team-adoption-plan.json
```

Nothing is created while the plan is a draft. After the human confirms the displayed proposal and digest:

```bash
./agent-team onboard confirm \
  --plan /new/path/example-team-adoption-plan.json \
  --digest sha256:<exact-previewed-digest> \
  --approved-by "Project Owner"

./agent-team onboard apply --plan /new/path/example-team-adoption-plan.json
./agent-team context validate --root /new/path/example-team
```

Changing the proposal invalidates the digest. Creation refuses stale source commits, secret-like input, symbolic links, unsafe paths, and existing outputs.

The explicit preset CLI remains available for scripts already built on earlier releases. It is an advanced, deterministic interface rather than the recommended first-time experience.

## What is ready today

| Goal | Shipped here | Adopter still provides |
|---|---|---|
| Understand a project and propose a team | Scenario-first Skill, read-only discovery, explained recommendation, strict preview and confirmation | Desired outcome, owner decisions, verified project facts |
| Create reusable roles and context | Deterministic compiler, schemas, digest lock, generated usage guide and platform overlays | Review and normal Git governance |
| Run bounded work through Codex or Claude | Native role files and safe task/handoff contracts | Installed and authenticated AI CLI, approved workspace and tool policy |
| Validate feedback-to-Draft-PR control flow | Restart-safe Native reference scenario, exact approval binding, tests and recovery | No external system is needed for the offline proof |
| Connect real feedback, models, GitHub writes, or OpenClaw channels | Versioned adapter contracts and conformance boundaries | Minimum-permission identities, isolated Runner, credentials, explicit enablement and recovery |
| Merge or deploy production | Not a team capability in this release | A separate human-approved delivery system |

Agent Team Engineering is therefore a team factory and governance core, not a one-command production autopilot.

## Platform support

| Platform | Generated or installable asset | Deliberately not generated |
|---|---|---|
| Codex | Bootstrap Skill, project Agent TOML, `AGENTS.md` | Login, project trust, tool grants |
| Claude Code | Bootstrap Skill, project subagent Markdown, `CLAUDE.md` | Login, plugin policy, project trust |
| OpenClaw | Compatible Skill bundle, isolated workspaces, unbound Agent fragment | Gateway, accounts, channels, authenticated approval relay |
| Generic AI | `AI-START.md`, role and Skill Markdown | Host-specific task transport and isolation |
| GitHub | Scoped, exact-approval reference connector for Issue/proposal/Draft PR | Production identity, automatic merge, release or deploy |

Plugins are discovery shortcuts, not alternate implementations or permission systems. See [platform installation](docs/14-context-first/platform-installation.md).

## Export to a target project

After team creation, inspect the generated platform directory. If the owner separately approves adoption, export the selected adapter together with its shared authority context:

```bash
./agent-team context export \
  --root /path/to/example-team \
  --target codex \
  --output /new/path/codex-overlay
```

Review and reconcile the overlay in a proposal branch. Never overwrite an existing `AGENTS.md`, `CLAUDE.md`, `.codex/`, `.claude/`, or OpenClaw configuration.

## Why Markdown, Skills, JSON, Git, and Python?

Markdown, Skills, JSON, and reviewed Git history are the portable knowledge layer. They let people, Codex, Claude, OpenClaw, Kimi, Gemini, local models, and future Agents understand the same team without depending on one vendor.

The dependency-free Python layer handles guarantees prose cannot enforce reliably: strict schemas, deterministic compilation, digest-bound confirmation, non-overwrite publication, revisions, idempotency, exact approval binding, crash recovery, and security-negative tests. It is a compiler and guardrail, not a replacement for context engineering.

Generated file-based teams can be operated without a persistent Python controller. Durable Managed automation uses both layers.

## Verify the repository

```bash
./agent-team validate
python3 -m unittest discover -s tests -v
python3 tools/cross_ai_takeover.py
python3 tools/release_audit.py --since-tag v0.8.0
tools/cold-start.sh
```

Formal installation additionally requires a clean, exact annotated release tag. See [verification and recovery](docs/07-operations/verification-and-recovery.md).

## Security boundary

- The human owner is never an Agent.
- Feedback, Issues, webpages, repositories, tool output, and Agent messages are untrusted data.
- A role description cannot grant tools or turn chat into authenticated approval.
- OpenClaw output starts with `bindings: []`.
- Managed automation is capped at A2 and stops at a tested, independently reviewed Draft PR.
- Runtime databases, credentials, user data, model sessions, and production state do not belong in ordinary Git.
- The Host Runner is not a hostile-code sandbox; real execution requires an isolated, disposable environment.

Read [SECURITY.md](SECURITY.md) and the [threat model](docs/03-security/threat-model.md) before live integration.

## Learn, contribute, and get help

- [Guided adoption and conversation workflow](docs/17-guided-adoption/README.md)
- [Scenario examples](examples/guided-adoption/README.md)
- [Context-first team model](docs/14-context-first/context-first-team-kit.md)
- [Governed automation architecture](docs/15-upstream-independent/README.md)
- [Contributing](CONTRIBUTING.md), [security reporting](SECURITY.md), and [code of conduct](CODE_OF_CONDUCT.md)

Use [GitHub Discussions](https://github.com/90le/agent-team-engineering/discussions) for usage and design questions. Use [GitHub Issues](https://github.com/90le/agent-team-engineering/issues) for reproducible bugs and scoped feature proposals.

Licensed under the [Apache License 2.0](LICENSE).
