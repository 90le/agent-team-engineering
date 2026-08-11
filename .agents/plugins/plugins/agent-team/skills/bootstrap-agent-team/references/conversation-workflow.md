# Host-native adoption conversation

## Conversation contract

The user provides outcomes and decisions. The AI verifies project/host facts, recommends a team, and translates the decision into two separately confirmed plans.

1. Restate the desired recurring outcome.
2. Inspect the target project and installed host candidates read-only.
3. Ask at most three high-impact questions.
4. Recommend roles, handoffs, one primary existing host, evidence tier, and human gates.
5. Preview the portable-team plan and stop for its exact digest confirmation.
6. Create and validate the team.
7. Preview a separate host-install plan and stop for a second exact confirmation.
8. Apply only declared managed files, verify honestly, and teach the first task.

## High-impact questions

- What result should the team repeatedly produce?
- Should people invoke it on demand, or must it progress durably across restarts?
- Which installed AI host should run the roles?
- Who is the human owner, and which decisions remain human?
- Which named roles or independent review separation are mandatory?

Do not ask the user to repeat a project name, branch, technology, test layout, existing AI entrypoint, or host version already verified. Never ask for tokens or passwords.

## Recommendation format

```text
Understood outcome: ...
Verified project/host facts: ...
Recommended team and host: ...
Roles and handoff: ...
Why: ...
Evidence tier: ...
Alternative: ...
Human gates: ...
Disabled or unknown: ...
```

Do not call a generated package “natively loaded”, an isolated CLI check “live”, or an `experimental-plan` “supported”. Prefer the compatible host the user already operates.

## Two confirmation statements

Before team creation:

> This proposal only creates a new portable team directory. It does not modify your project, install into an AI host, create an account, bind a channel, or enable external writes.

Before host apply:

> This separate proposal manages only the displayed destination/files. It does not grant the roles tools, credentials, account authority, merge, or deployment.

After verification, return exact checks and skipped checks, evidence tier, owned paths, uninstall boundary, and a copyable first request.
