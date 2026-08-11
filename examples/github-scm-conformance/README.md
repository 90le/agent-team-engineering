# Dedicated GitHub SCM conformance repository

Use this template only in a new Private repository that contains no product code, user data, secrets, deployment configuration, or branch shared with another project. It proves the v0.8 proposal-only connector before any business-repository adoption.

## One-time setup

1. Create an empty Private repository and protect it from production use.
2. Copy `workflow.yml` to `.github/workflows/agent-team-v08-conformance.yml` in its default branch.
3. Replace `REPLACE_WITH_NUMERIC_OWNER_ID` in that trusted workflow with the human owner's immutable GitHub actor ID. Do not turn it into a dispatch input.
4. Commit the workflow and record the exact default-branch commit.
5. Select an exact reviewed Agent Team framework commit and compute the plan digest from that checkout:

```bash
python3 tools/github_scm_conformance.py \
  --repository-id conformance.github.v08 \
  --base-commit <private-repository-main-commit> \
  --framework-commit <agent-team-framework-commit> \
  --repository owner/private-conformance-repository \
  --print-plan-digest
```

6. Manually dispatch the workflow with those exact three values and the printed digest. A successful first run creates one Issue, one proposal branch, one file commit, and one unmerged Draft PR.
7. Dispatch the same inputs again. The second report must show `created=false` for all four objects and the same provider references.

Never merge the Draft PR. Download both sanitized reports before deleting the test repository. A report is evidence, not permission to connect a business repository.

## What the workflow cannot do

Its job token is scoped to the repository and declares only `contents`, `issues`, and `pull-requests` write access. The framework client has no merge, release, settings, environment, secret, or deployment method. The checked-out public framework uses `persist-credentials: false`, so its directory does not receive the private repository token through Git credentials.
