# Multica experimental plan

Official research baseline: [multica-ai/multica `v0.4.23`](https://github.com/multica-ai/multica/tree/v0.4.23).

## Status

Multica is `experimental-plan`, not a live-supported installation target.

The Factory may generate a reviewable, version-pinned intent containing:

- proposed Agent names, descriptions, behavioral instructions, and runtime selectors;
- reusable Skill packages and an explicit Skill-binding plan;
- a squad leader/member topology and role labels;
- commands or API-shaped operations for human review;
- required unresolved inputs such as workspace, runtime, identity, and authentication;
- limitations, digest, and evidence metadata.

The overlay separates catalog descriptions from behavioral instructions and separates Agent creation from Skill binding. It does not treat a squad diagram as proof that work delegation, review, or execution occurred.

## Apply boundary

Factory `host apply` must not write to a real Multica installation or workspace in this support tier. It may materialize the offline overlay in a new destination for inspection. An operator must not run its proposed commands until all of the following are available and separately approved:

- exact compatible Multica version;
- authenticated workspace and human owner;
- valid runtime IDs and model/tool policy;
- reviewed Agent instructions and Skill contents;
- exact Agent, squad, and binding diff;
- rollback and post-write verification;
- license review for the intended deployment.

No workspace, Agent, Skill, squad, daemon, credential, or external repository is created by the experimental plan.

Materializing that offline package still follows the [common v1 file lifecycle](README.md): complete proposal binding, deterministic file stages, fixed transient metadata scratch, persistent empty guard, exact prior-tombstone disclosure, non-overwrite first apply, read-only uninstall preview, and replay-safe file removal. Apply/uninstall may create or replace and then delete only the exact declared scratch and must leave it absent on success; they never touch similarly named hidden files. The uninstall preview lists that scratch in delete/create/transient fields for `ACTIVE`/`UNINSTALLING`, and returns empty fields for `ALREADY_UNINSTALLED`/`LEGACY_UNBOUND`. These file guarantees do not promote Multica beyond `experimental-plan` and do not authorize execution of any proposed workspace command. A v0.9 file plan must be rebuilt; a v0.9 lock remains `LEGACY_UNBOUND` and cannot be automatically removed.

## License boundary

Multica's [`v0.4.23` license](https://github.com/multica-ai/multica/blob/v0.4.23/LICENSE) is titled **Multica License**. It combines Apache License 2.0 text with additional conditions, including restrictions and obligations involving hosted/embedded services, branding, attribution, contributions, and redistribution.

Agent Team Engineering references the public contract and emits its own portable data; it does not copy or vendor Multica source. Do not label Multica itself as plain `Apache-2.0`, and do not assume this repository's Apache-2.0 license changes Multica's terms. This is an engineering disclosure, not legal advice.

## Promotion criteria

Do not promote Multica beyond `experimental-plan` until a reproducible acceptance environment can:

1. pin an official version and compatible CLI/API contract;
2. use a disposable authenticated workspace and non-production runtime;
3. create/import Agents and Skills without secrets in artifacts;
4. bind Skills and squad membership exactly as previewed;
5. verify instructions, topology, ownership, and negative cases;
6. uninstall or rollback only created objects;
7. record upstream license review and observed external effects.

Until those gates pass, every generated Multica command remains a proposal for a human operator, not a supported action.
