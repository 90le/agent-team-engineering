# v0.8 core contract examples

`valid/` contains one portable example for each v0.8 core entity and command/event envelope. `invalid/cases.json` describes deterministic mutations that the dependency-free contract validator must reject.

The examples intentionally contain no Paperclip, OpenHands, OpenClaw, GitHub, Codex, or Claude identity as a required core field. External identifiers belong in adapter mappings or typed references, never in the portable authority.

Run the focused checks with:

```bash
python3 -m unittest tests.test_v08_contracts
```
