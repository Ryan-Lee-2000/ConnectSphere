# SPL-56 — Save an event request as a draft

Owner: Daniel Seow. Frontend ownership confirmed by Ryan.

## User story

As an Event Organiser, I want to save an incomplete event request as a draft so that I can finish it later.

## Acceptance criteria

- Can save at any point with only the event name filled (proposed minimum).
- Saved request has status Draft.
- The draft is visible only to its creator (see CS-E01-S3).
- Saving a draft notifies nobody.

## Dependencies and boundaries

- Builds on SPL-51's merged `event_requests` aggregate and read/create API.
- The event-name minimum remains a team proposal until confirmed.
- Ryan confirmed Daniel owns the permanent Event Organiser request frontend. The assignee confirmed
  that this change should include the complete-request submission UI using SPL-51's existing API.
- SPL-57 owns reopening, editing, resaving, last-saved time and submission from a draft.
- SPL-58 owns deletion.
- Daniel selected `POST /api/event-requests/drafts` for draft creation. This preserves the
  existing submitted-request POST contract. Shared schema/API changes require teammate review.
- No client-supplied organiser, organisation or status selects ownership or access.

## Implementation and verification

- An Alembic migration permits name-only drafts while retaining complete-field checks for submitted rows.
- The create route sets owner and draft status from the authenticated session and does not call a notification service.
- Drafts remain visible only to their creator, including when an account also has the Coordinator role.
- Focused API and frontend tests cover name-only creation, ownership and status.
- After integration with SPL-55 and SPL-63, `npm run verify`: 131 backend tests passed
  (one PostgreSQL test skipped in the quick suite), 58 frontend tests passed, and lint,
  format, typecheck and build passed.
- `npm run integration`: one PostgreSQL migration test passed against an empty disposable database.
- The integrated browser draft flow must be rerun before final QA sign-off.

Sources: SPL-56 Jira acceptance criteria supplied by the assignee; SPL-51 backend handoff in `docs/development/SPL-51.md`.
