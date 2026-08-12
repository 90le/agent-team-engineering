---
name: install-agent-team-host
description: Plan, preview, confirm, apply, verify, reconcile, or uninstall a generated Agent Team package for OpenClaw, Hermes Agent, Codex, Claude Code, Multica, or a generic file-capable AI host. Use after a portable team exists when a person asks to install, adapt, export, load, verify, upgrade, move, or remove that team in a specific AI/Agent host without overwriting user configuration or implying live account authority.
---

# Install Agent Team Host

Install only from a validated, locked portable team. Treat team creation and host installation as separate authority decisions.

## Establish the exact target

1. Read `docs/18-native-hosts/README.md` and `docs/18-native-hosts/support-matrix.md`.
2. Read exactly one dedicated selected-host guide when it exists. OpenClaw, Hermes Agent, and Multica have dedicated pages; for Codex, Claude Code, or Generic AI, use the architecture, support matrix, conversation workflow, and exact `hosts/<host-id>/host.json` descriptor. Do not invent a missing guide.
3. Verify the team contains `.agent-team/team-design.json` and `.agent-team/context.lock.json`; run `./agent-team context validate --root <team>`.
4. Run `./agent-team host list` and `./agent-team host probe --target <host-id>`.
5. Report the detected executable/version, current evidence tier, unknowns, and safe alternative. Probe must not read credentials, sessions, messages, private runtime state, or account data.

Do not install a missing host. Do not guess unknown identities. Multica `v0.4.23` is `experimental-plan` and Leda is `research-unknown`.

## Create a separate install plan

Prefer a new destination. An existing directory is allowed only when unrelated content can be preserved, every first-apply projected file and deterministic file stage is absent, and any prior tombstone matches the plan baseline. The only file-stage recovery exception is an exact same-proposal `APPLYING` lock. The fixed metadata scratch is separately lifecycle-managed; an exact empty guard with no install lock may be reused but grants no deletion authority. Refuse every other collision or install lock:

```bash
./agent-team host plan \
  --team /path/to/locked-team \
  --target <host-id> \
  --destination /new/path/host-team \
  --output /new/path/host-install-plan.json
./agent-team host preview --plan /new/path/host-install-plan.json
```

Show plan schema `1.1.0`, the source lock, complete host descriptor/version, destination, every projected artifact and deterministic file `stage_path`, the fixed transient metadata stage `.agent-team/.host-lifecycle.json.stage`, persistent `empty-regular-file-v1` guard and empty-content digest, install record, uninstall tombstone, expected prior guard/tombstone identities, any exact prior-tombstone deletion, all filesystem effects, retained files, `directories_removed: false`, evidence tier, limitations, digest, verification, and uninstall scope. Distinguish `filesystem_deletes: true` for declared scratch management from `persistent_filesystem_deletes` for exact prior-tombstone removal. Explain that lock schema `1.1.0` retains the complete proposal and exact guard binding. State explicitly which host files, similarly named hidden files, accounts, credentials, channels, bindings, repositories, and external systems remain untouched.

Stop for confirmation of the exact digest. Any change to source, target, destination, descriptor, artifact/stage set, prior lifecycle baseline, or effect requires a new plan and confirmation. Reject an unexecuted v0.9 plan and run a fresh `plan → preview → confirm`; never carry its approval into schema `1.1.0`.

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

On first apply, create only absent projected files plus declared lifecycle metadata. The operation may create or replace and then delete only the fixed metadata scratch; require it to be absent after success and never touch a similarly named hidden file. Persistently delete a prior tombstone only when the newly confirmed plan displayed and bound that exact identity and effect. If a crash leaves the complete, exact `APPLYING` lock, rerun only the same confirmed plan: validate or rebuild its deterministic file stages and resume. Once `ACTIVE`, verification must reject every leftover file stage and the metadata scratch. Preserve unrelated files and fail closed on every other collision, changed prior tombstone, unsafe guard, different install lock, concurrent lifecycle process, symlink crossing, source drift, or stale digest.

Treat the persistent operation guard as an exact empty regular file with the `empty-regular-file-v1` format and empty-content digest. A precise empty guard without an install lock supports recovery when a crash occurs after guard fsync but before the `APPLYING` lock; never delete it or infer file-deletion authority from it. POSIX `fcntl` covers cooperating local Factory commands only, not root, the kernel, filesystem/storage compromise, or another privileged writer.

When `host verify` reports `LEGACY_UNBOUND`, report a v0.9 lock with read-only verification only. Do not apply over it or enable automatic destructive uninstall; require manual ownership reconciliation.

For OpenClaw and Hermes, prefer isolated state/home directories for CLI validation. Never bind a live OpenClaw channel or overwrite a real Hermes profile. For Multica, materialize the offline overlay only; do not execute proposed workspace commands.

## Report evidence honestly

Return the install record and digest, managed paths, checks passed/failed/skipped, observed external writes, credentials accessed, resulting evidence tier, limitations, uninstall boundary, and a copyable first task. Do not promote “generated” to “loaded” or “isolated CLI verified” to “live supported”.

## Uninstall safely

Start every removal with the read-only scope preview:

```bash
./agent-team host uninstall-preview --root <destination>
```

Branch on its status:

- `ACTIVE`: show every deletion, creation, transient file, and retained path plus `directories_removed: false`. In particular, both `filesystem_deletes` and `filesystem_creates` include `.agent-team/.host-lifecycle.json.stage`, and `transient_files` identifies that same path: uninstall may create and delete this scratch while transitioning state, but success leaves it absent. Obtain a separate human process confirmation, then run `./agent-team host uninstall --root <destination> --digest <exact-proposal-digest>`. State that the CLI does not persist or authenticate that approval.
- `UNINSTALLING`: validate the remaining scope and resume `host uninstall` directly with the same exact digest. Its delete/create lists and `transient_files` likewise include the metadata scratch because recovery may create and delete it.
- `ALREADY_UNINSTALLED`: treat the tombstone as completed evidence; its delete/create/transient lists are empty, and same-digest replay is optional and idempotent.
- `LEGACY_UNBOUND`: its delete/create/transient lists are empty. Do not call destructive uninstall; reconcile the old v0.9 files and ownership manually.

Remove only immediately rechecked, unchanged Factory-owned files and manage only the exact declared metadata scratch. Preserve user configuration, memories, sessions, credentials, channels, existing Skills, boards, projects, unrelated Agents, similarly named hidden files, and every directory. Empty directories may remain. Retain the persistent empty guard and digest-bound tombstone; require the scratch to be absent after success so same-digest replay cannot touch newly created user files.

Stop on missing ownership evidence, drift that obscures ownership, or any target outside the recorded scope.
