# Hermes Agent native-team boundary

Official upstream: [NousResearch/Hermes-Agent](https://github.com/NousResearch/Hermes-Agent).

## Native projection

Hermes Agent has native concepts that map naturally to a portable team:

| Portable authority | Hermes-native projection |
|---|---|
| Role | Named profile distribution |
| Role behavior and boundary | Profile `SOUL.md` and distribution description |
| Reusable procedure | Profile-local Skill |
| Team/project scope | Hermes project plan |
| Coordinated durable work | Optional Kanban/swarm plan |
| Independent review | Separate verifier profile |

A generated package may therefore contain per-role profile distributions, `SOUL.md`, Skills, a team/project descriptor, a Skill bundle plan, and a reviewable Kanban/swarm command plan.

The Kanban plan describes coordination; generating it does not execute workers, select paid models, or prove a verifier independently reviewed a real result.

## Safe lifecycle

```bash
./agent-team host probe --target hermes
./agent-team host plan \
  --team /path/to/locked-team \
  --target hermes \
  --destination /new/path/hermes-team \
  --output /new/path/hermes-install-plan.json
./agent-team host preview --plan /new/path/hermes-install-plan.json
```

Probe reads executable identity/version only. It must not inspect the real Hermes home, memories, sessions, authentication, `.env`, user profiles, boards, or logs.

The `native-install-verified` evidence for Hermes Agent `0.20.0` comes from a disposable isolated home: the generated profile distribution passed profile install/list/describe/delete. No model or credential was used. It therefore proves the named install lifecycle, but not task execution, Kanban workers, a real user profile, or production behavior, and does not qualify as `native-verified`.

## Ownership and user data

Hermes profile distributions intentionally separate distribution-owned files from user-owned memory and state. The Factory must preserve the same boundary:

- manage only artifacts listed in the exact install record;
- never claim ownership of memories, sessions, authentication, `.env`, logs, or existing boards;
- follow the [common v1 lifecycle](README.md): bind the complete proposal, persistent empty guard, deterministic file stages, fixed metadata scratch, prior lifecycle state, effects, and digest;
- preserve unrelated destination content; require absent projected files/file stages on first apply, allow their recovery only for an exact same-proposal `APPLYING` lock, and never create, replace, or delete a temporary path other than the declared scratch;
- require a new plan when a profile name or destination changes;
- rebuild and reconfirm every unexecuted v0.9 plan; treat v0.9 locks as `LEGACY_UNBOUND` read-only records with automatic uninstall disabled;
- run `host uninstall-preview` first; for `ACTIVE`/`UNINSTALLING`, explain that its delete/create lists and `transient_files` include the scratch, while those lists are empty for `ALREADY_UNINSTALLED`/`LEGACY_UNBOUND`; obtain human process confirmation for `ACTIVE`, and remove only immediately rechecked Factory-owned files with the exact digest;
- retain the empty guard/tombstone and every directory, require scratch absence after success, and allow empty directories to remain after uninstall.

## Optional swarm use

Treat a generated swarm plan as an operator-reviewed template. Before executing it, separately decide:

- exact project and task scope;
- worker, verifier, and synthesizer profile separation;
- model/tool/cost policy;
- repository worktree and external-write policy;
- idempotency and durable evidence;
- stop, retry, and human escalation conditions.

Do not equate multiple profiles with safe multi-Agent autonomy. Independence, authority, isolation, and evidence still require explicit controls.
