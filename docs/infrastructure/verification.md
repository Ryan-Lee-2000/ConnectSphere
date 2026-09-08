# Sprint 0 foundation verification

## Current handoff status (2026-09-08)

Hosted connectivity, Auth, the baseline and GitHub deployment have passed. Actual teammate
Windows/macOS clean-clone checks and failure-recovery rehearsal remain pending; INF-01 is not Done.
Earlier sections below are dated historical evidence, including statuses superseded by activation.

## Foundation review fixes (2026-09-08)

- Local setup validates the database host and passes generated local configuration explicitly to
  migrations and seeding, overriding inherited hosted configuration for those child processes.
  Regression tests use fake URLs and do not contact hosted services.
- Route checks preserve required infrastructure routes while allowing approved additions.
  PostgreSQL checks apply sprint0_base twice and verify its empty schema, then upgrade to the
  current single head twice and verify the revision. Merged migrations were not edited.
- Native Windows verification passed: lint/format, 26 Python tests, two frontend tests,
  typecheck and build. The quick suite skipped one PostgreSQL test as configured.
- The separate PostgreSQL gate passed against a fresh disposable PostgreSQL 17 container.
  Non-fatal warnings: existing pytest cache permissions and Alembic path_separator deprecation.
- Budget reported NORMAL from the dated snapshot, not live telemetry. Browser/Auth, production
  Docker runtime, hosted deployment, macOS and teammate onboarding were not rerun for these fixes.
- Scope, reference-story selection, ownership and Definition of Done remain team decisions.
  These fixes do not mark INF-01 Done. Review and deployment remain separate from local checks.


Date: 2026-09-07. Scope: product-free foundation only. Earlier feature-demo results do not
certify this skeleton and are not included in the team handoff.

Environment: native Windows PowerShell, Windows build 26200 x64, Docker client/server 29.1.3,
Node 24.20.0 (isolated npm cache), Python 3.13.7, uv 0.10.4, pnpm 10.15.1,
Supabase CLI 2.116.0. System Node remains 22.19.0; it was not replaced.
No Git metadata is present, so this is not evidence of a clean clone or a particular commit.

## Passed

Commands used the prefix `npm.cmd exec --yes --package=node@24 -- npm.cmd` on this machine.

- `run setup`: dependency locks installed, new local Supabase project started, ignored configuration
  written, empty sprint0_base Alembic baseline applied, one role-free Auth fixture created.
- `run setup` again: public schema still contains only alembic_version; Auth still contains one
  user with one distinct email. No product tables, business profiles, organisations or roles exist.
- `start`: neutral React shell and Flask API started on 5173/5000.
- `run verify`: Ruff lint and format (15 Python files), 23 Python tests, TypeScript, two frontend
  tests and production frontend build passed. The quick suite deliberately skipped one PostgreSQL test.
- `run integration`: the PostgreSQL test passed separately against a newly created empty database,
  sprint0_integration_20260907. Baseline applied twice and created only the migration ledger.
- Migration generation test: generated and compiled a new revision in a temporary copy, leaving
  the project's migration history untouched.
- `run check:e2e`: one infrastructure smoke test passed, covering browser shell, API/database health,
  anonymous rejection, real local Auth sign-in and server-side validation of the returned token.
- Auth unit tests cover missing/invalid tokens, untrusted submitted identity and upstream outages.
- Source packaging exclusion test passed: credentials, dependency folders, compiled files and reports
  are excluded from the source-only ZIP.
- `run budget`: UNKNOWN, correctly indicating unverified account usage. No CI was triggered.
- Ctrl+C released ports 5000 and 5173; `run stop` stopped only the foundation stack and preserved data.

## Remaining checks and limitations

- macOS, other Windows Docker backends, and actual teammate clean clones remain unverified.
- Hosted authentication, deployment, account-wide budget retrieval and billing controls are not activated.
- There are no product tables, so product-role/organisation authorisation and browser Data API denial
  tests must be added with the first approved tables and stories; they are not claimed as passed here.
