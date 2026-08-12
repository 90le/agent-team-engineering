# OpenClaw native-team boundary

Official upstream: [openclaw/openclaw](https://github.com/openclaw/openclaw).

## Native projection

An OpenClaw projection preserves one portable authority while giving each role an isolated native workspace. The generated package may contain:

- a workspace per role with host discovery/instruction files;
- workspace-local `skills/<skill-id>/SKILL.md` packages;
- shared context references tied to the source team lock;
- an Agent/config installation plan with `bindings` empty;
- an ownership manifest for verification and uninstall.

The generated fragment uses the top-level `agents.list[].tools.deny` as the final
per-Agent hard stop and keeps elevated access disabled. Read-only roles also deny
`group:runtime`, which covers OpenClaw's runtime execution family in addition to the
named `exec` and `process` tools. Every generated role denies OpenClaw automation,
messaging, node, cross-session/Agent, media, plugin, and UI tool groups by default;
receiving a normal bound turn does not require granting the model those control-plane
tools. Writer roles retain only their separately governed filesystem/runtime surface.
The Factory intentionally does **not** emit
`agents.list[].tools.sandbox.tools`: in OpenClaw `2026.7.1-2`, a per-Agent sandbox
tool policy replaces rather than merges the adopter's global
`tools.sandbox.tools`, so a static fragment could accidentally remove a stricter
global deny such as `sessions_send`.

`openclaw sandbox explain --agent <id> --json` reports only the sandbox sub-policy,
not the complete final tool-policy pipeline. Its candidate `allow` list may still
name a tool that the top-level Agent deny blocks, and its `fixIt` list is a list of
configuration surfaces rather than proof that one is missing. Validate the complete
merged configuration, preserve stricter global policy, and never infer final tool
authority from that one inspector section alone.

The generated OpenClaw files are derived. Edit the portable `ROLES/`, `SKILLS/`, workflows, and policy source, then regenerate; do not maintain divergent role policy inside the host projection.

## Safe lifecycle

```bash
./agent-team host probe --target openclaw
./agent-team host plan \
  --team /path/to/locked-team \
  --target openclaw \
  --destination /new/path/openclaw-team \
  --output /new/path/openclaw-install-plan.json
./agent-team host preview --plan /new/path/openclaw-install-plan.json
```

Probe is limited to executable identity/version and does not read the user's messages, sessions, tokens, channel configuration, or private Agent state.

Use the [common v1 host lifecycle](README.md) without weakening it for OpenClaw. The `1.1.0` plan/lock binds the complete proposal, persistent empty guard, deterministic file stages, fixed transient metadata scratch, prior lifecycle identities, effects, and exact digest. First `apply` creates only absent declared package files; only an exact same-proposal `APPLYING` record may resume their stages after a crash. The lifecycle may create or replace and then delete only its declared scratch and must leave it absent on success. An exact empty guard without a lock may be reused but grants no deletion authority. It preserves unrelated destination content and fails on every other collision or lifecycle drift. A v0.9 plan must be rebuilt and reconfirmed; a v0.9 lock is `LEGACY_UNBOUND`, read-only verifiable, and not automatically uninstallable.

The `native-install-verified` evidence for OpenClaw `2026.7.1-2` comes from a disposable isolated home: Agent add/list succeeded with zero bindings, `doctor --lint` reported 24 checks and 0 errors, and Agent delete succeeded. Its 30 warnings were expected in the synthetic environment because no Gateway, token, or optional Skills were configured. No model task, account, real channel, or credential was used, so this evidence does not qualify as `native-verified`.

## Not authorized by installation

Installing a package does not authorize the Factory or generated roles to:

- start, restart, or reconfigure a Gateway;
- create or use an account;
- read credentials or sessions;
- create channel or peer bindings;
- relay human approval from chat;
- run a background team or scheduled job;
- write a repository, merge, release, or deploy.

Channel bindings require a separate plan that identifies the exact Agent, channel/account, peer scope, authenticated human identity, untrusted-input boundary, recovery/removal procedure, and verification. Until then, keep `bindings: []`.

## Verification and uninstall

Verification may prove that expected workspaces and Skills exist, manifests match the plan digest, and an isolated compatible CLI accepts the generated shape. It cannot prove live message delivery or model behavior.

Run `host uninstall-preview` before removal. For `ACTIVE` and `UNINSTALLING`, its delete/create lists and `transient_files` all identify the fixed metadata scratch because uninstall may create and delete it; success leaves it absent. `ACTIVE` requires human process confirmation before using the exact proposal digest, and the CLI stores no authenticated approval. Resume `UNINSTALLING` directly. `ALREADY_UNINSTALLED` and `LEGACY_UNBOUND` have empty delete/create/transient lists; replay the former only with the same digest and never automatically uninstall the latter. Uninstall may delete only immediately rechecked paths owned by the proposal-bound install record and manage only the declared scratch. It never deletes directories, retains the empty guard/tombstone, and may leave empty directories. Never delete an existing user workspace, global config, session, credential, unrelated Skill, similarly named hidden file, or Agent merely because it has the same display name.
