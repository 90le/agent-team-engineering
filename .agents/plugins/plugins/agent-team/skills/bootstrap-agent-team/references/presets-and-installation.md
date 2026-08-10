# Presets and installation

## Preset decision

| Need | Preset | Runtime |
|---|---|---|
| Readable software roles and shared context | `software-lite` | None required |
| Feedback through tested, independently reviewed Draft PR | `software-managed` | Optional Factory controller |
| Research, content, operations, or user-named roles | `custom` | None until explicitly mapped |

## Minimal commands

```bash
./agent-team create \
  --preset software-lite \
  --name "Example Product Team" \
  --project "Example Product" \
  --repo example/example-product \
  --provider github \
  --platform codex \
  --output /new/path/example-team

./agent-team context validate --root /new/path/example-team
```

For an interactive terminal, `./agent-team create --guided --output /new/path/team` prompts for missing values. Automation and Agents should prefer explicit arguments.

## Platform meaning

- `codex`: project Agent TOML and `AGENTS.md`.
- `claude`: project subagent Markdown and `CLAUDE.md`.
- `openclaw`: isolated workspaces and an unbound `agents.list` fragment; channel bindings remain empty.
- `generic-ai`: portable Markdown role adapters for other AI systems.

Repeat `--platform` to select more than one. Export one adapter and its shared context with:

```bash
./agent-team context export \
  --root /path/to/team \
  --target codex \
  --output /new/path/codex-overlay
```

Review the overlay in a proposal branch. Do not overwrite an existing `AGENTS.md`, `CLAUDE.md`, `.codex/`, or `.claude/` tree without reconciling the target project's own authority.
