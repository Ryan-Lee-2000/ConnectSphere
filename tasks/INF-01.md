# INF-01: Prove Sprint 0 foundation onboarding

Status: In verification; not Done.
Scope revised at the user's direction: share a product-free project skeleton, not a feature demo.
Goal: a teammate can set up and verify the foundation without Ryan on a call.

## Acceptance criteria

- Source handoff contains no implemented product story, sample domain schema, business-role
  fixtures, local credentials, compiled output or historical test reports.
- Native Windows PowerShell and macOS Terminal use npm run setup and npm start; Make/WSL are optional.
- Setup installs locked dependencies, starts isolated local Supabase, generates ignored local
  configuration and applies the empty Alembic baseline. No manual Python/pnpm install is needed.
- Rerunning setup preserves the single local Auth fixture without duplicates; no business records
  or roles are created. No other developer's database or Docker project is reset.
- The shell reaches Flask/PostgreSQL. Real local Auth tokens are validated by /api/session;
  missing/invalid tokens and Auth outages fail closed.
- npm run verify passes. The separate PostgreSQL gate verifies baseline migration and rerun
  on a new disposable database. Browser smoke checks pass against local services.
- Ctrl+C releases both development-server ports; npm run stop preserves local Supabase data.
- Production Docker image build/non-root runtime/health checks are recorded separately.
- Record actual commands, OS/runtime versions, results, problems and fixes on each platform.

A baseline estimation story is not selected or implemented by this task. It will be agreed by
team members later and delivered through the normal workflow. Review, merge and deployment
are separate evidence; no story becomes Done merely because a PR exists.
