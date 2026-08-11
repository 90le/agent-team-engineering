# Example: existing software project with Codex and Claude

## User request

> I have an existing web application. Create an AI development team that can understand feedback, plan changes, develop frontend and backend work, test it and review it. I use Codex and Claude.

## Read-only discovery

The guide reports only what it verifies, for example: Node and Python markers, a `tests/` directory, architecture documents, current Git branch, existing `AGENTS.md`, and whether the checkout is dirty.

## Focused questions

1. Should people invoke the team when needed, or must work keep progressing through a persistent controller across restarts?
2. Who is the human owner who approves scope and sensitive actions?
3. Which new directory should hold the team package?

## Recommendation

Recommend a portable AI-assisted software team with product, architecture, frontend, backend, QA, independent review and release-handoff responsibilities. Explain that Codex and Claude receive native role adapters over the same Markdown authority. The internal mapping is `software-lite`.

Alternative: the governed Managed team is appropriate only if durable feedback-to-Draft-PR progression is required.

Not enabled: model login, repository writes, authenticated approval, merge and deployment.

## Confirmation stop

The guide creates and displays a strict plan. It does not generate the team until the user confirms the exact digest. After creation, it validates and returns:

> Read `<team>/AI-START.md`. Help me use this team for: “Add saved searches to the dashboard.” Inspect current facts, recommend the responsible first role and bounded output, and ask at most three high-impact questions. Do not assume repository write or merge authority.
