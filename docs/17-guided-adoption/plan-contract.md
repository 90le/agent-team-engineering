# Guided adoption plan contract

The plan is the machine-readable boundary between natural-language guidance and deterministic generation. Its schema is [`schemas/guided-adoption-plan.schema.json`](../../schemas/guided-adoption-plan.schema.json).

## States

| State | Allowed operations | Meaning |
|---|---|---|
| `DRAFT` | validate, preview, replace with a new plan | No creation authority exists |
| `CONFIRMED` | validate, preview, apply once to the named absent path | Local owner confirmed the exact proposal digest for team creation only |

There is no “implicitly approved” state. `apply` refuses a draft.

## Proposal content

The digest covers the complete `proposal` object:

- read-only discovery and source Git identity;
- user purpose, goals, coordination level, platforms and custom roles;
- recommended internal mapping, plain-language explanation, reasons, alternative and limitations;
- team/project identity, owner, branch, summary and exact output path;
- fixed false external effects and separate-export requirement;
- known unknowns.

`plan_id` is derived from the same canonical proposal digest. Editing any proposal field invalidates both identity and confirmation.

## Confirmation semantics

`onboard confirm` requires the exact displayed `sha256:` digest and stores:

- the same proposal digest;
- a human display name;
- scope `create-new-team-directory-only`;
- an exact local confirmation statement.

This is a local creation boundary, not remote authentication and not production approval. It cannot authorize target-project mutation, credentials, external providers, merge, release, or deployment.

## Apply checks

Before generation, `onboard apply` verifies:

- strict schema and duplicate-key-safe JSON parsing;
- absence of inline credential-like material;
- proposal digest, plan identity and confirmation binding;
- supported purpose/automation mapping;
- absolute paths outside the Factory and target project;
- safe Git branch syntax;
- unchanged source commit when a Git commit was discovered;
- absent, non-symbolic output.

The compiler then generates into a staging directory, validates design and every lock, and publishes atomically to the absent output path. A second apply refuses overwrite.

## Portability and resume

The plan contains absolute local paths because it binds an actual creation operation. Another AI on the same device can validate, preview and resume it without chat history. After migration to another device, create a new plan so source and output paths, Git identity and confirmation reflect the new environment.

The generated team itself is portable. Its context and role contracts do not depend on the plan file remaining at the original path.
