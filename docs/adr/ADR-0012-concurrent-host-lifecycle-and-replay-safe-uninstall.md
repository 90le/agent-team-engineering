# ADR-0012: Concurrent host lifecycle and replay-safe uninstall

- Status: Accepted for v1 development
- Date: 2026-08-12
- Decision owners: Agent Team Engineering maintainers
- Supersedes: none
- Extends: ADR-0006, ADR-0011

## Context

The v0.9 host lifecycle binds a confirmed proposal to source and destination digests, publishes files without overwriting an existing path, and resumes an interrupted apply. That prevents ordinary stale-plan and collision failures, but it does not by itself serialize two local Factory processes. It also validates a source before a later read, and an uninstall verifies all files before later unlink calls. Those gaps leave bounded time-of-check/time-of-use races.

An uninstall can also stop after deleting some files. Without an explicit transition and durable completion record, a retry sees an `ACTIVE` record with missing files and cannot safely distinguish an interrupted removal from unexplained drift.

## Decision

Use a persistent POSIX `fcntl` guard for every mutating v1 host lifecycle operation. New v1 installations atomically create `.agent-team/.host-lifecycle.guard` as an `empty-regular-file-v1`; the plan displays its empty-content digest. Apply and uninstall acquire an exclusive, non-blocking kernel lock; v1 verification joins the same lock. If no install lock exists, an exact empty regular guard may be reused after a crash between guard fsync and `APPLYING` publication. Reuse never deletes the guard and the guard alone grants no authority to delete any file.

Plan schema `1.1.0` digest-binds the complete proposal: team and descriptor authority, destination, projected files, deterministic file stages and random per-file ownership intents, the empty guard contract, install/tombstone paths, fixed metadata scratch `.agent-team/.host-lifecycle.json.stage` and exact metadata intent, exact prior guard/tombstone identities, effects, retention, directory behavior, and limitations. Lock schema `1.1.0` stores the complete proposal and exact guard binding in addition to the derived managed-file list.

`filesystem_deletes` is always true because apply removes its exact plan-bound empty intent and apply/uninstall may rebuild and remove the declared metadata scratch during crash recovery. `persistent_filesystem_deletes` is true only when the new plan binds and confirms removal of an exact prior tombstone. The lifecycle may never delete the guard, infer delete authority from an unbound empty guard, adopt a pre-existing intent/scratch, or touch another similarly named hidden file. Any prior-tombstone baseline change fails closed.

Every source file is opened through no-follow directory descriptors and its bytes are checked against the proposal immediately before publication. Each deterministic stage is paired with a random per-file intent whose exact path is digest-bound by the plan. After `APPLYING` is durable, the implementation exclusively creates and fsyncs the intent, hard-links that inode to the stage and target, removes the stage, and retains the intent until an `ACTIVE` lock records the target digest/size/device/inode. It then removes only an intent with that exact binding. A crash before `ACTIVE` can resume through the same intent inode; a crash after `ACTIVE` can finish exact intent cleanup. A stage or target with equal bytes but no same-inode plan intent is unrelated content and is preserved with a fail-closed error.

Lifecycle JSON transitions likewise use one exact plan-bound metadata intent. The fixed scratch must be the same inode as that intent before it can be rewritten or renamed; a pre-existing unbound scratch or intent is preserved and refused. Successful apply/verify require metadata intent/scratch, all per-file intents/stages, and the initial-apply intent to be absent. Successful uninstall requires its metadata scratch/intent and quarantine stages absent. Verification uses the same no-follow descriptor and inode bindings.

Uninstall follows this state machine:

```text
ACTIVE → UNINSTALLING → UNINSTALLED tombstone
```

`host uninstall-preview` is the only read-only exact removal-scope inspection. For both `ACTIVE` and `UNINSTALLING`, `filesystem_deletes`, `filesystem_creates`, and `transient_files` identify the fixed metadata scratch plus every per-file quarantine stage that the current durable state may create or remove; successful completion leaves all of them absent. For `ACTIVE`, the preview also lists every managed-file/install-lock deletion, tombstone creation, retained empty guard/tombstone, and `directories_removed: false`. A human must confirm that process before the exact digest is passed to `host uninstall`. The CLI deliberately stores no authenticated uninstall-approval assertion. `UNINSTALLING` means an already-started removal can be validated and resumed directly with that digest. `ALREADY_UNINSTALLED` and `LEGACY_UNBOUND` return empty delete/create/transient lists; completed same-digest replay is idempotent, while legacy ownership requires manual reconciliation.

The `ACTIVE` lock records each installed file's digest, size, device and inode. Before removal, the implementation reopens the regular file without following symlinks, proves that full binding, hard-links the exact inode to its proposal-declared quarantine stage, and persists `QUARANTINED` before unlinking the original name. It then persists `REMOVED` before deleting the quarantine link. A crash can resume from each state; a byte-identical file recreated at the original path has another inode and is preserved. Directories are never removed because the file-only ownership record cannot distinguish a Factory-created directory from a pre-existing empty user directory; empty directories may remain. After all owned files are absent, it writes `.agent-team/host-uninstall.tombstone.json` and removes the install record. Replaying the same uninstall digest returns `ALREADY_UNINSTALLED`; another digest fails closed.

