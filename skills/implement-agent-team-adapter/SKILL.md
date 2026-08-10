---
name: implement-agent-team-adapter
description: Design, implement, validate, test, migrate, or review an Agent Team Factory platform adapter. Use when adding or changing messaging, GitHub or other code-hosting, AI provider, runner, deployment, notification, webhook, secret-resolver, authenticated-approval, or external-effect integration governed by adapter manifests, schemas, authority events, outbox delivery, isolation, and reconciliation.
---

# Implement Agent Team Adapter

Read `AI-BOOTSTRAP.md`, the constitution, threat model, `schemas/adapter.schema.json`, `policies/adapter-authority.json`, and `docs/10-adapters/sdk-isolation-and-approval.md`. Read the target adapter manifest and every input/output Schema it names. For an instance binding, also read its authority document and lock.

## Define the contract first

1. Give the adapter one stable `adapter.*` identity, semantic version, supported slots, a binding-config Schema, trust boundaries, logical credential kinds, and explicit operations.
2. Give every operation its allowed slots, direction, effect class, delivery strategy, capability, project scope, timeout, input Schema, and output Schema. Bind repository or runner targets to the instance project ID/locator, provider, mode, source reference, and default branch as applicable.
3. Use `provider-idempotency` only when the provider actually honors the stable key. Use `reconcile-before-retry` when a stable external marker can prove presence or absence. Use `at-most-once` with one attempt when neither guarantee exists.
4. Add a default-deny grant from a precise durable audit event in `policies/adapter-authority.json`. Never authorize an operation merely because a role prompt requested it.
5. Keep secrets as opaque `secret.*` references. Never put a credential value in a manifest, instance, request, result, exception, test fixture, log, or Git commit.

## Implement inside the host boundary

Implement the explicit `Adapter` protocol. Register the implementation in code; do not import a manifest entrypoint dynamically. Accept only the bounded request and `AdapterContext`. Resolve only secret references allowed by that instance binding.

Return a complete `adapter-result` object. Use stable, non-sensitive error codes instead of raw provider responses. Treat schema errors, secret-shaped output, unsupported operations, disabled bindings, and missing authority as permanent safe-stop failures.

For provider writes, preserve the outbox idempotency key. On uncertain retry, reconcile before a second write. Never report success without a stable external reference and provider request identifier.

## Protect inbound and approval paths

Verify webhook authentication over the original bytes before parsing JSON, use a stable authenticated delivery identifier for deduplication, enforce size limits, and convert public content only into untrusted feedback data.

Do not treat a chat message, model output, role name, or `kind=human` flag as approval. An approval adapter must authenticate the person and issue a short-lived assertion bound to the exact action, work item, revision, evidence or artifact digest. Persist only the claim digest and evidence reference, not the assertion signature or authentication secret.

## Protect execution

Runner requests use an allowlisted command identifier and argv, not a shell string. Require disposable workspace, read-only source, explicit network policy, bounded time, no privilege, no Docker Socket, and no production mounts. Keep untrusted test jobs secret-free by default. A dry-run planner is not a sandbox and must never claim to execute tests.

## Verify failure behavior

Add contract and negative tests for disabled binding, wrong slot, missing authority, malformed input, malformed or secret-bearing output, stale claim, provider success before acknowledgement, reconciliation without duplicate writes, at-most-once uncertainty, webhook tampering, approval expiry/binding/signature, secret scope, and unsafe runner configuration.

Run repository validation, all tests, official Skill validation, and the committed cold-start test. Keep real provider credentials and writes disabled until a separate instance-specific authorization supplies the exact target, minimum-permission identity, test environment, stop control, recovery path, and owner acceptance.
