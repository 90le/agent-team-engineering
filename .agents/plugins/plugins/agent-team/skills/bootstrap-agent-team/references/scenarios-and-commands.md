# Scenario and command guide

## Recommendation mapping

| User outcome | Recommended shape | Internal mapping | Boundary |
|---|---|---|---|
| Specialists invoked in an existing host | Native context-first team | `software-lite` or `custom` | Host remains the runtime |
| Separate frontend/backend source writers | Native team plus WriterTopology authority chain | v1.0 design contract | `DESIGN_ONLY`; no current host enforces it |
| Feedback progresses across restarts to a tested, independently reviewed Draft PR | Native team plus optional Managed controller | `software-managed` | No automatic merge or deploy |
| Custom roles with live external actions | Advanced integration project | No silent mapping | Engineer each capability, identity, approval, isolation, evidence, and recovery |

## Host meaning

- `openclaw`: isolated role workspaces, workspace-local Skills, empty bindings by default.
- `hermes`: role profile distributions, profile-local Skills, project/bundle/Kanban plan.
- `codex`: project Agents, `AGENTS.md`, and project-local Skills.
- `claude`: project subagents, `CLAUDE.md`, and project-local Skills.
- `multica`: `v0.4.23` `experimental-plan`; never execute workspace writes in the normal lifecycle.
- `generic-ai`: portable Markdown/JSON only.
- `leda`: `research-unknown` until exact official identity/version/contract is provided.

## Portable-team lifecycle

```bash
./agent-team onboard inspect --project-path /path/to/project
./agent-team onboard plan \
  --project-path /path/to/project \
  --purpose software \
  --automation assisted \
  --goal "Turn requests into reviewed changes" \
  --platform openclaw \
  --team-name "Example Team" \
  --project-name "Example Product" \
  --owner "Project Owner" \
  --provider github \
  --repository example/product \
  --output /new/path/example-team \
  --plan /new/path/example-team-plan.json
./agent-team onboard preview --plan /new/path/example-team-plan.json
./agent-team onboard validate --plan /new/path/example-team-plan.json
```

After exact confirmation, use the displayed digest with `onboard confirm`, then `onboard apply` and `context validate`.

## Independent-writer authority check

```bash
./agent-team native writer-authority-validate \
  --topology examples/v08-contracts/valid/writer-topology.json \
  --plan examples/v08-contracts/valid/plan-revision.json \
  --approval examples/v08-contracts/valid/approval-grant.json
```

This validates the v1.0 canonical topology → plan → approval digest chain and reports `automatic_execution: false`. It does not start a multi-writer runtime. PlanRevision and ApprovalGrant `1.1.0` documents bind an explicit topology object or `null`; legacy `1.0.0` documents omit that field.

## Separate host lifecycle

```bash
./agent-team host list
./agent-team host probe --target openclaw
./agent-team host plan \
  --team /new/path/example-team \
  --target openclaw \
  --destination /new/path/openclaw-team \
  --output /new/path/openclaw-plan.json
./agent-team host preview --plan /new/path/openclaw-plan.json
```

After a second exact confirmation, use the previewed `host confirm` and `host apply` commands, then run `./agent-team host verify --root <destination>`. Apply preserves unrelated destination content but never overwrites a planned path.
