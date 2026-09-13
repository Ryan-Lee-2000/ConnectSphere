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
- The `sprint0_base` migration establishes only the Alembic revision ledger. Approved product
  migrations now add the minimal account-role authorization model described below.
- One local-only Auth fixture supports real authentication and role smoke tests. Its application
  account holds Event Organiser and Attendee roles so multi-role evaluation is reproducible.

## Account-role authorization

CS-E01-S2 adds the smallest trusted application model needed for reusable role authorization:

- `accounts.id` is the verified Supabase Auth user UUID; client-submitted account identifiers never
  select the current account.
- `account_roles` uses `(account_id, role)` as its key, allowing one account to hold multiple roles
  while limiting stored values to the six confirmed Release 1 roles.
- Every authenticated API request loads role assignments from the application database into the
  request context after Supabase identity verification.
- API operations must explicitly opt into authenticated-only access or declare one or more permitted
  roles. An operation with no policy is refused before its handler executes.
- A role-protected operation succeeds when the trusted account holds at least one declared role.
  Refused requests return only a generic error and cannot execute the protected handler.
- `GET /api/account/roles` returns only the signed-in account's trusted roles. It has no account-ID
  selector and ignores client claims as authorization evidence.
- Product tables have PostgreSQL row-level security enabled and browser roles receive no table
  privileges. React continues to obtain business data only through Flask.

Sprint 1 maps venue catalogue functions onto that trusted foundation: Venue Staff may create and
maintain venue profiles and room layouts; Event Coordinators may browse the catalogue and details.
The browser does not submit a role, user ID or organisation ID to choose this access. Sprint 1 does
not define organisation isolation, ownership, coordinator assignment, booking availability or a
role-switching interface.

## Boundaries for future stories

React may call Supabase directly only for authentication. All business operations go through Flask.
The server must derive identity, roles and organisation access from trusted records. A valid
session is not sufficient authorisation for an operation. Never trust submitted role/organisation IDs.

When adding application tables, enable RLS and revoke browser-role access through Alembic.
Add permission, organisation-isolation and Data API denial tests with those tables. The original
Sprint 0 baseline had no product tables; S2 now establishes role authorization, while later stories
remain responsible for their own function and record-level rules.
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
