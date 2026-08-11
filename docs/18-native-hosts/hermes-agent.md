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
- preserve unrelated destination content and refuse any planned-path collision or different install lock;
- require a new plan when a profile name or destination changes;
- remove only Factory-owned artifacts on uninstall.

## Optional swarm use

Treat a generated swarm plan as an operator-reviewed template. Before executing it, separately decide:

- exact project and task scope;
- worker, verifier, and synthesizer profile separation;
- model/tool/cost policy;
- repository worktree and external-write policy;
- idempotency and durable evidence;
- stop, retry, and human escalation conditions.

Do not equate multiple profiles with safe multi-Agent autonomy. Independence, authority, isolation, and evidence still require explicit controls.
