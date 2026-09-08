# Personal GitHub Free repository

Owner: Ryan's personal account. Visibility: private. Teammates: collaborators.
No subscription upgrade is required. Repository: https://github.com/Ryan-Lee-2000/ConnectSphere.
Collaborator invitations/usernames have not been verified. Actions is enabled following the
account budget review; PR verification and main deployment have passed.

## Initial setup checklist (retained for reference)

1. Create an empty private repository without generated README, licence or .gitignore.
2. Before uploading the workflow, check account-wide Actions usage and available controls that
   stop paid usage. Keep Actions disabled until this is confirmed. Do not enable paid overages.
   Record the actual allowance and consumption in docs/infrastructure/ci-budget.json; UNKNOWN is not zero.
3. Upload reviewed source only, following README. Never upload local environment files or caches.
4. Invite teammates as collaborators. Choose a backup reviewer for periods when Ryan is unavailable.
5. Enable Actions after budget review, with read-only default workflow-token permissions and
   without allowing Actions to create/approve PRs. Enable Dependabot alerts/security updates
   where available. The committed Dependabot config schedules version updates on the default branch.
6. Open a small documentation PR and verify the checks execute successfully before normal work.

GitHub Free currently includes 2,000 Actions minutes/month and 500 MB Actions storage for this
account type. These are shared account allowances, not a fresh allowance for this repository.
Confirm the dashboard and current [GitHub allowance documentation](https://docs.github.com/en/billing/reference/product-usage-included).

## Review agreement

Use task branches and PRs. Another teammate reviews the latest changes and checks must pass
before a human merges. Do not push directly to main, force-push main, bypass a failed check,
or automatically merge dependency PRs. Request reviewers manually; CODEOWNERS.example is only
a placeholder. These are team rules: private GitHub Free does not enforce protected-branch
reviews/checks. Collaborators with write access can bypass them.

## Verification coverage

Each PR and main push runs one Linux job: lint/format, unit/API and frontend tests, typecheck,
frontend build, a separate disposable PostgreSQL migration test and production Docker build.
The job has a 20-minute limit; obsolete PR runs are cancelled. No reports or images are uploaded.
The Docker build uses no hosted credentials and is a build check, not a runtime/Auth check.
Real local Auth/browser and Docker runtime checks remain local acceptance evidence; they must
be rerun for relevant changes. They are not automated CI gates. Hosted Auth was verified manually before deployment activation.

Dependabot checks npm (including the pnpm workspace), uv, Docker and Actions weekly on Mondays
at 09:00 Singapore time. Minor/patch updates are grouped within JavaScript, Python and Actions;
major updates are separate. Each ecosystem permits one open version-update PR (four total),
not a global one-PR limit. Security updates have separate scheduling/limits. Review runtime
version changes against README, launchers and Dockerfile; updates to embedded tool-install
commands are not guaranteed by Dependabot. Normal tests still run on dependency PRs.

## Active hosting

DEPLOY_ENABLED is true. Set it false to pause future GitHub deployments; this does not cancel
a running deployment. See docs/infrastructure/deployment.md for configuration and recovery.
The free-plan workflow uses repository Actions secrets, with no environment approval gate.
Repository write access must therefore be trusted: workflow editors can change how secrets are used.
The main-branch condition is normal workflow routing, not protection against a collaborator editing it.

Sources: [branch protection](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches),
[environments](https://docs.github.com/en/actions/reference/workflows-and-actions/deployments-and-environments),
[Dependabot options](https://docs.github.com/en/code-security/reference/supply-chain-security/dependabot-options-reference).

## Initial dependency review (2026-09-07)

PR #2 changes only the Docker Python image to 3.14, conflicting with the project's Python
3.13 requirement. Defer it until a coordinated runtime migration is approved. PRs #3 (Vitest 5)
and #4 (Gunicorn 26) are untested major application/test-tool upgrades and remain deferred,
not certified as compatible or unsafe. Security advisory and major-upgrade review remain separate maintenance work.
PR #1's pnpm Action update is included in the consolidated CI runtime maintenance PR.
The maintenance change moves checkout/setup-node/pnpm setup to v6 and setup-uv to v7;
upstream manifests declare node24 for each. Installed Node 24, pnpm 10.15.1, uv 0.11.33
and Python 3.13 stay pinned. setup-node's automatic package-manager cache is disabled,
avoiding a dependency on pnpm before its installation step. Dependabot proposals remain
subject to human review; no application dependency updates are merged by this review.
