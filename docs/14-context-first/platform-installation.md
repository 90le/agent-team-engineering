# Install and use with Codex, Claude, OpenClaw, or another AI

The repository is usable without installing a plugin: clone it, run `./agent-team`, or give its URL and `AI-START.md` to an AI. Plugins provide a discovery shortcut, not a separate implementation or permission system.

## Clone once

```bash
git clone https://github.com/90le/agent-team-engineering.git
cd agent-team-engineering
./agent-team presets
```

Use a release tag for reproducible adoption:

```bash
git checkout v0.7.0
```

## Give the repository to any AI

Use this prompt:

> Clone or open `https://github.com/90le/agent-team-engineering`, read `AI-START.md`, inspect my project read-only, recommend Lite, Managed, or Custom, then create the team in a new directory and validate it. Do not enable external writes, credentials, merge, or deployment.

An AI that can read files and run Python 3.11 needs no vendor-specific plugin.

## Codex plugin

The repository contains a Codex marketplace at `.agents/plugins/marketplace.json` and a self-contained `agent-team` plugin.

```bash
codex plugin marketplace add /absolute/path/agent-team-engineering/.agents/plugins
codex plugin add agent-team@agent-team-engineering
```

Start a new Codex thread, then ask:

> Use `$bootstrap-agent-team` to create a context-first team for this project.

The plugin contains only a Skill and metadata. It has no MCP server, credential, hook, or background process.

## Claude Code plugin

The repository root contains `.claude-plugin/marketplace.json`:

```bash
claude plugin marketplace add 90le/agent-team-engineering
claude plugin install agent-team@agent-team-engineering
```

Then invoke the installed `bootstrap-agent-team` Skill or ask Claude to create a context-first team for the current project. Marketplace installation copies the plugin into Claude's cache, so the bundle is self-contained and does not reference files outside its plugin root.

## OpenClaw bundle

OpenClaw can install Codex-compatible bundles and maps their Skill roots without loading arbitrary native plugin code. Install the same self-contained bundle after cloning:

```bash
openclaw plugins install /absolute/path/agent-team-engineering/.agents/plugins/plugins/agent-team
openclaw plugins list
openclaw plugins inspect agent-team
openclaw gateway restart
```

This installs the team-creation Skill. It does not create OpenClaw channel bindings. A generated team's `openclaw.fragment.json` deliberately has `bindings: []`; public intake and human approval must use different authenticated identities, channels, and workspaces.

## Generated platform overlays

The Factory plugin helps create a team. A generated team also has project-specific platform assets. Export them with shared context:

```bash
./agent-team context export \
  --root /path/to/team \
  --target claude \
  --output /new/path/claude-overlay
```

The exported `.agent-team/context/AI-START.md` is the portable entrypoint. Review and merge the overlay through the target project's normal governance.

## Uninstall and trust boundary

Use each platform's plugin manager to remove the discovery bundle. Generated team packages are ordinary files and Git history; plugin removal does not delete them. Review any third-party bundle before installation. This bundle intentionally ships no executable plugin runtime or external dependency.
