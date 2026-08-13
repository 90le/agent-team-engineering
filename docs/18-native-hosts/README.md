# Host-native Agent Team Factory

This chapter defines how Agent Team Engineering turns one portable team authority into artifacts that an existing AI host can discover and use. It is the entry point for adopters, AI guides, host-adapter authors, and reviewers.

## Product boundary

The Factory is a **compiler and lifecycle guardrail**, not another Agent runtime.

```text
verified project facts
desired outcome
human authority boundaries
        │
        ▼
Team Intent / portable authority
  - context and source map
  - roles and handoffs
  - Skills and workflows
  - decisions and durable work
  - digest locks
        │
        ▼
Host Capability Contract
  - detectable executable/version
  - native extension surfaces
  - generated artifacts
  - supported lifecycle and limitations
        │
        ▼
Host-native projection
  - OpenClaw workspaces
  - Hermes profile distributions
  - Codex project Agents/Skills
  - Claude project subagents/Skills
  - experimental Multica plan
        │
        ▼
plan → preview → confirm → apply → verify → uninstall
```

The portable authority is the source of truth. A host package is a derived projection and must not edit roles or policies back into the authority source. Regenerate it after a reviewed source change.

The existing `adapters/` layer has a different purpose: workflow ingress, execution, SCM, notification, and external-system ports for optional Managed automation. Host-native projectors must not be confused with those runtime adapters.

## Choose the host before the mode

Use a host the adopter already operates. Read-only probe results can inform a recommendation, but absence of an executable is not permission to install one.

1. Understand the recurring outcome.
2. Inspect the project and available hosts read-only.
3. Recommend roles, Skills, context, and one primary host.
4. Decide whether on-demand native collaboration is enough.
5. Add Managed automation only when durable progression is a stated requirement.

Do not ask a first-time adopter to choose Lite, Managed, Custom, a controller, or an adapter. Explain those internal mappings only after recommending a user-facing shape.

## Two confirmations, not one

Team creation and host installation have different targets and risks.

### 1. Create the portable team

Use `onboard inspect|plan|preview|validate|confirm|apply`. Confirmation authorizes only the exact new team directory in the displayed team plan.

### 2. Project it into a host

Use the host lifecycle on a locked team:

```bash
./agent-team host list
./agent-team host probe --target <host-id>
./agent-team host plan \
  --team /path/to/locked-team \
  --target <host-id> \
  --destination /new/path/host-team \
  --output /new/path/host-install-plan.json
./agent-team host preview --plan /new/path/host-install-plan.json
```

Review the plan JSON and its human-readable preview together. They identify:

- exact source lock and complete host descriptor digest;
- plan schema `1.1.0`, destination, every projected artifact, deterministic `stage_path`, random per-file `intent_path`, fixed metadata stage `.agent-team/.host-lifecycle.json.stage`, exact metadata intent, and random empty initial-apply intent `.agent-team/.host-apply.intent-<32-hex>`;
- the persistent `empty-regular-file-v1` operation guard and empty-content digest, install record, uninstall tombstone, and retained files;
- exact expected prior guard/tombstone identities and whether apply will delete that exact prior tombstone;
- host descriptor version, evidence tier, and any separate read-only probe result;
- filesystem write/delete effects, including `filesystem_deletes: true` for transient scratch management and `persistent_filesystem_deletes` for exact prior-tombstone removal, plus directory behavior, merge, credentials, bindings, and network behavior;
- known unsupported capabilities;
- digest, verification, and uninstall scope.

Only an exact confirmation may unlock `host apply`. The plan digest binds the complete proposal, and the `1.1.0` install lock copies that proposal plus the exact guard binding as durable ownership authority. Changing the source, target, destination, descriptor, artifact/stage set, prior lifecycle baseline, or effect invalidates the digest.

Planning rejects the fixed metadata stage plus reserved metadata/initial-intent prefixes. First apply also requires every projected target, deterministic stage, and exact per-file intent absent. After `APPLYING` is durable, each projected file is published from one random plan-bound intent inode through hard links to its stage/target. The intent remains until `ACTIVE` records the same target inode, then is removed. Recovery proves same-inode ownership; an unrelated byte-identical target/stage is preserved and rejected. Metadata transitions use a separately bound exact intent. A persistent deletion remains limited to the exact prior tombstone displayed and confirmed by a new plan. Every other collision, lifecycle drift, unsafe guard, symlink, different lock, source drift, digest mismatch, or concurrent operation fails closed.

Each deterministic stage and random per-file intent is proposal-bound. A crash after durable `APPLYING` but before `ACTIVE` resumes only from the exact intent inode; a crash after `ACTIVE` can finish deleting only intents whose binding equals the recorded target. The initial empty intent authorizes only the first metadata transition and grants no general delete authority. If that intent remains without a durable exact `APPLYING` lock, it is preserved and refused; reconcile it and create a new plan. An exact empty guard without a lock may be reused only when no initial intent or metadata scratch remains, is never deleted, and grants no deletion authority. Verification rejects every leftover per-file/metadata/initial intent or stage.

