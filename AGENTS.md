# Shared instructions for all agents

Read README.md, docs/architecture.md, the selected task and docs/requirements.md.
Use the active task's acceptance criteria. Sprint 0 contains no product features. Implement only team-approved product tasks.

For frontend work, also read PRODUCT.md and DESIGN.md. Treat the tokens in DESIGN.md as the shared visual source of truth; DESIGN.json is its machine-readable extension.

## Commands
- npm run doctor / npm run setup / npm start (native Windows and macOS; WSL/Make optional).
- npm run verify: lint, format check, backend unit/API tests, frontend tests, typecheck and build.
- npm run integration: requires INTEGRATION_DATABASE_URL pointing at an EMPTY disposable PostgreSQL.
- npm run check:e2e: requires local Supabase, the Auth test fixture, frontend and API already running.
- npm run e2e:record -- <spec>: records a browser spec on video for UAT evidence; app and real Auth fixtures must already run.
- Existing make aliases remain supported with their Python/pnpm prerequisites installed.
Report exactly which checks passed, skipped or could not run. Never replace a failing check with a skip.

## Architecture and ownership
React calls Supabase only for auth; business records go through Flask.
Never trust a submitted user/role/organisation ID. Never disable auth to make tests pass.
Application migrations belong only to Alembic. Do not edit a merged migration.
One agent workspace per developer initially. No shared uncommitted directory, DB resets, or ports
between concurrent tasks. Take no unassigned work automatically. Jira tracks each story's status; QA and DevOps reports live in the Confluence QA space.

## Small tasks and handoff
Implement only the selected task. Read dependencies first.
Push coherent changes after local checks, not every generated edit.
PRs include requirements, test results, migration notes and open questions.
Humans review and merge. Do not change Sprint scope/estimates/AC without team agreement.
A story is not Done merely because a PR exists. Record review and deployment separately.

## Workflow skills
A ticket moves through skills run by the developer with the ticket key:
build (`$build SPL-103` in Codex, `/build SPL-103` in Claude Code), then qa, then devops.
pr-review (`$pr-review SPL-103 91`, with the PR number) handles each round of review comments;
devops is run again after the PR is merged.
The instructions live in `.agents/skills/<name>/SKILL.md`; `.claude/skills/` only points there.
When a skill is invoked, read its SKILL.md in full and follow it. Edit only the `.agents` copy.
Reports use the Confluence QA space master templates:
[QA-TEMPLATE](https://clivelim01-1787647390567.atlassian.net/wiki/spaces/QS/pages/20086786) for QA-<KEY> and
[DEVOPS-TEMPLATE](https://clivelim01-1787647390567.atlassian.net/wiki/spaces/QS/pages/20086804) for DEVOPS-<KEY>.

## Budget and deployment
Run npm run budget. UNKNOWN means account usage is unverified, not zero.
Conserve CI; do not trigger optional repeated runs while budget is unknown/critical.
Do not weaken required tests. Never add a paid service or change billing settings.
Shared deployment is enabled through GitHub Actions on passing main pushes; see docs/infrastructure/deployment.md.
Do not invoke deploy.py or hosted migrations from ordinary local feature work.

## Secrets
No hosted secrets in Git, comments, screenshots or frontend bundles.
Local seeded passwords are fake fixtures. Supabase admin seed key is local-only.
Use fixtures/test configuration for auth tests; no production auth bypass environment flags.
