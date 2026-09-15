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
not define organisation isolation, ownership, booking availability or a role-switching interface.

## Coordinator assignment

CS-E05-S1 to S3 (SPL-59 to SPL-61) let Event Operations Managers find submitted requests without a
coordinator, assign one and reassign later, on top of SPL-51's `event_requests` aggregate. Every
operation requires the Event Operations Manager role through `require_roles`.

- `event_coordinator_assignments` holds one row per request, keyed by `event_request_id`. The key
  rejects a
  second concurrent assignment. Reassignment applies only while the row still names the coordinator
  that was read **and** the event is still in a reassignable status; both conditions live in the
  statement, so a concurrent terminal transition cannot slip between the read and the write.
  `is_assigned_coordinator()` is the check later coordinator-only operations must reuse.
  `backend/tests/test_coordinator_concurrency_postgres.py` proves both races with real
  interleaved PostgreSQL transactions under `npm run integration`.
- `event_coordinator_history` appends every assignment and reassignment (previous coordinator,
  new coordinator, who, when) and is read in `changed_at` order.
- `accounts.display_name` and `accounts.is_active` provide coordinator names and the "active user"
  rule. **Active** means the account may still be given new responsibility: `is_active` defaults to
  true for every account and only an inactive account is withheld from the coordinator picker.
  Inactivity never removes an existing assignment, so an event keeps its coordinator and its
  history if that account is later deactivated. Values are provisioned by the local seed and by
  the migration default; no story yet gives the team a way to edit them, so ownership of both
  columns needs a decision before these stories are called complete.
- **Status vocabulary.** CS-E07-S1 owns it in `app.event_statuses`; assignment reads that module
  rather than restating the values, and an import-time check fails loudly if the statuses this
  story depends on ever leave the vocabulary. Assignment is the first operation to move a request
  off `submitted`, so it stamps `status_changed_at` as well, which CS-E07-S1 reads.
- **Ordering.** The queue is oldest submission first, using CS-E03-S5's `submitted_at`. Requests
  stored before that story carry no submission time and sort last by id, because PostgreSQL and
  SQLite disagree on where NULLs fall.
- **Still pending.** `organisation_id` stays null until SPL-45 introduces client organisations, so
  the queue shows no organisation name yet.

## Event-request submission foundation

SPL-51 adds an additive `event_requests` aggregate with zero or more child
`equipment_requirements`. Flask derives the organiser account from the verified session, creates
the aggregate transactionally, and applies record-level read scoping: Event Organisers see their
own requests and Event Coordinators see all submitted requests. Client-submitted account,
organisation and status identifiers are rejected.

The aggregate carries nullable venue, facilities, accessibility, equipment and registration
preferences so adjacent Sprint 1 stories can share one migration chain. Those columns are a data
contract only; they do not implement bookings, reservations, registration, drafts or workflow
transitions. `organisation_id` is deliberately nullable and remains `NULL` until an approved
organisation model can derive it server-side. Both tables use RLS with no browser-role grants;
business access remains exclusively through Flask.

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
