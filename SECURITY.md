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

Managed mode is capped at A2 and stops at a reviewed Draft PR. Model login, GitHub writes, OpenClaw channel bindings, host Runner execution, merge, and deployment are separate adoption decisions and are disabled by default. Read the [threat model](docs/03-security/threat-model.md) before enabling live integrations.
