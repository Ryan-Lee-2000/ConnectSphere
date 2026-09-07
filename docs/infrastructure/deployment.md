# Activate shared demo after creating accounts

Status: DISABLED. GitHub remote: https://github.com/Ryan-Lee-2000/ConnectSphere.
No Render service or Supabase cloud project is configured. Repository Actions is disabled pending budget review.
Ordinary contributors eventually only merge reviewed PRs and read the Verify workflow summary.

## Dependency maintenance and CI/CD

Dependabot proposes dependency-update pull requests; GitHub Actions runs verification and the
gated deployment workflow. They serve different purposes and can be used together.
See [Dependabot version updates](https://docs.github.com/en/code-security/concepts/supply-chain-security/dependabot-version-updates).

The committed .github/dependabot.yml prepares weekly updates for pnpm, uv, Docker and Actions,
with minor/patch grouping and one open version-update PR per ecosystem. It becomes active when
uploaded to the default branch. Automatic merging is not configured. See docs/infrastructure/repository-setup.md.
Dependency PRs must pass the same required checks as other changes; budget remains UNKNOWN.

## Local production image

The Windows production build and runtime passed on 2026-09-07; see docs/infrastructure/verification.md for evidence.
Local Docker Desktop containers must use host.docker.internal to reach Supabase on the host.
Keep browser-facing Supabase URLs on 127.0.0.1. Pass database credentials only at runtime;
only the Supabase URL and public publishable key belong in frontend build arguments.
Bind the local production test port to 127.0.0.1. Use the existing foundation browser smoke test
against that port, then remove the test app container while retaining Supabase data.
This check does not activate hosting or prove macOS/clean-clone acceptance.

## Hosted activation

Maintainer setup:
1. Follow docs/infrastructure/repository-setup.md for Ryan's private personal GitHub Free repository.
   Confirm spending controls before uploading/enabling workflows and confirm course access requirements.
2. Use the documented manual PR/review rule. Private GitHub Free does not enforce branch
   protection or provide deployment environments. All collaborators with write access must be trusted.
3. Configure $0 paid usage controls in billing before enabling Actions.
4. Create Supabase Free project and Render Free Docker web service linked to main.
   Disable Render automatic deploys. Use default free URL; select no paid resources.
5. Set Render build arguments VITE_SUPABASE_URL and VITE_SUPABASE_PUBLISHABLE_KEY via its
   supported Docker build environment configuration. Set the same SUPABASE_URL and
   SUPABASE_PUBLISHABLE_KEY for Flask at runtime, plus server-only DATABASE_URL.
   Render's RENDER_GIT_COMMIT is used by /api/health to identify the deployed version.
6. Configure GitHub repository Actions secrets RENDER_API_KEY and DEMO_MIGRATION_DATABASE_URL.
   Configure repository variables RENDER_SERVICE_ID and DEMO_URL.
   Use the Supabase dashboard's compatible connection string (SSL; session pooler if IPv4 needs it);
   prefix postgresql+psycopg:// for SQLAlchemy. Keep migration/runtime credentials server-side.
7. Provision hosted demo accounts separately. NEVER run the local seed against cloud.
8. Test Docker build/start locally, CI PostgreSQL gate, real hosted auth, Data API denial for any product tables added later, and migration
   compatibility. Enable repository variable DEPLOY_ENABLED=true only after these pass.

On subsequent passing main pushes: migrations, exact-commit deploy, status poll, health/commit check.
The deployment script polls at 10-second intervals, with bounded timeout.
No migration runs in each Gunicorn worker or on app startup.

Migration policy: deploy additive/backwards-compatible changes while the old app is live.
Do not merge destructive migrations through this automatic path.
Recovery: inspect failed step. An app rollback does not undo a migration. Redeploy a known
compatible commit through a reviewed main revert; review any data repair separately.

Cost limitations: one free demo, no guaranteed uptime. Wake it before a presentation.
Data stays in Supabase, not Render's ephemeral disk. No paid domains, schedulers or background
workers. Actual external notification email is not implemented by the foundation.
Sources: https://render.com/docs/free and https://api-docs.render.com/reference/create-deploy
