# Shared instructions for all agents

Read README.md, docs/architecture.md, the selected task and docs/requirements.md.
Use the active task's acceptance criteria. Sprint 0 contains no product features. Implement only team-approved product tasks.

## Commands
- npm run doctor / npm run setup / npm start (native Windows and macOS; WSL/Make optional).
- npm run verify: lint, format check, backend unit/API tests, frontend tests, typecheck and build.
- npm run integration: requires INTEGRATION_DATABASE_URL pointing at an EMPTY disposable PostgreSQL.
- npm run check:e2e: requires local Supabase, the Auth test fixture, frontend and API already running.
- Existing make aliases remain supported with their Python/pnpm prerequisites installed.
Report exactly which checks passed, skipped or could not run. Never replace a failing check with a skip.

## Architecture and ownership
React calls Supabase only for auth; business records go through Flask.
Never trust a submitted user/role/organisation ID. Never disable auth to make tests pass.
Application migrations belong only to Alembic. Do not edit a merged migration.
One agent workspace per developer initially. No shared uncommitted directory, DB resets, or ports
between concurrent tasks. Take no unassigned work automatically. Jira is not integrated.

## Small tasks and handoff
Implement only the selected task. Read dependencies first.
Push coherent changes after local checks, not every generated edit.
PRs include requirements, test results, migration notes and open questions.
Humans review and merge. Do not change Sprint scope/estimates/AC without team agreement.
A story is not Done merely because a PR exists. Record review and deployment separately.

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
