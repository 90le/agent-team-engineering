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

Prefer a new destination. An existing directory is allowed only when unrelated content can be preserved, every projected target, deterministic stage and exact per-file ownership intent is absent, fixed metadata scratch and reserved metadata/initial-intent prefixes are absent at planning, and any prior tombstone matches the plan. After durable `APPLYING`, each file is published only from its random plan-bound intent inode through hard links to stage/target; that intent remains until `ACTIVE` records the same target inode. Only this same-inode evidence may resume or be cleaned. An empty guard without a lock may be reused only when no initial intent or metadata scratch remains; a pre-`APPLYING` intent residue is preserved and requires reconciliation plus a new plan. The guard grants no deletion authority. Refuse every other collision or lock:

```bash
./agent-team host plan \
  --team /path/to/locked-team \
  --target <host-id> \
  --destination /new/path/host-team \
  --output /new/path/host-install-plan.json
./agent-team host preview --plan /new/path/host-install-plan.json
```

Show schema `1.1.0`, source/descriptor authority, destination, every artifact, deterministic `stage_path`, random per-file `intent_path`, fixed metadata stage, exact metadata intent, random empty initial-apply intent, empty guard/digest, lock/tombstone, prior identities, effects, retained files, directory rule, evidence tier, limitations, digest and uninstall scope. Distinguish transient intent/stage cleanup from persistent exact tombstone removal. Explain that `ACTIVE` lock records exact target inode bindings. State which lookalike hidden files, accounts, credentials, channels, repositories and external systems remain untouched.

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

On first apply, finish collision checks before creating any intent. Durably write `APPLYING`; publish each file only through its exact random intent inode; persist `ACTIVE` with target inode bindings before cleaning per-file intents. Recover only same-inode intent/stage/target state; never adopt an unrelated byte-identical file. Metadata transitions require their exact metadata intent. Persistently delete a prior tombstone only when the new confirmed plan bound it. Verification rejects every leftover intent/stage. Preserve unrelated content and fail closed on lifecycle drift, unsafe guard, different lock, concurrent process, symlink, source drift, or stale digest.

Treat the persistent operation guard as an exact empty regular file with the `empty-regular-file-v1` format and empty-content digest. A precise empty guard without an install lock may be reused only when no initial intent or metadata scratch remains. If the initial intent exists without a durable exact `APPLYING` record, preserve it, stop, reconcile the destination, and build a new plan. Never delete the guard or infer file-deletion authority from it. POSIX `fcntl` covers cooperating local Factory commands only, not root, the kernel, filesystem/storage compromise, or another privileged writer.

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

- `ACTIVE`: show every deletion, creation, transient file, and retained path plus `directories_removed: false`. Both effect lists include `.agent-team/.host-lifecycle.json.stage` and every declared per-file quarantine stage; `transient_files` identifies them because uninstall may create/delete these paths and must leave all absent. Obtain a separate human process confirmation, then run `./agent-team host uninstall --root <destination> --digest <exact-proposal-digest>`. State that the CLI does not persist or authenticate that approval.
- `UNINSTALLING`: validate the remaining scope and resume `host uninstall` directly with the same exact digest. Its delete/create lists and `transient_files` identify whichever metadata/quarantine stages remain possible in the durable state.
- `ALREADY_UNINSTALLED`: treat the tombstone as completed evidence; its delete/create/transient lists are empty, and same-digest replay is optional and idempotent.
- `LEGACY_UNBOUND`: its delete/create/transient lists are empty. Do not call destructive uninstall; reconcile the old v0.9 files and ownership manually.

Remove only a Factory file whose digest, size, device and inode match the install lock. First hard-link that exact inode to its declared quarantine stage, persist progress, then unlink the original name. Preserve a byte-identical file recreated at the original path, plus user configuration, memories, sessions, credentials, channels, existing Skills, boards, projects, unrelated Agents, similarly named hidden files, and every directory. Empty directories may remain. Retain the persistent empty guard and digest-bound tombstone; require every metadata/quarantine scratch to be absent after success.

Stop on missing ownership evidence, drift that obscures ownership, or any target outside the recorded scope.
