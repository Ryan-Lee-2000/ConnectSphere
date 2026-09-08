# Shared demo deployment

Status recorded 2026-09-08: GitHub deployment enabled and successfully rehearsed.

- Repository: https://github.com/Ryan-Lee-2000/ConnectSphere (private, personal GitHub Free)
- Demo: https://connectsphere-mmay.onrender.com
- Render service: srv-dafcmr0n74is739ekup0; Docker, Singapore, Free instance
- Supabase project: kwsjxsigdbcvxxiiozvt; hosted Auth and PostgreSQL
- GitHub variable DEPLOY_ENABLED=true. Keep Render's own Auto-Deploy off to avoid duplicate deploys.

## What happens after a merge

A push to main runs verification, the disposable PostgreSQL migration test and a Docker build.
Only after those pass does the deploy job apply Alembic migrations to hosted Supabase, ask Render
for the exact Git commit, poll deployment status, then check /api/health for status ok and that
same commit. PRs run checks without deployment. Documentation merges also trigger deployment.
Render rebuilds the selected commit; this is not promotion of the immutable image built in CI.

The first successful full rehearsal used commit 8c2d82fdae1a30925aa74ded38df01332bad17de:
[Verify run, attempt 2](https://github.com/Ryan-Lee-2000/ConnectSphere/actions/runs/34132621922/attempts/2).
Checks took 1m21s and deployment 59s. See [verification evidence](verification.md), including
separate user-run hosted Auth and baseline checks. Real Auth/browser tests are not automated
CI gates. Failure recovery and teammate/macOS onboarding remain untested.

## Configuration inventory

GitHub repository Actions secrets (values never belong in source):
- RENDER_API_KEY
- DEMO_MIGRATION_DATABASE_URL

GitHub repository variables:
- RENDER_SERVICE_ID=srv-dafcmr0n74is739ekup0
- DEMO_URL=https://connectsphere-mmay.onrender.com
- DEPLOY_ENABLED=true

Render environment variables: DATABASE_URL, SUPABASE_URL, SUPABASE_PUBLISHABLE_KEY,
VITE_SUPABASE_URL and VITE_SUPABASE_PUBLISHABLE_KEY. Only the two VITE values belong in
frontend build arguments. Database credentials stay server-side. The session-pooler URL uses
postgresql+psycopg:// with SSL required, port 5432 and the project-specific pooler username.
Never copy a local .env into Render or run the local seed against cloud.

Render settings: main branch, repository root, Docker context '.', Dockerfile './Dockerfile',
health path /api/health, no Docker command override, no pre-deploy command. The Dockerfile starts
Gunicorn. RENDER_GIT_COMMIT identifies the deployed version. Migrations do not run on app startup.
Hosted demo accounts are provisioned separately; the verification account has no business role.

## Review, budget and recovery

Private GitHub Free does not enforce the team's PR/review rule or provide environment approvals.
Repository workflow editors must be trusted with how repository secrets are used. Humans review
and merge; agents do not deploy from ordinary local feature work.

The user supplied account screenshots showing a $0 paid Actions budget with Stop usage enabled
and included-usage alerts on. Usage is a dated manual snapshot, not live billing telemetry;
run npm run budget and follow [budget guidance](ci-budget.md). Do not enable paid services.

Set DEPLOY_ENABLED=false to prevent future GitHub deployment jobs. This does not cancel an
already running job. Keep Render Auto-Deploy off. Inspect a failure before retrying: a failed
application deploy may follow a successful migration. An app rollback does not undo a migration.
Use reviewed additive/backwards-compatible migrations while the previous app is live; never
merge destructive migrations into this automatic path. Redeploy a compatible commit through a
reviewed main revert and review data repair separately. Failure recovery has not been rehearsed.

The demo uses free hosting with no uptime guarantee. Check it before presentations; data lives
in Supabase rather than Render's ephemeral disk. No paid domains, schedulers or workers are configured.
Product-table RLS, role/organisation permissions and Data API denial tests must accompany future
approved tables; the current foundation has no product tables.

## Local production checks

Docker Desktop containers reach host Supabase through host.docker.internal; browser URLs stay
on 127.0.0.1. Bind local production test ports to loopback and preserve database volumes when
removing test app containers. Local checks do not certify macOS or a fresh teammate clone.

Sources: https://render.com/docs/free and https://api-docs.render.com/reference/create-deploy