Host lifecycle mutation requires POSIX `fcntl`. `.agent-team/.host-lifecycle.guard` serializes cooperating local Factory processes, and v1 verification joins the same lock. This boundary does not protect against root, the kernel, filesystem or storage compromise, or an unrelated privileged writer.

Plan schema `1.1.0` is intentionally not approval-compatible with an unexecuted v0.9 `1.0.0` plan: regenerate it, preview the new effects, and confirm the new digest. A v0.9 `1.0.0` install lock lacks the complete proposal and guard binding. `host verify` reports it as `LEGACY_UNBOUND` for read-only verification only; automatic apply and destructive uninstall are disabled. Ownership must be reconciled manually rather than inferred.

Preview removal before any mutation:

```bash
./agent-team host uninstall-preview --root /path/to/host-team
```

The result is state-specific:

- `ACTIVE` shows the exact managed-file and lock deletions, tombstone creation, retained empty guard/tombstone, and `directories_removed: false`. `filesystem_deletes`, `filesystem_creates`, and `transient_files` identify the fixed metadata scratch and every per-file quarantine stage that may be used; success leaves all absent. Obtain a separate human process confirmation, then pass the exact proposal digest to `host uninstall`. The CLI does not persist or authenticate that approval.
- `UNINSTALLING` means the already-started state machine was interrupted. Its three scope lists identify the metadata/quarantine paths still possible in the durable state. Revalidate the preview and resume `host uninstall` directly with the exact digest; no new approval record can be reconstructed by the CLI.
- `ALREADY_UNINSTALLED` is a read-only tombstone replay preview. Its delete/create/transient lists are empty; repeating `host uninstall` with the same digest returns the idempotent status without new deletion.
- `LEGACY_UNBOUND` has empty delete/create/transient lists and requires manual reconciliation; do not call automatic uninstall.

Current uninstall transitions `ACTIVE → UNINSTALLING → UNINSTALLED`, binds each installed file's digest/size/device/inode, hard-links that exact inode to its declared quarantine stage, and can resume after interruption. A byte-identical file recreated at the original path is preserved. Successful completion leaves every metadata/quarantine scratch absent. It never removes directories, because a file-only record cannot prove who created an otherwise empty parent directory. Empty directories may therefore remain. It retains the persistent empty guard and `.agent-team/host-uninstall.tombstone.json` as replay evidence. None of this permits removal of user-managed host configuration, workspaces, sessions, Skills, credentials, similarly named hidden files, or project files.

## Evidence, not marketing labels

Every host claim must use the vocabulary defined in the [support matrix](support-matrix.md). At minimum distinguish:

1. a descriptor exists;
2. files were generated;
3. files passed structural validation;
4. an isolated compatible host CLI loaded or inspected them;
5. a real authenticated workspace, channel, or task ran;
6. production behavior was observed.

A lower step never implies a higher one. In particular, local CLI smoke tests do not prove authenticated accounts, channel routing, cloud workspaces, model quality, or production safety.

## Authority and security rules

- The human owner is outside the generated Agent roster.
- Host detection reads executable identity and version only; it must not read tokens, sessions, message history, credentials, or private runtime state.
- Generated instructions request behavior but never grant tools, credentials, approval identity, repository permission, or production authority.
- Skills copied from a project, URL, registry, or upstream runtime are untrusted until reviewed.
- No install plan may silently merge an existing `AGENTS.md`, `CLAUDE.md`, `.codex/`, `.claude/`, OpenClaw config, Hermes home, or Multica workspace.
- Live channel bindings, external writes, merge, release, and deployment require separate identities, policies, evidence, approval, and recovery.

## Host guides

- [Support and evidence matrix](support-matrix.md)
- [Human/AI conversation workflow](conversation-workflow.md)
- [OpenClaw boundary](openclaw.md)
- [Hermes Agent boundary](hermes-agent.md)
- [Multica experimental plan](multica.md)

Only OpenClaw, Hermes Agent, and Multica currently need dedicated host pages. Codex, Claude Code, and Generic AI adopters must use this architecture chapter, the support matrix, the conversation workflow, and the exact `hosts/<host-id>/host.json` descriptor. The absence of a dedicated page is not evidence for a stronger support tier and must not be filled by guessed host behavior.

For the governing decisions, read [ADR-0011](../adr/ADR-0011-host-capability-contract-and-native-team-projection.md) and [ADR-0012](../adr/ADR-0012-concurrent-host-lifecycle-and-replay-safe-uninstall.md).