- Existing .pytest_cache permissions cause a non-fatal write warning. Cleanup of that directory was
  denied by Windows; it is excluded from Git and the source archive. All test assertions still ran.
- Old local test database volumes were preserved outside the source handoff. The foundation uses
  a distinct Supabase project identity and does not reset other projects.

The team still needs to supply the full authoritative requirements baseline, review this foundation,
choose its first product story/reference estimate, and activate the eventual repository checks.
INF-01 is not Done. No product story has been completed or assigned story points by this work.

## Production Docker verification (2026-09-07)

Passed on the Windows Docker Desktop environment above; no application or Dockerfile changes
were needed. This verifies the production image locally, not hosted deployment.

- Built with `docker build --progress=plain --build-arg VITE_SUPABASE_URL --build-arg VITE_SUPABASE_PUBLISHABLE_KEY -t connectsphere-foundation:production-check .`.
  Build arguments came from local configuration; the publishable key is public browser configuration.
  Docker emitted two SecretsUsedInArgOrEnv warnings for that public key's ARG/ENV names.
- Image ID: `sha256:4cf658e6978b7984e7b9a8b93b8badb664b1e23c409b63d5618cadceaf55e113`.
- Ran twice with loopback binding `127.0.0.1:18000:10000`. Container-side database/Auth URLs
  used `host.docker.internal`; browser-side Auth used `127.0.0.1`.
- Both runs passed: non-root appuser (UID 1000), static frontend HTTP 200, database-backed health
  HTTP 200 with RELEASE_COMMIT, anonymous/invalid token HTTP 401, and actual local Auth token validation.
- Existing Playwright foundation smoke test passed against the production server: 1 passed.
  Invoked pinned pnpm through isolated Node 24 with `playwright test --config artifacts/production-playwright.config.ts`;
  the temporary config selected port 18000, one worker and the existing e2e directory.
- No local `.env` files were found under /app; no seed admin key was supplied to the runtime.
  Runtime logs contained no worker errors or tracebacks.
- Stop/remove/recreate preserved the baseline revision, sole public table alembic_version, and
  the same single Auth fixture. Test containers were removed; unrelated Docker projects were untouched.
- Setup and budget were rerun; setup passed and budget remains UNKNOWN. The separate PostgreSQL
  migration gate was not rerun in this Docker check; its earlier passing evidence is recorded above.

Temporary test harness/config/report live only under ignored artifacts and are excluded from the
source handoff. macOS and genuine clean-clone checks remain outstanding.

## Pre-team source handoff rehearsal (2026-09-07)

- Extracted the source-only ZIP into a new `artifacts/Wednesday rehearsal` directory, exercising
  a path containing spaces. No .env, node_modules or .venv was copied into it.
- Installed pnpm dependencies with `pnpm install --frozen-lockfile` via isolated Node 24 and
  pinned pnpm 10.15.1; passed. Existing machine package caches were reused.
- Ran `npm run verify` through isolated Node 24 from the extracted directory. uv created a new
  project environment. Lint, formatting, 23 Python tests, two frontend tests, typecheck and build
  passed; one PostgreSQL integration test was skipped as designed. The original workspace's
  pytest cache permission warning did not occur in this fresh directory.
- uv reported the inherited VIRTUAL_ENV belonged to the original workspace and correctly ignored
  it. This check used the extraction's own .venv.
- Database setup, browser tests and production Docker were not repeated in this extraction;
  their previous results above apply to the original workspace. No additional stack was started.
- Reviewed native command execution and added macOS AirPlay port-conflict guidance plus
  docs/onboarding/checklist.md for Wednesday, 9 September. Actual macOS execution remains untested.

Readiness: prepared for teammate trials and repository/hosting planning. This is a fresh-source
Windows rehearsal with existing machine tools/caches, not a clean machine or Git-clone certification.

## GitHub Free preparation (2026-09-07)

