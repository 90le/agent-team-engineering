# Guided adoption: from a goal to a working Agent Team

This guide defines the ordinary-user path introduced in v0.8.1. It is written for adopters, AI assistants, plugin authors, and maintainers who need the same behavior across Codex, Claude, OpenClaw, and generic file-capable AI products.

## Product promise

A user should be able to say what outcome they want without knowing the Factory's internal presets. The adoption AI inspects discoverable project facts, asks only high-impact questions, explains one recommendation and an alternative, materializes a strict proposal, waits for exact confirmation, and then lets the deterministic compiler create and validate a new team package.

The AI and CLI have different responsibilities:

| Layer | Responsibility | Must not do |
|---|---|---|
| AI guide | Understand natural language, inspect read-only facts, clarify intent, explain tradeoffs, teach usage | Invent authority, hide unknowns, treat a mode name as user intent |
| Adoption plan | Preserve discovery, answers, recommendation, paths, effects, limitations and exact digest | Carry secrets or ambiguous side effects |
| CLI | Validate schema, bind confirmation, reject drift/overwrite, compile deterministically, validate result | Pretend to understand free-form intent or silently choose external permissions |
| Generated team | Route outcomes to roles, preserve durable context and handoffs, expose platform entrypoints | Create credentials, authenticate approval, merge, or deploy |

## The three decision dimensions

Do not collapse these into one opening “mode” question:

1. **Purpose**: software, research/knowledge, content, operations, or custom.
2. **Coordination depth**: file-based, AI-assisted on demand, or durable governed progression to a reviewed Draft PR.
3. **AI platforms**: Codex, Claude, OpenClaw, Generic AI, or a combination.

The internal mapping follows only after those dimensions are understood:

| Purpose and coordination | Compiler mapping |
|---|---|
| Software + files/assisted | `software-lite` |
| Software + durable governed feedback-to-Draft-PR | `software-managed` |
| Non-software or named roles + files/assisted | `custom` |
| Non-software or unmapped roles + Managed | Unsupported until capabilities are separately engineered |

The last row is an intentional stop, not a missing prompt. A custom role cannot obtain an authenticated identity, Shell, repository write, approval, or recovery semantics from prose alone.

## Conversation behavior

The detailed protocol is in [conversation-protocol.md](conversation-protocol.md). Its core rules are:

- inspect before asking;
- no more than three questions in one turn;
- do not ask for facts already verified;
- recommend in user language and explain why;
- show one meaningful alternative and all material limitations;
- show the exact plan and digest before asking for confirmation;
- never combine team creation with project export or live integration;
- after creation, teach a copyable first request and daily operations.

## Interactive human path

```bash
./agent-team onboard guided --output /new/path/my-team
```

The command interviews for purpose, coordination depth, platforms, outcome, project identity, owner, and custom roles when needed. It saves a draft plan beside the requested team path, prints the full preview, and creates nothing unless the user types `yes` in the interactive confirmation.

The older `create --guided` entry delegates to this scenario-first path when no explicit preset is supplied. Existing automation may continue using `create --preset` or `create --design`.

## AI and automation path

The AI first runs read-only discovery:

```bash
./agent-team onboard inspect --project-path /path/to/project
```

After clarifying intent, it creates a draft using explicit arguments, previews and validates it, and then stops:

```bash
./agent-team onboard plan ... --plan /new/path/team-adoption-plan.json
./agent-team onboard preview --plan /new/path/team-adoption-plan.json
./agent-team onboard validate --plan /new/path/team-adoption-plan.json
```

Only after the owner confirms that exact preview:

```bash
./agent-team onboard confirm \
  --plan /new/path/team-adoption-plan.json \
  --digest sha256:<exact-digest> \
  --approved-by "Human Owner"

./agent-team onboard apply --plan /new/path/team-adoption-plan.json
```

See [plan-contract.md](plan-contract.md) for the strict state and digest semantics.

## Two confirmations, not one

Team creation and target-project adoption have different effects:

1. **Create team**: writes one absent directory outside the Factory and target project. It does not alter the target or contact an external provider.
2. **Adopt platform overlay**: exports and then reconciles `AGENTS.md`, `CLAUDE.md`, `.codex/`, `.claude/`, or OpenClaw files into a target proposal branch. This requires a second review and confirmation.

Live channels, models, authenticated approval, repository writes, an isolated Runner, merge, and deployment are further integration gates. A team-creation confirmation cannot authorize them.

## Generated usage experience

Every generated context team includes:

- `GETTING-STARTED.md` for people: first prompt, daily requests, role map, project setup and integration boundary;
- `AI-START.md` for AI: read order, automatic role routing, maximum-three-question rule, first-response contract, durable continuation and safe stop;
- `TEAM.md` and `ROLES/` for complete responsibility contracts;
- `WORK/` for durable task, evidence and handoff state;
- `PROJECT-CONTEXT.md`, `ARCHITECTURE.md`, `KNOWLEDGE/`, and `DECISIONS/` for maintainable project truth.

The user describes the outcome. The AI selects and explains the responsible role; it should not force the user to memorize role IDs.

## Acceptance standard

An adoption release is not accepted merely because its CLI tests pass. A no-history AI must be able to receive the repository and a natural request, then:

1. find the adoption entrypoint;
2. inspect the project read-only;
3. ask focused questions without exposing presets first;
4. recommend and explain a supported team;
5. stop at an exact preview;
6. create only after confirmation;
7. validate and explain how to begin the first task;
8. preserve disabled external integrations.

The release test set covers a software-assisted project, a durable feedback-to-Draft-PR request, and a custom knowledge team. See [the examples](../../examples/guided-adoption/README.md) and [FAQ](faq.md).
