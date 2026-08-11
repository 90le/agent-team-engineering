---
name: install-agent-team-host
description: Plan, preview, confirm, apply, verify, reconcile, or uninstall a generated Agent Team package for OpenClaw, Hermes Agent, Codex, Claude Code, Multica, or a generic file-capable AI host. Use after a portable team exists when a person asks to install, adapt, export, load, verify, upgrade, move, or remove that team in a specific AI/Agent host without overwriting user configuration or implying live account authority.
---

# Install Agent Team Host

Install only from a validated, locked portable team. Treat team creation and host installation as separate authority decisions.

## Establish the exact target

1. Read `docs/18-native-hosts/README.md` and `docs/18-native-hosts/support-matrix.md`.
2. Read exactly one selected host guide under `docs/18-native-hosts/`.
3. Verify the team contains `.agent-team/team-design.json` and `.agent-team/context.lock.json`; run `./agent-team context validate --root <team>`.
4. Run `./agent-team host list` and `./agent-team host probe --target <host-id>`.
5. Report the detected executable/version, current evidence tier, unknowns, and safe alternative. Probe must not read credentials, sessions, messages, private runtime state, or account data.

Do not install a missing host. Do not guess unknown identities. Multica `v0.4.23` is `experimental-plan` and Leda is `research-unknown`.

## Create a separate install plan

Prefer a new destination. An existing destination is allowed only when every planned managed file is absent; preserve unrelated content and refuse any collision or different install lock:

```bash
./agent-team host plan \
  --team /path/to/locked-team \
  --target <host-id> \
  --destination /new/path/host-team \
  --output /new/path/host-install-plan.json
./agent-team host preview --plan /new/path/host-install-plan.json
```

Show the source lock, host descriptor/version, destination, every managed artifact, evidence tier, limitations, digest, verification steps, and uninstall scope. State explicitly which existing host files, accounts, credentials, channels, bindings, repositories, and external systems remain untouched.

Stop for confirmation of the exact digest. Any change to source, target, destination, descriptor, or artifacts requires a new plan and confirmation.

## Apply and verify

After exact confirmation, use only the commands emitted by the current preview:

```bash
./agent-team host confirm \
  --plan /new/path/host-install-plan.json \
  --digest sha256:<exact-previewed-digest> \
  --approved-by "Project Owner"
./agent-team host apply --plan /new/path/host-install-plan.json
./agent-team host verify --root /new/path/host-team
```

Apply creates only absent files declared by the plan. It may preserve unrelated files in an existing destination, but fails closed on any planned-path collision, different install lock, symlink crossing, source drift, or stale digest.

For OpenClaw and Hermes, prefer isolated state/home directories for CLI validation. Never bind a live OpenClaw channel or overwrite a real Hermes profile. For Multica, materialize the offline overlay only; do not execute proposed workspace commands.

## Report evidence honestly

Return the install record and digest, managed paths, checks passed/failed/skipped, observed external writes, credentials accessed, resulting evidence tier, limitations, uninstall boundary, and a copyable first task. Do not promote “generated” to “loaded” or “isolated CLI verified” to “live supported”.

## Uninstall safely

Preview uninstall scope and obtain separate confirmation when removal is requested. Run `./agent-team host uninstall --root <destination> --digest <exact-install-digest>` only with the exact install record. Remove only unchanged Factory-owned artifacts; preserve user configuration, memories, sessions, credentials, channels, existing Skills, boards, projects, and unrelated Agents.

Stop on missing ownership evidence, drift that obscures ownership, or any target outside the recorded scope.
