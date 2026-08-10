# Team blueprint quick example

Create a complete, non-overwriting team package outside the Factory repository:

```bash
python3 tools/agent_team.py team create \
  --blueprint examples/team-blueprint/input/team.json \
  --output /tmp/example-product-team

python3 tools/agent_team.py team validate --root /tmp/example-product-team
python3 tools/agent_team.py team inspect --root /tmp/example-product-team
```

The example targets a placeholder GitHub repository and keeps every external adapter disabled. It
therefore proves compilation and portability without creating an Issue, invoking a model, pushing a
branch, or opening a Pull Request. Replace the project locator in a copied blueprint and review the
instance-specific identity and secret plan before enabling provider writes.

For an immediately executable no-network team, use:

```bash
python3 tools/agent_team.py team demo --output /tmp/agent-team-demo
```

That command creates a separate reference project and enables only the deterministic model router.
It stops at the human plan gate; follow the exact approval and resume commands in the JSON output.
The full adoption, live CLI, GitHub, Runner and OpenClaw boundaries are documented in
[the Team Creator guide](../../docs/13-team-creator/blueprint-compiler-and-reference-runtime.md).
