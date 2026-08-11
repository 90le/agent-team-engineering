---
name: install-agent-team-host
description: Plan, preview, confirm, apply, verify, reconcile, or uninstall a generated Agent Team package for OpenClaw, Hermes Agent, Codex, Claude Code, Multica, or generic file-capable AI. Use after a portable team exists when a person asks to adapt, install, export, load, verify, upgrade, move, or remove it in a specific AI host without overwriting user configuration or implying live account authority.
---

# Install Agent Team Host

Use only a validated team with `.agent-team/team-design.json` and `.agent-team/context.lock.json`. Team creation does not authorize host installation.

## Inspect and plan

1. Locate the stable Factory checkout used to generate the team.
2. Read its `docs/18-native-hosts/README.md`, `support-matrix.md`, and exactly one selected host guide.
3. Run `./agent-team context validate --root <team>`.
4. Run `./agent-team host list` and `./agent-team host probe --target <host-id>`.
5. Report detected version, evidence tier, limitations, and safe alternative. Do not read credentials, sessions, messages, private runtime state, or account data.
6. Use `host plan` with the locked team, exact target, destination, and a new plan path; run `host preview`. Prefer a new destination; an existing one is allowed only when every planned path is absent.

Show source lock, descriptor/version, destination, every managed artifact, evidence tier, limitations, digest, verification, and uninstall scope. Explain all untouched accounts, bindings, credentials, project files, and external systems. Stop for exact confirmation.

## Apply and verify

After confirmation, run the current plan's `host confirm` and `host apply`, then `./agent-team host verify --root <destination>`. Refuse stale digests, source drift, symlink crossings, planned-path collisions, different install locks, or artifacts outside the plan. Preserve unrelated destination content.

For OpenClaw and Hermes, use isolated state/home directories for CLI validation. Do not bind live channels or overwrite real profiles. For Multica `v0.4.23`, materialize the `experimental-plan` package only; never execute its proposed workspace writes. Treat Leda as `research-unknown`.

Report managed paths, evidence tier, checks passed/failed/skipped, observed external writes, credentials accessed, limitations, and uninstall boundary. Do not equate generation with host load or isolated validation with live support.

## Uninstall

Run `host verify --root <destination>`, inspect its install lock, and obtain separate confirmation. Use `./agent-team host uninstall --root <destination> --digest <exact-install-digest>`. Remove only unchanged Factory-owned artifacts; preserve user config, memories, sessions, credentials, channels, Skills, boards, projects, and unrelated Agents. Stop when ownership is ambiguous or managed files drifted.
