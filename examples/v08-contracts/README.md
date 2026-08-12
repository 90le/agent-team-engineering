# Portable core contract examples

`valid/` contains one portable example for each core entity and command/event envelope. The stable v0.8 set is retained. The v1.0 product release adds the design-only `writer-topology.json` and upgrades the canonical PlanRevision/ApprovalGrant examples to documents `1.1.0`, which explicitly bind that topology. The unified PlanRevision and ApprovalGrant schema files have `$id` `1.1.0` but remain compatible with legacy `1.0.0` documents that omit `writer_topology`. This v1.0 addition does not rewrite v0.9 release history. `invalid/cases.json` describes deterministic mutations that the dependency-free contract validator must reject.

The schemas intentionally contain no Paperclip, OpenHands, OpenClaw, GitHub, Codex, or Claude identity as a required core field. The canonical writer topology example carries explicit host degradation records as data, but the schema accepts arbitrary host identifiers. External identifiers belong in adapter mappings or typed references, never in mandatory portable vocabulary.

Run the focused checks with:

```bash
python3 -m unittest tests.test_v08_contracts

./agent-team native writer-authority-validate \
  --topology examples/v08-contracts/valid/writer-topology.json \
  --plan examples/v08-contracts/valid/plan-revision.json \
  --approval examples/v08-contracts/valid/approval-grant.json
```

The second command validates the canonical topology → plan → approval digest chain and explicitly reports `automatic_execution: false`.
