# Start here: create your Agent Team

This is the adoption entrypoint for a human or AI using this repository. To maintain or modify the Factory itself, switch to [AI-BOOTSTRAP.md](AI-BOOTSTRAP.md).

## What this repository creates

Given a project, a team preset, and one or more target platforms, it creates a new portable package containing:

- shared Markdown context, project facts, architecture, decisions, and knowledge registry;
- explicit role missions, responsibilities, inputs, outputs, tools, prohibitions, handoffs, success, and stop conditions;
- reusable Skills loaded only when a role needs them;
- native Codex, Claude, OpenClaw, or Generic AI discovery files;
- a strict JSON design and SHA-256 lock;
- optionally, a durable governed runtime that stops after a tested, independently reviewed Draft PR.

It does not create credentials, authenticate approvals, connect channels, merge code, or deploy production.

## If an AI is reading this for a user

1. Inspect the target project read-only. Do not modify it yet.
2. Identify or ask for: team name, project name, repository locator, default branch, human owner, desired platforms, and whether the user wants Lite, Managed, or Custom.
3. Default to `software-lite`. Use `software-managed` only when persistent automation is explicitly requested. Use `custom` for user-named roles.
4. Create only in a new directory outside this Factory and outside the target project.
5. Validate the result and report its paths, roles, human gates, project unknowns, and remaining integration work.
6. Do not enable model sessions, provider writes, OpenClaw bindings, host execution, merge, deployment, or secrets as part of creation.
7. Explain which files are compiler-managed and which project context, knowledge, decisions, and work records the owner may maintain through Git review.

## Fastest local start

```bash
./agent-team presets

./agent-team create \
  --preset software-lite \
  --name "Example Product Team" \
  --project "Example Product" \
  --repo example/example-product \
  --provider github \
  --platform codex \
  --platform claude \
  --output /new/path/example-product-team

./agent-team context validate --root /new/path/example-product-team
```

Interactive terminals can use:

```bash
./agent-team create --guided --output /new/path/my-team
```

For custom roles, repeat `--role`:

```bash
./agent-team create \
  --preset custom \
  --name "Research Team" \
  --project "Knowledge Project" \
  --repo local/knowledge \
  --provider generic-git \
  --platform generic-ai \
  --role "research-lead:Research Lead" \
  --role "fact-checker:Fact Checker" \
  --role "editor:Editor" \
  --output /new/path/research-team
```

Continue with the [context-first team guide](docs/14-context-first/context-first-team-kit.md) or [platform installation guide](docs/14-context-first/platform-installation.md).
