# Native-host support and evidence matrix

## Evidence tiers

| Tier | Exact meaning | What it does not prove |
|---|---|---|
| `native-verified` | An exact version was probed; native artifacts passed host schema/lint; isolated install, list/load, verify, uninstall, and a minimal task smoke test passed. | Real account/workspace mutation, live channel delivery, production safety, or compatibility with another version |
| `native-install-verified` | Isolated install, list/load, verify, and uninstall passed for an exact version, but no reliable account-free minimal task smoke test was possible. | Task execution, model quality, authenticated service behavior, or production safety |
| `verified-export` | Native-shaped artifacts passed structural checks and, where an official machine contract exists, its fixture checks; no real host state was changed. | Native load, task execution, authenticated writes, or production use |
| `experimental-plan` | An official interface was researched and a reviewable plan can be generated, but local runtime, account/workspace, or end-to-end import evidence is missing. | Compatibility, authenticated writes, or supported production use |
| `portable` | Host-neutral Markdown/JSON can be read by people and file-capable AI systems. | Native discovery, role spawning, isolation, scheduling, or lifecycle |
| `research-unknown` | The named host or version cannot be tied to an unambiguous official contract. | Any compatibility claim or pseudo-native output |

Release notes and acceptance evidence may downgrade a host. They must never promote one without the corresponding reproducible proof.

## Current targets

| Host | Release posture | Factory artifact | Evidence boundary | Important limitations |
|---|---|---|---|---|
| OpenClaw | `native-install-verified` | Per-role workspaces, workspace-local Skills, identity/instruction files, unbound registration plan | In a disposable isolated home, `2026.7.1-2` passed Agent add/list with zero bindings, `doctor --lint` with 24 checks and 0 errors, then Agent delete. The 30 warnings were expected because Gateway, tokens, and optional Skills were absent. | No model task, real account, Gateway, channel, binding, credential, approval relay, or live message claim |
| Hermes Agent | `native-install-verified` | Per-role profile distributions, `SOUL.md`, profile-local Skills, project/bundle/Kanban plan | In a disposable isolated home, `0.20.0` passed profile install/list/describe/delete without a model or credential. | No real user-profile overwrite, model task, credential, board execution, worker result, or production behavior claim |
| Codex | `verified-export` | Project `AGENTS.md`, Agent TOML, project-local Skills | Structural/Skill validation; any stronger tier requires a release acceptance record | No login, trust, tool grant, model session, external write, or production action |
| Claude Code | `verified-export` | Project `CLAUDE.md`, subagent Markdown, project-local Skills | Structural/Skill validation; any stronger tier requires a release acceptance record | No login, plugin trust, tool grant, model session, external write, or production action |
| Multica `v0.4.23` | `experimental-plan` | Agent instructions, Skill binding plan, squad topology, and reviewable CLI/API intent | Official `v0.4.23` repository/CLI contract reviewed; no live Multica installation or workspace write | Factory `apply` can materialize the offline package only; runtime/workspace identity and authentication remain unresolved; upstream uses a custom **Multica License** |
| Generic file-capable AI | `portable` | `AI-START.md`, roles, Skills, context, workflows, work records | Cross-AI cold-start/readability checks | No host-native spawning, scheduling, isolation, tool transport, or lifecycle |
| Leda | `research-unknown` (not in the host catalog) | None | No precise official repository, version, CLI, or configuration contract supplied | Do not infer that it means Loop, LlamaIndex, a private product, or any similarly named project |

## Multica pin and license boundary

The Multica research baseline is the official [`v0.4.23` tag](https://github.com/multica-ai/multica/tree/v0.4.23), including its [CLI and daemon guide](https://github.com/multica-ai/multica/blob/v0.4.23/CLI_AND_DAEMON.md) and [license file](https://github.com/multica-ai/multica/blob/v0.4.23/LICENSE).

The license file incorporates Apache License 2.0 text **plus additional conditions** covering hosted/embedded services, branding, attribution, contributions, and redistribution. Agent Team Engineering neither vendors Multica code nor re-licenses it. This statement is an engineering boundary, not legal advice; adopters must review the upstream license for their intended use.

## How to report a verification result

Record all of the following in the release acceptance document:

```text
host id:
descriptor revision:
host executable/version:
environment isolation:
source team lock digest:
generated package digest:
commands executed:
checks passed/failed/skipped:
external writes observed:
credentials accessed:
resulting evidence tier:
known limitations:
```

Use `skipped` rather than silently treating an unavailable live service as passing. Never write “supported” without naming the tier.
