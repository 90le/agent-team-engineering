# Install the guide and project a team into an AI host

There are two different installations:

1. **Discovery guide** — optional Skills that teach an AI how to interview, plan, create, and install a team.
2. **Generated team projection** — project-specific roles, Skills, context, and plans compiled for one host after human confirmation.

Installing the guide does not create a team. Creating a team does not install its host projection. Neither action grants an account, credential, binding, repository write, merge, or deployment authority.

## Universal path: give the repository to an AI

No plugin is required. Give a file-capable AI this request:

> Open `https://github.com/90le/agent-team-engineering` at its latest stable release, read `AI-START.md` completely, and help me build a native team for my project and an AI host I already use. Inspect both read-only, ask at most three high-impact questions, explain the recommendation and evidence tier, preview the exact plan, and wait for confirmation before creating or installing anything.

An AI with filesystem access, Git, and Python 3.11+ can clone the Factory and use its deterministic CLI.

## Clone a stable release

```bash
git clone https://github.com/90le/agent-team-engineering.git
cd agent-team-engineering
git fetch --tags
git checkout "$(git tag --list 'v*' --sort=-version:refname | head -n 1)"
./agent-team validate
```

Do not use an unreviewed development branch for ordinary adoption.

## Optional Codex discovery plugin

The repository contains a Codex marketplace and a self-contained `agent-team` plugin:

```bash
codex plugin marketplace add /absolute/path/agent-team-engineering/.agents/plugins
codex plugin add agent-team@agent-team-engineering
```

Start a new thread so discovery metadata is refreshed. Then ask:

> Use `$bootstrap-agent-team` to inspect this project and installed AI hosts read-only, recommend a host-native expert team, show the exact plan, and wait for confirmation before creating anything.

After a locked team exists, invoke `$install-agent-team-host` for its separate host plan and confirmation.

The plugin has Skills and metadata only. It has no MCP server, credential, hook, external dependency, or background process.

## Optional Claude Code discovery plugin

The repository root contains a Claude marketplace:

```bash
claude plugin marketplace add 90le/agent-team-engineering
claude plugin install agent-team@agent-team-engineering
```

Start a new Claude Code session, then invoke `bootstrap-agent-team`. Use `install-agent-team-host` only after the portable team is created and validated.

## Optional OpenClaw discovery plugin

Review the bundle, then install it from a stable local checkout:

```bash
openclaw plugins install /absolute/path/agent-team-engineering/.agents/plugins/plugins/agent-team
openclaw plugins list
openclaw plugins inspect agent-team
```

Restarting a live Gateway is a separate operational action; do it only when the owner has approved the interruption and recovery path. Installing the discovery plugin does not create Agents or bindings.

## Use the guide from Hermes Agent

Hermes can work from the stable checkout without duplicating the Factory into its user home:

```bash
hermes --in /absolute/path/agent-team-engineering
```

Then ask Hermes to read `AI-START.md` and guide the same scenario-first workflow. The generated Hermes team projection is installed separately; do not overwrite real profiles, memories, sessions, authentication, or `.env` while creating it.

## Create the portable team

The AI guide uses `onboard plan|preview|validate`, waits for an exact digest confirmation, then uses `onboard confirm|apply` and `context validate`. The result is a new, locked portable team directory outside the Factory and target project.

## Project the locked team into one host

```bash
./agent-team host list
./agent-team host probe --target openclaw
./agent-team host plan \
  --team /path/to/locked-team \
  --target openclaw \
  --destination /path/to/managed-projection \
  --output /path/to/openclaw-plan.json
./agent-team host preview --plan /path/to/openclaw-plan.json
```

After reviewing the plan JSON, preview, exact files, digest, tier, limitations, and uninstall scope:

```bash
./agent-team host confirm \
  --plan /path/to/openclaw-plan.json \
  --digest sha256:<exact-previewed-digest> \
  --approved-by "Human Owner"
./agent-team host apply --plan /path/to/openclaw-plan.json
./agent-team host verify --root /path/to/managed-projection
```

Apply creates only absent planned files. It preserves unrelated destination content, refuses collisions and symlink crossings, and never touches live host configuration or external APIs. Native object registration, account login, OpenClaw binding, Hermes real-profile adoption, and Multica workspace writes remain separate host-specific actions.

To uninstall, first verify and inspect the install lock, obtain a separate human confirmation, then use the recorded digest:

```bash
./agent-team host uninstall \
  --root /path/to/managed-projection \
  --digest sha256:<exact-install-digest>
```

Uninstall refuses drift and removes only unchanged Factory-owned files. Unrelated destination content is preserved.

## Evidence boundary

Consult the [support matrix](../18-native-hosts/support-matrix.md) instead of assuming every host has equal proof. OpenClaw and Hermes Agent are currently `native-install-verified`; Codex and Claude Code are `verified-export`; Multica `v0.4.23` is `experimental-plan`; Generic AI is `portable`; Leda is `research-unknown` and has no generated native adapter.

## Remove the discovery guide

Use the selected host's plugin manager to remove the optional discovery plugin. Plugin removal does not delete generated teams or managed projections. Use `host uninstall` with the exact install lock for a managed projection, and normal reviewed Git/file governance for portable team authority.
