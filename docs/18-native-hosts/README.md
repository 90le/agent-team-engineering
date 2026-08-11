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
- destination and every managed artifact;
- host descriptor version, evidence tier, and any separate read-only probe result;
- overwrite, merge, credentials, bindings, and network behavior;
- known unsupported capabilities;
- digest, verification, and uninstall scope.

Only an exact confirmation may unlock `host apply`. Changing the source, target, destination, descriptor, or artifact set invalidates the digest. Apply creates only absent files listed in the plan. An existing destination may contain unrelated files, which are preserved; any planned-path collision, symlink crossing, different install lock, or source drift fails closed.

`host uninstall` removes only artifacts recorded as owned by the exact install record. It is not permission to remove user-managed host configuration, workspaces, sessions, Skills, credentials, or project files.

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

For the governing decision, read [ADR-0011](../adr/ADR-0011-host-capability-contract-and-native-team-projection.md).
