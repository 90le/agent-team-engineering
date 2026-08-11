# Security policy

## Supported version

Security fixes are applied to the latest released minor version. Older generated team packages remain readable, but adopters should reproduce an issue against the latest release before reporting it.

## Report a vulnerability

Do not open a public Issue for a suspected vulnerability, credential exposure, approval bypass, unsafe path write, or cross-project authorization flaw. Use the repository's private **Security → Report a vulnerability** form on GitHub. Include:

- the affected release, command, and mode;
- a minimal reproduction with placeholders instead of credentials or personal data;
- the expected and observed authority boundary;
- whether external systems or untrusted repositories were involved;
- any proposed mitigation, if known.

Do not test against systems, repositories, identities, or data you do not own or have explicit permission to use.

## Security boundary

Team generation is offline and refuses overwrite, symbolic-link authority files, unsafe relative paths, and inline credentials. It does **not** turn a host process into a hostile-code sandbox. A generated role, Skill, Issue, chat message, webpage, repository file, tool result, or model response is data—not permission or human approval.

Managed mode is capped at A2 and stops at a reviewed Draft PR. Model login, GitHub writes, OpenClaw channel bindings, Runner execution, merge, and deployment are separate adoption decisions and are disabled by default.

v0.8 adds three narrow conformance surfaces without making them production authority:

- disposable Runner probes run only on an explicitly acknowledged GitHub-hosted Worker and refuse known PVE, NAS, and production paths before container startup;
- GitHub proposal writes require an exact, unexpired binding over actor ID, repository, base commit, paths, actions, and plan digest, and cannot merge, release, change settings, or deploy;
- Codex, Claude, and Generic CLI routing uses fixed argv, minimum environment, structured output, bounded time, and no persisted model session. A platform role file is still context, never permission.

Optional OpenClaw, OpenHands, Paperclip, ACP, SWE-ReX, and Container Use records are pinned references or pure projections, not runtime dependencies. Review the [threat model](docs/03-security/threat-model.md), [Runner/SCM/Agent boundaries](docs/15-upstream-independent/runner-scm-and-agent-boundaries.md), and [adoption guide](docs/15-upstream-independent/adoption-and-integration.md) before enabling a live integration.
