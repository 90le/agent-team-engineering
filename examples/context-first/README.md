# Context-first team example

This example demonstrates the portable input contract without depending on a model, plugin, network service, or persistent controller. It defines a small knowledge team with a researcher, an independent reviewer, a curator, and a final human decision.

Compile it only to a new directory:

```bash
./agent-team create \
  --design examples/context-first/team-design.json \
  --output /new/path/knowledge-steward-team

./agent-team context validate --root /new/path/knowledge-steward-team
./agent-team context inspect --root /new/path/knowledge-steward-team
```

The result is a Lite team. It creates Markdown context, role contracts, Skills, a Generic AI adapter, and a digest lock; it does not call an AI, write to GitHub, or grant tools. Edit a copy of the design outside the Factory when adapting it.

For the richer eight-role software preset, use `./agent-team create --preset software-lite ...`. For the governed feedback-to-Draft-PR runtime, explicitly choose `software-managed` after reading the security and runtime guides.