A v0.9 unexecuted plan schema `1.0.0` must be regenerated, previewed, and confirmed because its approval did not bind the v1 metadata and effects. A separate legacy schema may parse a v0.9 `1.0.0` install lock for `LEGACY_UNBOUND` read-only verification, but that record lacks complete proposal-bound ownership. Automatic apply and destructive uninstall are disabled; an operator must reconcile ownership manually rather than having v1 infer it.

The empty operation guard and uninstall tombstone are the two persistent files remaining after uninstall. The metadata scratch is absent, though empty directories may remain. These files are small lifecycle evidence, not host configuration, credentials, runtime state, or live activation. A later install plan may remove only the exact prior tombstone whose full identity and persistent delete effect it displays and binds into a new confirmation. It preserves or reuses the empty guard; there is no implicit history purge.

## Security boundary

The guard serializes cooperating local Factory commands. No portable userspace protocol can atomically compare an inode and unlink it against a hostile privileged process on every supported POSIX filesystem. Directory file descriptors, no-follow opens, digest checks, inode comparison, exclusive publication, and kernel locking narrow the race; they do not claim protection from root, kernel, filesystem, or storage compromise. Operators must not let unrelated privileged tools mutate a destination during apply or uninstall.

## Consequences

### Positive

- Competing plans cannot both enter a lifecycle mutation.
- Late source drift cannot be published even after initial validation passed.
- Destination publication remains non-overwriting at the kernel operation.
- Interrupted uninstall is resumable and completion replay is idempotent.
- Persistent effects are visible before confirmation and bound into the proposal digest.
- An exact empty guard supports recovery across the guard-fsync/lock-publication crash window without granting deletion authority.
- Exact metadata and per-file ownership intents make JSON and projected-file recovery possible without adopting pre-existing or merely byte-identical content.

### Costs

- Host lifecycle mutation requires POSIX `fcntl`, matching the existing instance lifecycle requirement.
- Two small metadata files remain after uninstall, and the transient metadata scratch must be absent.
- v0.9 unexecuted host plans require replanning under schema `1.1.0`.
- v0.9 install locks cannot use automatic destructive uninstall and require manual reconciliation.
- A non-cooperating privileged filesystem writer remains outside the guarantee.

## Rejected alternatives

### Lock only the replaceable JSON install record

Rejected because atomic JSON replacement changes the inode. A waiter on the old inode and a new opener on the replacement could both believe they hold the authoritative lock.

### Delete the guard after every operation

Rejected because unlinking a lock file while waiters may hold its old inode can split synchronization across two inodes.

### Silently create internal metadata outside the plan

Rejected because host installation approval must disclose every persistent destination effect.

### Treat partial uninstall as unexplained drift

Rejected because it prevents deterministic recovery after an ordinary crash between owned-file deletions.

## Acceptance

- concurrent different-plan apply fails before a second mutation;
- source mutation after initial validation fails before publication;
- the plan and lock bind the complete proposal, empty guard contract/binding, every random per-file intent and deterministic stage, fixed metadata scratch and exact metadata intent, random initial-apply intent, prior tombstone, and delete effects;
- planning rejects any metadata scratch or `.host-apply.intent-` prefix entry; after confirmation and collision checks, apply creates one exact plan-bound empty intent and only the same plan may use it to recover the first metadata transition;
- apply remains resumable only for exact same-plan intent/stage/target inode bindings under `APPLYING`, or exact intent cleanup recorded by `ACTIVE`; byte equality alone never grants ownership;
- an exact empty guard without an install lock can be reused but cannot authorize any deletion;
- apply may remove only exact plan-bound initial, metadata, and per-file intents plus their same-inode stages; every unrelated/pre-existing collision is preserved and rejected, and success leaves no transient path;
- uninstall rechecks content and identity immediately before removal;
- uninstall preview is read-only and distinguishes `ACTIVE`, `UNINSTALLING`, `ALREADY_UNINSTALLED`, and `LEGACY_UNBOUND`; the first two expose the scratch in delete/create/transient lists while the latter two expose empty lists;
- `ACTIVE` removal requires human process confirmation and the exact digest while the CLI records no authenticated approval;
- interrupted uninstall resumes from `UNINSTALLING`;
- replay of the exact completed digest reports `ALREADY_UNINSTALLED`;
- legacy v0.9 locks remain read-only verifiable and cannot enter automatic destructive uninstall;
- plans preview the empty guard format/digest, install record, tombstone, deterministic file stages, fixed metadata scratch, exact prior state, transient versus persistent delete effects, retention, no-directory-removal rule, and POSIX lock boundary;
- documentation does not claim protection from hostile privileged mutation.

## References

- [ADR-0006](ADR-0006-verified-install-and-transactional-instance-lifecycle.md)
- [ADR-0011](ADR-0011-host-capability-contract-and-native-team-projection.md)
- [Native-host lifecycle](../18-native-hosts/README.md)
- [GitHub issue #14](https://github.com/90le/agent-team-engineering/issues/14)
