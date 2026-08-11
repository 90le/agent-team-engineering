# Guided adoption examples

These examples show what a human or no-history AI should do before choosing an internal compiler mapping. They are conversation and decision examples, not credentials or production integration recipes.

| Scenario | User starts with | Expected recommendation |
|---|---|---|
| [Existing software project](software-assisted.md) | “Give Codex and Claude a team that can help us ship reviewed changes.” | AI-assisted portable software team |
| [Persistent feedback to Draft PR](managed-feedback.md) | “Keep processing feedback across restarts, but wait for my exact plan approval.” | Governed Managed reference team, live adapters disabled |
| [Long-lived knowledge base](knowledge-team.md) | “Build a source-checked knowledge team usable by people and different AIs.” | Custom context-first knowledge team |

Each example demonstrates:

1. read-only facts before questions;
2. no internal-mode opening question;
3. at most three questions in one turn;
4. one explained recommendation and alternative;
5. explicit disabled capabilities;
6. a strict preview and confirmation stop;
7. a usable first-task prompt after generation.

Run the real CLI contract with a disposable local project as shown in the [guided adoption guide](../../docs/17-guided-adoption/README.md). The automated tests generate their own paths and assert that unconfirmed, tampered, stale, secret-bearing and overwriting operations fail closed.
