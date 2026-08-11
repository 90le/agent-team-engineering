# Example: long-lived research and knowledge team

## User request

> I want a knowledge base that people, AI and future Agents can use for years. Sources must be traceable, facts checked and documents kept maintainable across different tools.

## Read-only discovery

The guide looks for existing Markdown, Git history, knowledge indexes, architecture or governance documents and AI entrypoints. It does not read private exports, secrets or a vector database as the sole source of truth.

## Focused questions

1. What kinds of sources and final knowledge products should the team maintain?
2. Who accepts a document as authoritative and decides corrections or retirement?
3. Which AI products must consume the same team context?

## Recommendation

Recommend a custom context-first team with Research Lead, Source Curator, Fact Checker, Knowledge Editor and Knowledge Librarian. Explain source registration, evidence handoffs, owner review and durable Git/Markdown authority. The internal mapping is `custom`.

Alternative: supply user-named roles if the domain requires specialist review such as legal, medical or localization; those roles still do not receive sensitive authority automatically.

Not enabled: crawler accounts, external publishing, secrets, autonomous production edits or a persistent controller. Custom Managed automation requires a separate capability mapping.

## First task after creation

> Read `<team>/AI-START.md`. Help me establish the first verified source registry and document lifecycle. Recommend the first responsible role, identify unknown governance decisions, and propose one bounded work packet without external writes.
