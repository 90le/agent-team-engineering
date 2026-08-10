# Contributing

Thank you for improving Agent Team Engineering. Contributions should preserve its central property: humans and different AI systems can inspect the same durable context, while code enforces the parts that prose cannot safely enforce.

## Before opening a change

1. Open or reference an Issue describing the user outcome and compatibility impact.
2. Keep Factory contracts generic. Do not add organization secrets, business data, runtime databases, personal paths, or credentials.
3. Record an ADR when changing authority, workflow state, package boundaries, compatibility, or platform semantics.
4. Preserve legacy CLI and generated-package compatibility unless the change includes an explicit migration and recovery path.

## Develop and verify

Use Python 3.11+ and Git. The runtime has no third-party Python dependency.

```bash
python3 tools/agent_team.py validate
python3 -m unittest discover -s tests -v
python3 tools/agent_team.py simulate --approve-production
tools/cold-start.sh
```

Add positive, negative, determinism, and no-overwrite tests for every new compiler or authority path. Platform assets must remain self-contained and must not silently enable credentials, external writes, channel bindings, merge, or deployment.

## Pull requests

Keep a change bounded and explain:

- the user outcome and non-goals;
- the contract, security, and migration impact;
- the exact verification commands and results;
- any remaining manual adoption decision.

Authors must not approve their own security or release-boundary changes. A maintainer decides whether and when to merge.

By submitting a contribution, you agree that it is licensed under the repository's [Apache License 2.0](LICENSE).
