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
6. Use `host plan` with the locked team, exact target, destination, and a new plan path; run `host preview`. Prefer a new destination. In an existing directory, preserve unrelated content; require all first-apply projected files, deterministic file stages, the fixed metadata scratch, and every `.host-apply.intent-` prefix entry to be absent at planning, and require any prior tombstone to match the plan baseline. The plan binds one random exact empty intent used only to make the first metadata transition recoverable. Only the same confirmed plan may recover that exact intent, and only an exact same-proposal `APPLYING` lock permits file-stage recovery. An exact empty guard without a lock may be reused without granting deletion authority.

Show schema `1.1.0`, source lock, complete descriptor/version, destination, every artifact and deterministic file stage, fixed metadata scratch `.agent-team/.host-lifecycle.json.stage`, exact random empty intent `.agent-team/.host-apply.intent-<32-hex>`, persistent `empty-regular-file-v1` guard and empty-content digest, install record, tombstone, expected prior guard/tombstone identities, any exact prior-tombstone deletion, effects, retention, `directories_removed: false`, evidence tier, limitations, digest, verification, and uninstall scope. Distinguish transient `filesystem_deletes` from `persistent_filesystem_deletes`. Explain that lock `1.1.0` preserves the complete proposal and exact guard binding. Explain all untouched lookalike hidden files, accounts, bindings, credentials, project files, and external systems. Stop for exact confirmation. Rebuild, preview, and reconfirm every unexecuted v0.9 plan; its approval is incompatible.

## Apply and verify

After confirmation, run the current plan's `host confirm` and `host apply`, then `./agent-team host verify --root <destination>`. Complete collision checks, create only the exact plan-bound empty intent, durably write `APPLYING`, remove that intent, and create only absent projected files. If a crash leaves the exact intent or metadata stage before `APPLYING`, only the same confirmed plan may validate and resume it; if it leaves the complete exact `APPLYING` lock, validate or rebuild deterministic file stages and resume. Persistently delete only an exact prior tombstone disclosed by the newly confirmed plan. Refuse stale digests, changed tombstone baselines, unsafe guards, source drift, symlink crossings, every unrelated/pre-existing intent or stage, different lock, concurrent lifecycle processes, or artifacts outside the plan. Preserve unrelated destination content.

Treat the guard as a persistent `empty-regular-file-v1` with the empty-content digest. A precise empty guard without an install lock can be reused after the guard-fsync crash window, but it is never deleted and grants no deletion authority. POSIX `fcntl` serializes cooperating local Factory commands only; it does not defend against root, the kernel, filesystem/storage compromise, or another privileged writer. Treat `LEGACY_UNBOUND` verification as read-only v0.9 compatibility; automatic apply and destructive uninstall remain disabled pending manual reconciliation.

For OpenClaw and Hermes, use isolated state/home directories for CLI validation. Do not bind live channels or overwrite real profiles. For Multica `v0.4.23`, materialize the `experimental-plan` package only; never execute its proposed workspace writes. Treat Leda as `research-unknown`.

Report managed paths, evidence tier, checks passed/failed/skipped, observed external writes, credentials accessed, limitations, and uninstall boundary. Do not equate generation with host load or isolated validation with live support.

## Uninstall

Run the read-only `./agent-team host uninstall-preview --root <destination>` first. For `ACTIVE`, show the exact scope and explain that `filesystem_deletes`, `filesystem_creates`, and `transient_files` identify `.agent-team/.host-lifecycle.json.stage` plus every declared per-file quarantine stage; uninstall may create/delete these paths and success leaves all absent. Show retained paths and `directories_removed: false`, obtain a separate human process confirmation, and then use `host uninstall` with the exact proposal digest; disclose that the CLI stores no authenticated approval. For `UNINSTALLING`, the same three fields identify whichever metadata/quarantine stages remain possible; validate and resume directly with the same digest. For `ALREADY_UNINSTALLED` and `LEGACY_UNBOUND`, those three lists are empty; same-digest replay is optional and idempotent for the former, while the latter requires manual ownership reconciliation and forbids automatic uninstall.

Remove only a Factory file whose digest, size, device and inode match the install lock. Hard-link that exact inode to its declared quarantine stage before persisting/removing it; preserve a byte-identical file recreated at the original path. Preserve all user data, unrelated/lookalike hidden content, and every directory; empty directories may remain. Retain the persistent empty guard and digest-bound tombstone; require all scratch paths absent after success. Stop when ownership is ambiguous or managed files drifted.
