---
name: manage-agent-team-factory
description: Create, inspect, validate, relock, run, pause, back up, restore, upgrade, recover, or hand over a portable Agent Team instance using the agent-team-engineering Factory. Use for team-instance manifests, Factory/instance/target-repository boundaries, version locks, persistent control-plane state, leases, idempotency, outbox recovery, audit verification, generated-file drift, safe bootstrap, cross-AI transfer, or preparation for binding GitHub, OpenClaw, models, runners, and deployment adapters.
---

# Manage Agent Team Factory

Read the Factory `AI-BOOTSTRAP.md`, constitution, threat model, `factory-package.json`, and `docs/08-factory/instance-lifecycle.md`. For runtime or recovery work, also read `docs/09-control-plane/persistence-and-recovery.md`. When an instance exists, read its `AI-BOOTSTRAP.md`, `.agent-team/instance.json`, and `.agent-team/instance.lock.json` completely.

## Establish the boundary

1. Treat the Factory repository as generic implementation and migration authority.
2. Treat the instance repository as non-secret configuration, version binding, policy, operations, and evidence authority.
3. Treat each target repository as product, architecture, source, test, and release authority.
4. Treat workflow databases, Runner workspaces, artifacts, and secrets as external runtime state. Never add them to ordinary Git.

## Create an instance

1. Start from `examples/team-instance/input/instance.json` and replace identity and non-secret bindings.
2. Keep the initial maximum autonomy at or below `A2`, retain human production approval, and leave external adapters disabled until separately authorized and tested.
3. Represent credentials only as opaque `secret.*` references.
4. Run `python3 tools/agent_team.py instance init --config <json> --output <new-path>`.
5. Run `instance validate` and review the generated authority, lock, Factory revision, dirty flag, contract digest, and file ownership before committing the new instance.

Initialization must target a new path outside the Factory. Never move, delete, or overwrite an existing directory to make initialization succeed.

## Change an instance

Edit only `.agent-team/instance.json` for declarative changes. Run validation, review the exact diff, then run `instance relock` and validate again. A relock accepts a validated configuration digest; it does not grant new authority, repair managed-file drift, upgrade the Factory, or enable a provider.

Treat managed-file drift as a failure. Treat seeded-file drift as a user customization warning and preserve it. Use a proposal branch and retain a recovery point for future migrations.

## Operate persistent state

Validate the instance, initialize only its configured state path, then inspect status and verify audit. Require a matching lease for every non-owner transition and a human actor for owner gates. Use stable idempotency keys derived from source identity or work item/revision/action; never invent a fresh key merely because a request timed out.

On uncertainty, activate the human-owner global pause. Reconcile expired leases and outbox claims, verify audit, compare external provider state, and resume only with a recorded reason. Create verified backups with `runtime backup`; restore only into an absent state path and keep the restored instance paused until reconciliation.

## Bind an external adapter

Require separate authorization, the exact target, a minimum-permission identity, secret-system references, a dry-run or test environment, contract tests, idempotency behavior, stop controls, and rollback. Repository access is not merge or production authority. Do not infer provider configuration from chat history.

## Stop safely

Stop without mutation when the locked Factory release is unavailable, a digest differs, a secret value is present, the instance was created by a newer Factory, managed files drifted, authority conflicts, or the requested operation expands into a real pilot or production system without explicit authorization.

Finish by running repository validation, unit and security tests, instance validation, and the clean-clone test appropriate to the changed entrypoint or contract.