- Added weekly Dependabot configuration for npm/pnpm, uv, Docker and GitHub Actions.
- CI now calls the same npm verification/integration commands as contributors and builds the
  production Docker image without hosted credentials. Removed the paid-plan private environment
  dependency from the disabled deployment job; future secrets are repository Actions secrets.
- Both workflow and Dependabot YAML parsed successfully with PyYAML in a temporary tool environment.
  This checks YAML syntax, not GitHub service acceptance; actionlint was not installed.
- Local npm run verify passed: lint, formatting, 23 Python tests, two frontend tests, typecheck
  and frontend build. One PostgreSQL test skipped by design; its separate gate, browser checks
  and Docker runtime checks were not rerun for this configuration/documentation change.
  The existing non-fatal pytest cache permission warning remains.
- No GitHub run, Dependabot PR, hosted deployment or account-setting change occurred.
  Budget remains UNKNOWN. The first repository run and remaining Auth/browser CI gate are pending.

## Repository connection (2026-09-07)

Connected the private Ryan-Lee-2000/ConnectSphere repository, preserving its initial README
commit b7960766c8fdc5067d24fe10c6e9331a6836b50e. Earlier no-Git observations above describe
the environment at the time of those tests. Actions was enabled with zero runs, then disabled
before upload because account usage/spending controls remain unverified. Hosting stays disabled.

## Documentation organisation (2026-09-07)

Moved onboarding, development and infrastructure documents into grouped folders; merged
CONTRIBUTING guidance into the development workflow. Tool configuration remains at root.
Updated budget-file lookup, archive rules and references. The first verification attempt failed
formatting due to mixed line endings in the packaging test; formatting was corrected and the
full rerun passed: lint, formatting, 23 Python tests, two frontend tests, typecheck and build.
One PostgreSQL test skipped by design; separate integration, browser and Docker runtime checks
were not rerun for this reorganisation. Existing pytest cache permission warning remains.
Local Markdown links and relocated archive contents passed inspection. Budget reads the moved
file successfully and reports UNKNOWN. GitHub Actions remains disabled; no hosted checks claimed.

## Hosted activation evidence (2026-09-07; recorded 2026-09-08)

- Public endpoint checks returned homepage 200, /api/health 200 with status ok and commit
  8c2d82fdae1a30925aa74ded38df01332bad17de, and anonymous /api/session 401.
- User-provided terminal screenshot: hosted Auth check passed health, missing/invalid token
  rejection, real hosted sign-in and matching Render user identity; session signed out. Earlier
  sign-in attempts failed with invalid_credentials; user identified password-pasting trouble.
  No application fix was required; the earlier email-typo hypothesis was not established.
- User-provided terminal screenshot: target/schema preflight and both baseline applications
  passed at sprint0_base, with no product tables. Local .env and Auth records unchanged.
  These were one-off ignored artifacts/check_hosted_auth.py and check_hosted_baseline.py,
  using hidden prompts, not reusable checks included in the source handoff.
- GitHub [full rehearsal, attempt 2](https://github.com/Ryan-Lee-2000/ConnectSphere/actions/runs/34132621922/attempts/2)
  succeeded for commit 8c2d82fdae1a30925aa74ded38df01332bad17de. Checks job: 1m21s;
  hosted migration and exact-commit Render deployment/health job: 59s.
- Automated coverage: lint/format, 23 Python tests (one PostgreSQL test skipped in the quick
  suite), two frontend tests, typecheck/build, separate PostgreSQL gate and Docker image build.
  Real hosted Auth/browser validation is manual, not a per-PR or per-deploy automated gate.
- GitHub deployment enabled; repository secret names and variables configured. No secret values
  are recorded here. Render Auto-Deploy is intended to remain off per user setup instructions.
- $0 paid Actions budget with Stop usage and alerts confirmed from user screenshots. The usage
  snapshot expires after 24 hours; automated account-wide retrieval remains incomplete.

This documentation update does not rerun hosted sign-in or migrations. It records the existing
passing evidence; it does not claim new teammate tests, product features or failure recovery.
