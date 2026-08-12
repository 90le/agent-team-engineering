# Independent frontend/backend writer topology

Status: accepted v1.0 design authority; `DESIGN_ONLY`, with no automatic execution authority.

## What v1.0 adds

The Factory can generate native role, Skill, and context packages, while the current Managed reference runtime deliberately keeps one source-writing `builder`. The v1.0 release adds a portable WriterTopology authority chain that describes what a genuinely independent frontend/backend team must enforce before any runtime may claim that capability.

The chain has three authority digests:

```text
WriterTopology.topology_digest
sha256:b4b3e8ad868889082a871e3ecc7588b00ced58a0555da299061c0aae758de0dd
        │ exact topology identity + digest
        ▼
PlanRevision.plan_digest
sha256:5736168426ff82d70e78ba52d36c6407894e75922dd569de18db375eaded7efb
        │ exact plan fields + topology binding
        ▼
ApprovalGrant.scope_digest
sha256:2457ab8a7d297122c9f82322445b79bb7a90ba59f649bba9e5f315b5b0dfc4b7
```

The canonical files are:

- [`writer-topology.json`](../../examples/v08-contracts/valid/writer-topology.json);
- [`plan-revision.json`](../../examples/v08-contracts/valid/plan-revision.json);
- [`approval-grant.json`](../../examples/v08-contracts/valid/approval-grant.json).

Validate the complete chain offline:

```bash
./agent-team native writer-authority-validate \
  --topology examples/v08-contracts/valid/writer-topology.json \
  --plan examples/v08-contracts/valid/plan-revision.json \
  --approval examples/v08-contracts/valid/approval-grant.json
```

A successful report returns the topology digest, plan digest, approval scope digest, `automatic_execution: false`, and `identity_or_signature_verified: false`. The last field is essential: offline validation checks local document and digest coherence, not an approval actor's authenticated identity or digital signature. Validating only `writer_topology` with `native contract-validate` remains useful for editing that one document, but it does not prove that a plan and approval bind it.

## Version and compatibility boundary

Do not confuse the product version, contract versions, or host-install plan:

| Item | Version meaning |
|---|---|
| Agent Team Engineering `v1.0.0` | Introduces the WriterTopology authority chain |
| WriterTopology | Schema and document version `1.0.0` |
| PlanRevision and ApprovalGrant | Their current schema files have `$id` `1.1.0` and validate both `1.0.0` and `1.1.0` documents |
| Host installation plan `1.1.0` | A separate contract for installing host projections; it is not PlanRevision |

For PlanRevision and ApprovalGrant:

- a `1.1.0` document must include `writer_topology` explicitly;
- a topology-bound `1.1.0` plan must give every task an exact `allowed_paths` list; each writer task stays inside that writer's own ownership roots, non-writer tasks receive no source path, and the plan-level list is the exact union;
- use the exact topology identity/digest object when independent-writer authority is intended;
- use `null` when no WriterTopology authority is claimed; never infer a topology from role names;
- a compatible `1.0.0` document must omit `writer_topology` and cannot claim the `1.1.0` binding;
- migrating a legacy document to `1.1.0` requires a newly digested plan and a new approval; it is not an in-place authority upgrade.

The `v0.9.0` release history remains unchanged and did not provide this three-document authority chain. The v1.0 addition must not be backported in prose as if old v0.9 plans or approvals already carried it.

## Authority invariants

| Area | Required invariant |
|---|---|
| Writers | At least two distinct identities; each role reference matches its actor |
| Ownership | Repository-relative, normalized, non-overlapping subtrees |
| Git isolation | Every worktree and branch template includes `{work_item_id}` and `{writer_id}` |
| Approval | `human.owner`; binding is `exact-plan-and-topology-digests`; approval precedes writes |
| Plan binding | Plan repository/base match the topology; every writer receives a task; every allowed path is inside one writer root |
| Approval binding | Approval repeats the exact plan and topology bindings and its scope digest covers them |
| Integration | A separate integrator consumes immutable writer commits and evidence |
| Assurance | Exactly one independent read-only tester and reviewer; no self-review |
| Stop point | Independently tested and reviewed Draft PR only |
| Recovery | Retry stays on the same revision and approval; retry identity includes `topology_digest` |
| Default effects | No automatic merge, release, or deployment |
| Host mapping | Every projection says whether topology is enforced; canonical v1 records all say `false` |

Changing ownership, writer identity, Git templates, phases, or any other topology content changes `topology_digest`. That change also changes the bound plan digest, approval scope digest, and retry identity. Generate a new PlanRevision and obtain a new ApprovalGrant; never reuse the old approval or retry key.

The semantic validator also rejects overlaps where one root contains another, such as `apps/web` and `apps/web/components` assigned to different writers.

## Cross-cutting files

The v1 design intentionally fails closed when two writers own overlapping roots. A change to a shared API schema, lockfile, generated client, or repository-wide configuration must be handled by one of these reviewed choices:

1. replan so exactly one writer owns that path for the revision;
2. split the work into a prerequisite revision and rebase later writers on its approved commit;
3. stop for a human decision.

Do not grant both writers the repository root, and do not let the integrator silently author feature changes to resolve a conflict.

## What validation does not do

The authority validator reads three local JSON files. It does not install a host, launch or schedule an Agent, create or authenticate identities, verify a digital signature, enforce filesystem ownership, create worktrees or branches, read credentials, write a repository, open a PR, merge, release, or deploy. A result of `VALID` with `identity_or_signature_verified: false` is not a production identity grant.

`status: DESIGN_ONLY`, `topology_enforced: false`, and `automatic_execution: false` are safety facts. Passing the command proves coherent portable design authority only; it is not runtime conformance or activation evidence.

## Host degradation

Native role installation and multi-writer runtime enforcement are different claims:

| Host | v1 projection evidence | Independent-writer runtime enforcement |
|---|---|---|
| OpenClaw | `native-install-verified` team/Skill/context files | Not verified |
| Hermes Agent | `native-install-verified` team/Skill/context files | Not verified |
| Codex | `verified-export` role/context files | Not verified |
| Claude | `verified-export` role/context files | Not verified |
| Multica | `experimental-plan` leader/Squad overlay | Not verified; Squad wakes the leader and role labels are not permissions |
| Generic AI | `portable` Markdown/JSON | Receiving AI must map it |

A later adapter may raise an enforcement claim only with an authenticated, isolated live conformance fixture for writer identity, ownership, worktrees, handoff, approval, retry/recovery, and Draft PR stopping.

## Relationship to the current Managed runtime

`software-managed` remains a durable single-writer feedback-to-Draft-PR controller. It is useful when restart-safe state, exact approval, audit, and recovery matter. It must not be described as independent frontend/backend execution. Use the host-native team package for rich roles and this authority chain as the target design; use Managed only as an optional single-writer controller until a separate multi-writer runtime passes conformance.

See [ADR-0013](../adr/ADR-0013-portable-independent-writer-topology.md) for the decision boundary and the [v1.0 release acceptance contract](../16-release/v1.0-acceptance.md) for the full local, remote, and external-evidence gates.
