# Sprint 0 architecture boundaries

See the [C4 model](architecture/c4.md) for context, containers, deployment views, trade-offs
and links from the design to implementation and tests.

One monorepo: React + TypeScript + Vite; Flask application factory; SQLAlchemy + Alembic;
local Supabase PostgreSQL and Auth. Dependencies are locked in uv.lock and pnpm-lock.yaml.
Native Windows and macOS use npm commands. Make and WSL are optional.

## Infrastructure provided

- The React shell calls GET /api/health through the Vite proxy (or same-origin Flask in production).
- /api/health executes SELECT 1 and returns 503 when PostgreSQL is unavailable.
- /api/session validates a Bearer token using Supabase /auth/v1/user and returns its verified ID.
  It is an infrastructure probe, not a user profile or business authorisation implementation.
- Missing/invalid tokens fail with 401; Auth outages fail closed with 503.
- Application metadata has no domain tables. The sprint0_base migration establishes only the
  Alembic revision ledger. Add reviewed models/migrations when product stories require them.
- One local-only Auth fixture supports real authentication smoke tests. It has no business role.

## Boundaries for future stories

React may call Supabase directly only for authentication. All business operations go through Flask.
The server must derive identity, roles and organisation access from trusted records. A valid
session is not sufficient authorisation for an operation. Never trust submitted role/organisation IDs.

When adding application tables, enable RLS and revoke browser-role access through Alembic.
Add permission, organisation-isolation and Data API denial tests with those tables. Sprint 0
has no product tables to protect; it does not claim that Release 1 authorisation is implemented.
Alembic alone owns application migrations. Never rewrite a merged migration.

Understand the full requirements before choosing domain relationships, including multiple roles
per user and multi-session events. Do not create a speculative complete schema in Sprint 0.
Business state transitions, assignment, booking and change handling belong to approved stories.

## Verification and delivery

SQLite supports fast infrastructure tests; PostgreSQL migration checks remain a separate gate.
The browser smoke test proves the shell, API/database connectivity and actual local Auth token
validation. It is not a product story or an estimation benchmark.

Flask serves the built React files in the production Docker image. The enabled deployment
workflow rebuilds the verified commit on Render; this is not promotion of an immutable CI image.
Hosted Auth, the empty baseline and the main deployment path have been verified. No paid services,
hosted migrations or deployments are part of ordinary local development.
