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
not define booking availability.

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
  `GET /api/event-requests/assigned/<id>` returns the complete read-only request (CS-E06-S1); its
  query joins the assignment, so a missing request and another coordinator's request both answer
  the same 404 and disclose nothing.
  `backend/tests/test_coordinator_concurrency_postgres.py` proves both races with real
  interleaved PostgreSQL transactions under `npm run integration`.
- `event_coordinator_history` appends every assignment and reassignment (previous coordinator,
  new coordinator, who, when) and is read in `changed_at` order.
- Coordinator names come from `accounts.display_name`, which SPL-45 now owns and makes non-null.
  `accounts.is_active` carries the "active user" rule and is added here. **Active** means the
  account may still be given new responsibility: `is_active` defaults to true for every account and
  only an inactive account is withheld from the coordinator picker. Inactivity never removes an
  existing assignment, so an event keeps its coordinator and its history if that account is later
  deactivated. The value is provisioned by the migration default; no story yet gives the team a way
  to edit it, so ownership of `is_active` still needs a decision.
- **Status vocabulary.** CS-E07-S1 owns it in `app.event_statuses`; assignment reads that module
  rather than restating the values, and an import-time check fails loudly if the statuses this
  story depends on ever leave the vocabulary. Assignment leaves the request `submitted`; SPL-70's
  assigned-coordinator action is the first operation to move it to `under_review` and stamp
  `status_changed_at`.
- **Ordering.** The queue is oldest submission first, using CS-E03-S5's `submitted_at`. Requests
  stored before that story carry no submission time and sort last by id, because PostgreSQL and
  SQLite disagree on where NULLs fall.
- **Client organisation.** SPL-45 now supplies `organisations` and a non-null
  `event_requests.organisation_id`, so the queue names the requesting client organisation.

## Event review transitions

SPL-70 introduces the first explicit workflow action at
`POST /api/event-requests/<id>/begin-review`. The route verifies that the caller is the currently
assigned Event Coordinator; clients never submit a target status. `event_review.TRANSITION_RULES`
is the server-owned before/after policy that later workflow actions extend.

`transition_event_status()` conditionally updates the expected current status and appends an
`event_status_history` row in the caller's transaction. The history records the named action,
previous and resulting statuses, actor, and timestamp. A competing or repeated action updates no
row and therefore writes no audit evidence.

SPL-65 adds `request_clarification` (`under_review` to `returned_for_clarification`) to the same
rules at `POST /api/event-requests/<id>/request-clarification`. The route also appends a
`clarification_requests` row (message, author, time) in the same transaction, so each request is
kept as history. The organiser reads the messages with the request; replying is a later story.

## Event-request submission foundation

SPL-51 adds an additive `event_requests` aggregate with zero or more child
`equipment_requirements`. Flask derives the organiser account from the verified session, creates
the aggregate transactionally, and applies record-level read scoping: Event Organisers see their
own requests and Event Coordinators see all submitted requests. Client-submitted account,
organisation and status identifiers are rejected.

The aggregate carries nullable venue, facilities, accessibility, equipment and registration
preferences so adjacent Sprint 1 stories can share one migration chain. Those columns are a data
contract only; they do not implement bookings, reservations, registration, drafts or workflow
transitions. Both tables use RLS with no browser-role grants; business access remains exclusively
through Flask.

## Client-organisation event isolation

SPL-45 adds the minimal trusted organisation relationship needed for same-client visibility:

- `organisations` identifies a client and is protected by RLS with no browser-role grants.
- An Event Organiser's `accounts.organisation_id` is application-owned membership data.
- Every event request stores the organisation derived from its authenticated organiser's account;
  callers cannot select or override that organisation.
- Dedicated organisation-event list and detail operations include non-draft events for the trusted
  organisation. A cross-client identifier and a draft identifier both produce the same generic
  not-found response.
- The existing own-request API retains its narrower draft-management contract.

## Venue preparation occupancy

SPL-87 establishes the shared, database-free rule for turning dated event slots into complete venue
occupancy. `app.slots.derive_venue_occupancy()` orders event slots using the fixed AM, PM and Night
sequence, derives at most one directly adjacent setup and turnaround slot from a venue's catalogue
requirements, and rolls adjacency across Singapore calendar days. Its immutable result identifies
each slot as event, setup or turnaround occupancy.

The calculation deliberately creates no booking record and exposes no endpoint or interface.
Venue search, booking, calendars and conflict prevention consume this rule in their own approved
stories, preventing each workflow from implementing a different interpretation of preparation time.

## Venue operational unavailability

SPL-89 adds `venue_operational_blocks` as the audited Venue Staff input for dates and operating
slots when a catalogue venue cannot be used. Blocks use an inclusive Singapore date range, one or
more of that venue's configured AM/PM/Night slots, and a required reason. Removal is a soft lifecycle
transition: `removed_by_account_id` and `removed_at` preserve who removed the block and when, while
active availability reads ignore removed rows.

`operational_block_for_slot()` is the shared read boundary for venue search, suitability and
conflict-prevention stories. It deliberately centralises the active/date/slot rule instead of asking
each consumer to interpret block records itself. The table has RLS enabled and grants revoked from
browser roles; Venue Staff create, list and remove blocks only through Flask.

With SPL-83's shared booking occupancy available, block creation also marks every intersecting
Requested or Approved booking for review in the same transaction. The marker records the triggering
block, trusted Venue Staff actor and timestamp without changing booking status or details. Terminal
and non-overlapping bookings remain unmarked. Clearing markers, notifications and a review queue are
separate future work; SPL-77 and SPL-81 consume the shared model for their own workflows.

Booking claims and block creation acquire the same ordered PostgreSQL transaction advisory locks
for every affected venue/date/slot before reading or writing availability. The shared lock prevents
a booking transaction and a block transaction from both passing their separate table checks against
stale committed state. After waiting, the second transaction sees either the committed block and
refuses the booking or the committed occupancy and marks that booking for review.

## Venue booking conflict boundary

SPL-83 adds the minimal shared `venue_bookings` aggregate and active
`venue_booking_occupancy` claims needed before the request and approval interfaces exist. A claim
derives all event, setup and turnaround slots through SPL-87, refuses any matching active SPL-89
operational block, and writes the complete batch in a nested transaction. A database uniqueness
constraint on venue, Singapore date and operating slot prevents two bookings from retaining the
same claim. The shared transaction advisory locks described above coordinate booking occupancy with
operational blocks, which live in a different table and cannot share that uniqueness constraint.

Requested and Approved bookings own occupancy rows. Moving a booking to Rejected, Withdrawn or
Cancelled deletes its active claims, while moving to Approved rechecks operational blocks before
changing status. Conflict errors identify the occupied date and slot. SPL-77 and SPL-81 will call
this module inside their own transactions; they remain responsible for rolling back their booking
write when the policy refuses it. Product tables retain RLS with no browser-role grants.

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
