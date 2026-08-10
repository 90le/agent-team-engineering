---
name: upgrade-agent-team-instance
description: Plan, apply, recover, verify, or roll back a versioned Agent Team instance with the agent-team-engineering Factory. Use when moving an existing instance between supported Factory releases, handling an interrupted lifecycle journal, inspecting an external recovery bundle, or returning to a previous release. Requires an exact verified Factory release, stopped workers, a quiescent runtime, human review of the digest-bound plan, and recovery material outside the instance; never use relock as an upgrade or delete a journal manually.
---

# Upgrade an Agent Team Instance

Read the Factory `AI-BOOTSTRAP.md`, `docs/08-factory/instance-lifecycle.md`, `docs/11-lifecycle/installation-upgrade-and-adoption.md`, and `docs/03-security/threat-model.md`. Read the target instance `AI-BOOTSTRAP.md`, `.agent-team/instance.json`, and `.agent-team/instance.lock.json` completely. Use `manage-agent-team-factory` for ordinary instance changes and runtime governance; this Skill owns only installation-version transitions and their recovery.

## Establish authority and stop work

1. Obtain human-owner approval for the exact instance path, source and target Factory versions, maintenance window, recovery location, and rollback intent. Planning and inspection are read-only; apply, recovery, rollback, worker stop, and runtime pause are state changes.
2. Stop every scheduler, worker, adapter host, and process that can write the instance or its runtime database. A paused database does not prove those processes have stopped.
3. If runtime state exists, pause it through the governed runtime command, reconcile expired leases and claimed effects, and require zero active leases and zero pending, failed, or claimed outbox effects. Verify the audit chain. If state is absent, record that fact instead of creating it for an upgrade.
4. Run `python3 tools/agent_team.py doctor --instance <instance>` and `instance validate`. Stop on an error, managed-file drift, an existing lifecycle journal, a secret finding, a newer instance version, or unverifiable authority.

## Plan and apply

1. Run only from an exact, clean, annotated Factory release or a verified Factory installation. Never apply from a development checkout, dirty tree, lightweight tag, or copied directory without `.factory-installation.json` verification.
2. Write the plan outside the instance:

   `python3 tools/agent_team.py instance upgrade plan --root <instance> --output <external-plan.json>`

3. Have the human owner review the bound instance path and ID, source and target versions, source and target lock digests, every create/replace/remove action, and every preserved seeded file. Regenerate rather than edit a stale plan.
4. Choose an absent recovery-bundle path outside the instance, preferably on an independently backed-up failure domain. Do not keep the only recovery copy beside the instance on the same disposable disk.
5. Apply the reviewed plan:

   `python3 tools/agent_team.py instance upgrade apply --root <instance> --plan <external-plan.json> --recovery <external-recovery-dir>`

6. The Factory changes managed files one at a time and commits the target lock last. This is logical fail-closed atomicity, not a filesystem-wide atomic directory swap. Keep the workers stopped until instance validation, Doctor, runtime status, and audit verification all pass.
7. Preserve the plan, recovery bundle, command result, validation evidence, source and target revisions, and human decision in the instance evidence history. Resume runtime and workers only with an explicit recorded owner decision.

## Recover an interrupted operation

Treat `runtime/.factory-lifecycle-journal.json` as the sole crash-recovery authority. Do not edit, move, relock around, or delete it.

1. Keep every writer stopped and inspect the journal without exposing secret values.
2. Verify the external bundle referenced by the journal with `instance recovery-inspect --bundle <path>`.
3. Run `python3 tools/agent_team.py instance recover --root <instance>`. The same command recovers an interrupted upgrade to its source release or an interrupted rollback to its pre-rollback release.
4. Run instance validation and Doctor, verify runtime audit/status, and retain the journal-recovery evidence. Escalate to the owner if the bundle is missing, tampered, belongs to another instance, or current files contain post-transition drift; do not improvise an overwrite.

## Roll back deliberately

1. Use only the verified recovery bundle produced by the corresponding successful upgrade. Inspect it first and confirm the current lock equals its expected target lock.
2. Stop writers and quiesce runtime exactly as for upgrade.
3. Select a new absent external path for a rescue bundle of the current release. The rescue makes rollback reversible.
4. Run `python3 tools/agent_team.py instance rollback --root <instance> --recovery <original-recovery-dir> --rescue <new-rescue-dir>`.
5. Validate the restored release. Keep both the original recovery and new rescue bundles until the owner accepts the outcome and the retention policy permits disposal.

Stop without mutation if the exact release cannot be verified, `fcntl` lifecycle locking is unavailable, workers cannot be stopped, runtime cannot be proven quiescent, the plan is stale, an output path already exists, a digest or instance identity differs, external recovery storage is unavailable, or any requested action expands beyond the approved instance and version transition.
