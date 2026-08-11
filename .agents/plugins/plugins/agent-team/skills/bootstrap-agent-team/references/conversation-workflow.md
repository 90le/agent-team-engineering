# Adoption conversation workflow

## The conversation contract

The user supplies outcomes and decisions; the AI translates them into a reviewable team proposal. Internal presets are implementation details, not the opening question.

Use this sequence:

1. Restate the desired outcome in one sentence.
2. Inspect the target project read-only and distinguish verified facts from unknowns.
3. Ask no more than three high-impact questions in one turn.
4. Recommend one team shape with reasons, one alternative, and limitations.
5. Materialize and show a strict plan preview with its digest.
6. Stop for exact confirmation.
7. Confirm, create, validate, and teach the first task.
8. Treat project export or live integration as a separate decision.

## High-impact questions

Ask only what changes the recommendation or authority boundary. Typical questions are:

- What outcome should the team repeatedly produce?
- Should people invoke it when needed, or must feedback progress durably across restarts to a reviewed Draft PR?
- Which AI products need native files: Codex, Claude, OpenClaw, or a generic file-capable AI?
- Who is the human owner for scope and sensitive decisions?
- For a non-software team, which responsibilities must remain distinct?

Do not ask the user to repeat a project name, branch, technology, test layout, or existing AI entrypoint already verified from the repository. Do not ask for tokens, passwords, production data, or model credentials.

## Recommendation format

Use a compact response like this before running the planner:

```text
Understood outcome: ...
Verified from the project: ...
Recommended team: ...
Why: ...
Alternative: ...
Not enabled: ...
Unknowns that remain: ...
```

After planning, show the CLI preview without hiding its digest. Say: “This is a proposal only. It will create one new team directory; it will not change your project or connect external systems. Shall I apply this exact proposal?”

## After creation

Do not end with only file paths. Give the user this pattern, adapted to their outcome:

> Read `<team>/AI-START.md` completely. Help me use this team for: `<first outcome>`. Inspect durable state, recommend the responsible role and next bounded step, and ask at most three high-impact questions. Do not assume external authority.

Also explain these daily requests:

- start a new task;
- show status from durable work records;
- continue from the last verified handoff;
- explain role routing without acting;
- stop safely and return the owner decision needed.
