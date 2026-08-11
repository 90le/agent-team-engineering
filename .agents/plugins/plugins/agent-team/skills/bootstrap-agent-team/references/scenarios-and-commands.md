# Scenario decisions and deterministic commands

## Internal recommendation mapping

| User outcome | Coordination need | Internal mapping | Important boundary |
|---|---|---|---|
| Build or maintain software | People or AI tools invoke roles as needed | `software-lite` | No persistent controller |
| Feedback progresses across restarts to tested, independently reviewed Draft PR after exact human approval | Durable governed automation | `software-managed` | Live adapters disabled; no merge or deploy |
| Research, knowledge, content, operations, or user-named responsibilities | File-based or AI-assisted collaboration | `custom` | Context-only by default |
| Custom roles plus durable external automation | Advanced adoption project | Do not silently map | Specify each capability, identity, approval, evidence, and recovery first |

## Platform meaning

- `codex`: project Agent TOML plus an `AGENTS.md` discovery adapter.
- `claude`: project subagent Markdown plus a `CLAUDE.md` discovery adapter.
- `openclaw`: isolated role workspaces plus an unbound `agents.list` fragment; `bindings` remains empty.
- `generic-ai`: portable Markdown role adapters for Kimi, Gemini, local models, and other file-capable AI hosts.

Select every platform the user actually plans to use. Platform files do not create accounts, sessions, credentials, sandboxes, or tool grants.

## Deterministic lifecycle

```bash
./agent-team onboard inspect --project-path /path/to/project

./agent-team onboard plan \
  --project-path /path/to/project \
  --purpose software \
  --automation assisted \
  --goal "Turn requests into reviewed changes" \
  --platform codex \
  --team-name "Example Team" \
  --project-name "Example Product" \
  --owner "Project Owner" \
  --provider github \
  --repository example/product \
  --output /new/path/example-team \
  --plan /new/path/example-team-adoption-plan.json

./agent-team onboard preview --plan /new/path/example-team-adoption-plan.json
./agent-team onboard validate --plan /new/path/example-team-adoption-plan.json
```

After the user confirms the exact preview:

```bash
./agent-team onboard confirm \
  --plan /new/path/example-team-adoption-plan.json \
  --digest sha256:<exact-digest> \
  --approved-by "Project Owner"

./agent-team onboard apply --plan /new/path/example-team-adoption-plan.json
./agent-team context validate --root /new/path/example-team
```

An interactive human can instead run:

```bash
./agent-team onboard guided --output /new/path/example-team
```

For custom roles, repeat `--role role-id:Display Name`. Research/knowledge, content, and operations purposes receive a safe starter role set when roles are not specified.

## Separate project adoption

After team creation and a second explicit confirmation, export one reviewed overlay:

```bash
./agent-team context export \
  --root /path/to/team \
  --target codex \
  --output /new/path/codex-overlay
```

Reconcile the overlay in a proposal branch. Never overwrite existing `AGENTS.md`, `CLAUDE.md`, `.codex/`, `.claude/`, or OpenClaw configuration.
