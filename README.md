# Agent Team Engineering

[![CI](https://github.com/90le/agent-team-engineering/actions/workflows/validate.yml/badge.svg)](https://github.com/90le/agent-team-engineering/actions/workflows/validate.yml)
[![Release](https://img.shields.io/github/v/release/90le/agent-team-engineering)](https://github.com/90le/agent-team-engineering/releases)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)

**A host-native Agent Team Factory for OpenClaw, Hermes Agent, Codex, Claude Code, and other AI hosts.** Turn a project, a goal, and human authority boundaries into a portable team source plus files that the chosen host understands natively.

[中文说明](README.zh-CN.md) · [Give this repository to an AI](AI-START.md) · [Native-host guide](docs/18-native-hosts/README.md) · [Examples](examples/guided-adoption/README.md)

## What this project does

Bring an existing project or a new idea. The Factory guides a short interview, proposes the right specialists and workflow, waits for exact human confirmation, then compiles a reviewable team:

```text
project facts + desired outcome + human boundaries
                         │
                         ▼
       portable team source: context, roles, Skills,
       workflows, decisions, work records, digest lock
                         │
          ┌──────────────┼───────────────┐
          ▼              ▼               ▼
    OpenClaw team   Hermes profiles   Codex / Claude
    workspaces      and Kanban plan   native project files
```

The Factory does **not** replace OpenClaw, Hermes Agent, Codex, Claude Code, or Multica. It compiles the same governed team intent into host-native packages and safe installation plans. Choose an AI host you already use; do not adopt another runtime just for this project.

For long-running feedback → analysis → approval → implementation → independent review → tested Draft PR workflows, the repository also includes an optional **Managed** controller. It is a governed automation layer, not the default mode and never grants merge or production deployment authority. In v0.9 it deliberately has one source-writing `builder`; choose the on-demand native team when separate frontend and backend writer identities are mandatory.

## Give it to an AI

Copy this prompt into an AI that can read a repository and run local commands:

> Open `https://github.com/90le/agent-team-engineering`, use the latest stable release, and read `AI-START.md` completely. Help me build a native AI team for my project. First inspect the project read-only and detect the AI hosts I already have. Ask at most three high-impact questions at a time, recommend a team and target host in plain language, disclose the evidence level and limitations, show the exact plan, and wait for my confirmation before creating or installing anything. Do not enable credentials, external writes, channel bindings, merge, or deployment.

The AI should lead this conversation:

1. What outcome should the team repeatedly produce?
2. Which project facts and installed AI hosts can be verified read-only?
3. Which decisions must remain human, and who is the human owner?
4. Which roles, Skills, context, and host-native shape best fit those answers?
5. What exact files and paths will be created, and what remains disabled?
6. Does the owner confirm this exact digest-bound plan?

Users do not need to choose “Lite”, “Managed”, “Custom”, an adapter, or a controller up front. Those are internal mappings the guide explains only after understanding the outcome.

## Terminal quick start

Python 3.11+ and Git are the only Factory requirements:

```bash
git clone https://github.com/90le/agent-team-engineering.git
cd agent-team-engineering
git fetch --tags
git checkout "$(git tag --list 'v*' --sort=-version:refname | head -n 1)"

./agent-team onboard guided --output /new/path/my-team
```

The guided flow is safe by default:

```text
read-only discovery → recommendation → plan → preview → human confirmation
                    → new team directory → validation
```

Team creation does not modify the target project. Installing a generated native package is a second, separately previewed and confirmed lifecycle:

```bash
./agent-team host list
./agent-team host probe --target openclaw
./agent-team host plan \
  --team /path/to/my-team \
  --target openclaw \
  --destination /new/path/openclaw-team \
  --output /new/path/openclaw-install-plan.json
./agent-team host preview --plan /new/path/openclaw-install-plan.json
```

After reviewing the paths, limitations, digest, and rollback information, follow the displayed `confirm`, `apply`, and `verify` instructions. `apply` creates only absent files declared by the plan; unrelated destination content is preserved and any planned-path collision fails closed. It does not log in, create credentials, bind channels, write to a Multica workspace, merge code, or deploy production.

## Inputs and outputs

| You provide | The Factory produces | You still control |
|---|---|---|
| Project path or idea | Verified facts and explicit unknowns | Which facts and goals are correct |
| Desired recurring outcome | Recommended roles and handoff workflow | Team scope and human owner |
| Existing AI host | Host-native package and install plan | Login, trust, model and tool policy |
| Authority boundaries | Constitution, approval gates and stop conditions | Credentials and sensitive approvals |
| Optional automation need | Managed workflow capped at reviewed Draft PR | External identities, merge and deployment |

Every generated team remains ordinary, portable files:

```text
my-team/
├── GETTING-STARTED.md      # copyable first and daily requests
├── AI-START.md             # cross-AI discovery and routing
├── TEAM.md                 # team identity and role map
├── CONSTITUTION.md         # authority and safety boundaries
├── CONTEXT-MAP.md          # where each kind of truth belongs
├── PROJECT-CONTEXT.md      # verified facts and explicit unknowns
├── ROLES/                  # missions, inputs, outputs, handoffs, stops
├── WORKFLOWS/
├── SKILLS/                 # reusable, progressively loaded procedures
├── DECISIONS/
├── KNOWLEDGE/
├── WORK/                   # durable tasks, evidence and handoffs
├── platforms/              # host-native projections
└── .agent-team/
    ├── team-design.json
    └── context.lock.json
```

Markdown, Skills, JSON, and Git are the portable authority layer. Dependency-free Python supplies guarantees prose cannot reliably enforce: strict schemas, deterministic compilation, digest-bound confirmation, non-overwrite publication, drift checks, idempotency, recovery, and security-negative tests. File-based teams do not require a persistent Python controller after generation.

## Host support is evidence-based

“A directory was generated” is not the same as “the host loaded it”, and neither means a live channel or production workflow was exercised. This project reports support with explicit evidence tiers:

- **native-verified** — isolated native install/load/uninstall and a minimal task smoke test passed for an exact host version;
- **native-install-verified** — isolated native install/load/uninstall passed, but no reliable account-free task smoke test was possible;
- **verified-export** — native-shaped files and an import plan are structurally/contract validated, but no real host state was changed;
- **experimental-plan** — an upstream contract is tracked and a reviewable plan can be generated, but end-to-end host import is unverified;
- **portable** — host-neutral Markdown/JSON only;
- **research-unknown** — no unambiguous upstream identity or reproducible contract exists.

OpenClaw `2026.7.1-2` and Hermes Agent `0.20.0` are `native-install-verified`: their packages completed install/list-or-describe/uninstall checks in disposable isolated homes, without models or credentials. They are not `native-verified` because no minimal task was run. Codex and Claude Code are `verified-export`. Multica `v0.4.23` is **`experimental-plan`** with no live workspace write; its upstream licensing has additional terms and must be reviewed independently. “Leda” is **`research-unknown`** until a precise repository, version, and integration contract are supplied.

See the [support matrix](docs/18-native-hosts/support-matrix.md) for exact artifacts, proof, limitations, and version pins.

## Three usage shapes

| User outcome | Recommended shape | Boundary |
|---|---|---|
| “Create specialists that my existing AI can invoke for this project.” | Native host team | Context, roles, Skills, handoffs; host remains the runtime |
| “Create a research, knowledge, content, operations, or custom expert group.” | Custom context-first team | Context-only until each external capability is engineered |
| “Carry approved feedback across restarts to a tested, independently reviewed Draft PR.” | Native team + optional Managed controller | One source-writing builder; exact human approval; no automatic merge or deployment |

## Use a generated team

Start with the generated `GETTING-STARTED.md`, or tell the target AI:

> Read `AI-START.md` completely. Help me use this team for: `<request>`. Inspect verified project facts and durable work first, explain the responsible role and next bounded step, and ask at most three high-impact questions. Do not assume external authority.

The team records state in `WORK/` and reviewed Git files instead of depending on chat memory. A different person, model, device, or compatible host can resume from the same evidence.

## Security and honesty boundaries

- The human owner is never an Agent.
- Issues, chats, webpages, repositories, tool output, and Agent messages are untrusted data.
- A role description cannot grant a tool or turn chat into authenticated approval.
- Creation and installation plans are separate, digest-bound decisions and refuse overwrite by default.
- Host discovery must be read-only; secrets, sessions, runtime databases, and production data do not belong in Git.
- OpenClaw channel bindings, Multica workspace writes, live external adapters, merge, release, and deployment remain disabled unless separately engineered and authorized.
- Managed automation stops at a tested, independently reviewed Draft PR.
- A Host Runner is not a hostile-code sandbox; real execution needs an isolated, disposable environment.

Read [SECURITY.md](SECURITY.md), the [threat model](docs/03-security/threat-model.md), and [ADR-0011](docs/adr/ADR-0011-host-capability-contract-and-native-team-projection.md) before enabling a live integration.

## Documentation

- [Native-host architecture and lifecycle](docs/18-native-hosts/README.md)
- [Support and evidence matrix](docs/18-native-hosts/support-matrix.md)
- [Human/AI conversation workflow](docs/18-native-hosts/conversation-workflow.md)
- [Install the optional discovery plugin and host projection](docs/14-context-first/platform-installation.md)
- [Guided adoption](docs/17-guided-adoption/README.md)
- [Context-first team model](docs/14-context-first/context-first-team-kit.md)
- [Optional governed automation](docs/15-upstream-independent/README.md)
- [Contributing](CONTRIBUTING.md), [security reporting](SECURITY.md), and [code of conduct](CODE_OF_CONDUCT.md)

Use [GitHub Discussions](https://github.com/90le/agent-team-engineering/discussions) for usage and design questions. Use [GitHub Issues](https://github.com/90le/agent-team-engineering/issues) for reproducible bugs and scoped feature proposals.

Licensed under the [Apache License 2.0](LICENSE).
