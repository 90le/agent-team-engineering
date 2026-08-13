---
name: install-agent-team-host
description: Plan, preview, confirm, apply, verify, reconcile, or uninstall a generated Agent Team package for OpenClaw, Hermes Agent, Codex, Claude Code, Multica, or generic file-capable AI. Use after a portable team exists when a person asks to adapt, install, export, load, verify, upgrade, move, or remove it in a specific AI host without overwriting user configuration or implying live account authority.
---

# Install Agent Team Host

Use only a validated team with `.agent-team/team-design.json` and `.agent-team/context.lock.json`. Team creation does not authorize host installation.

## Inspect and plan

1. Locate the stable Factory checkout used to generate the team.
2. Read its `docs/18-native-hosts/README.md` and `support-matrix.md`. Read one dedicated selected-host guide when present; OpenClaw, Hermes Agent, and Multica have pages. For Codex, Claude Code, or Generic AI, use the common guide, matrix, conversation workflow, and exact host descriptor instead of inventing a page.
3. Run `./agent-team context validate --root <team>`.
4. Run `./agent-team host list` and `./agent-team host probe --target <host-id>`.
5. Report detected version, evidence tier, limitations, and safe alternative. Do not read credentials, sessions, messages, private runtime state, or account data.
6. Use `host plan` with the locked team, exact target, destination, and a new plan path; run `host preview`. Preserve unrelated content. Require every projected target, deterministic stage and exact random per-file intent absent, plus fixed metadata scratch and reserved metadata/initial-intent prefixes absent at planning. After `APPLYING`, each file is published only from its plan-bound intent inode; the intent remains until `ACTIVE` records the same target inode. Recovery requires that same-inode evidence. An exact empty guard without a lock may be reused without granting deletion authority.

Show schema `1.1.0`, source/descriptor authority, destination, every artifact, deterministic stage and random per-file intent, fixed metadata stage and exact metadata intent, initial empty intent, guard/digest, lock/tombstone, prior identities, effects, retention, directory rule, evidence tier, limitations, digest and uninstall scope. Explain exact `ACTIVE` target inode binding, transient versus persistent deletion, and every untouched lookalike/account/external system. Stop for exact confirmation. Rebuild and reconfirm every v0.9 plan.

## Apply and verify

After confirmation, run `host confirm`, `host apply`, then `host verify`. After durable `APPLYING`, publish every file only through its random plan-bound intent inode; persist `ACTIVE` with exact target bindings before intent cleanup. Resume only same-inode intent/stage/target state and never adopt equal bytes alone. Metadata uses its separately bound exact intent. Delete only a newly confirmed exact prior tombstone. Refuse stale digests, lifecycle drift, unsafe guards, symlinks, unbound/pre-existing intents or stages, different locks, concurrent lifecycle processes, and out-of-plan artifacts.

Treat the guard as a persistent `empty-regular-file-v1` with the empty-content digest. A precise empty guard without an install lock can be reused after the guard-fsync crash window, but it is never deleted and grants no deletion authority. POSIX `fcntl` serializes cooperating local Factory commands only; it does not defend against root, the kernel, filesystem/storage compromise, or another privileged writer. Treat `LEGACY_UNBOUND` verification as read-only v0.9 compatibility; automatic apply and destructive uninstall remain disabled pending manual reconciliation.

For OpenClaw and Hermes, use isolated state/home directories for CLI validation. Do not bind live channels or overwrite real profiles. For Multica `v0.4.23`, materialize the `experimental-plan` package only; never execute its proposed workspace writes. Treat Leda as `research-unknown`.

Report managed paths, evidence tier, checks passed/failed/skipped, observed external writes, credentials accessed, limitations, and uninstall boundary. Do not equate generation with host load or isolated validation with live support.

## Uninstall

Run the read-only `./agent-team host uninstall-preview --root <destination>` first. For `ACTIVE`, show the exact scope and explain that `filesystem_deletes`, `filesystem_creates`, and `transient_files` identify `.agent-team/.host-lifecycle.json.stage` plus every declared per-file quarantine stage; uninstall may create/delete these paths and success leaves all absent. Show retained paths and `directories_removed: false`, obtain a separate human process confirmation, and then use `host uninstall` with the exact proposal digest; disclose that the CLI stores no authenticated approval. For `UNINSTALLING`, the same three fields identify whichever metadata/quarantine stages remain possible; validate and resume directly with the same digest. For `ALREADY_UNINSTALLED` and `LEGACY_UNBOUND`, those three lists are empty; same-digest replay is optional and idempotent for the former, while the latter requires manual ownership reconciliation and forbids automatic uninstall.

Remove only a Factory file whose digest, size, device and inode match the install lock. Hard-link that exact inode to its declared quarantine stage before persisting/removing it; preserve a byte-identical file recreated at the original path. Preserve all user data, unrelated/lookalike hidden content, and every directory; empty directories may remain. Retain the persistent empty guard and digest-bound tombstone; require all scratch paths absent after success. Stop when ownership is ambiguous or managed files drifted.
