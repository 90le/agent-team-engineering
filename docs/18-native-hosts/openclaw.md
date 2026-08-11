# OpenClaw native-team boundary

Official upstream: [openclaw/openclaw](https://github.com/openclaw/openclaw).

## Native projection

An OpenClaw projection preserves one portable authority while giving each role an isolated native workspace. The generated package may contain:

- a workspace per role with host discovery/instruction files;
- workspace-local `skills/<skill-id>/SKILL.md` packages;
- shared context references tied to the source team lock;
- an Agent/config installation plan with `bindings` empty;
- an ownership manifest for verification and uninstall.

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

After exact confirmation, Factory `apply` creates only absent package files declared by the plan. It preserves unrelated destination content and fails on a planned-path collision.

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

Channel bindings require a separate plan that identifies the exact Agent, channel/account, peer scope, authenticated human identity, untrusted-input boundary, rollback, and verification. Until then, keep `bindings: []`.

## Verification and uninstall

Verification may prove that expected workspaces and Skills exist, manifests match the plan digest, and an isolated compatible CLI accepts the generated shape. It cannot prove live message delivery or model behavior.

Uninstall may delete only paths recorded as Factory-owned by the exact install record. Never delete an existing user workspace, global config, session, credential, unrelated Skill, or Agent merely because it has the same display name.
