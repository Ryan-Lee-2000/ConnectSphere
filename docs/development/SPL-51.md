# SPL-51 — Shared event-request backend contract

Owner: Ranveer. Implementation support: Ryan while the owner is blocked.

## User outcome

As an Event Organiser, I want to create an event request with the event's core details so that
ConnectSphere knows what I need.

## Approved acceptance criteria

- Accept event name, purpose, description, proposed date, start time, end time and expected
  attendance.
- Require name, purpose, proposed date, start time, end time and expected attendance.
- Refuse a past proposed date and a start time that is not before the end time.
- Store expected attendance once at event level as a positive whole number.
- Return the venue slots intersected by the chosen times: AM (07:00–12:00), PM
  (13:00–18:00) and Night (19:00–24:00).
- Link the request to the organiser's client organisation automatically.

## Shared schema/API contract supplied by the story owner

The additive migration creates `event_requests` and child `equipment_requirements`. It includes
nullable preference fields needed by the adjacent venue, equipment and registration stories so
those teammates can build on one table rather than create competing migrations.

`POST /api/event-requests` is restricted to Event Organisers. The server derives
`organiser_account_id` from the verified caller and creates equipment lines in the same
transaction. `GET /api/event-requests` and `GET /api/event-requests/<id>` permit Event Organisers
and Event Coordinators. Organisers see only their own requests; Coordinators see all. An Organiser
opening another Organiser's identifier receives 404.

React continues to use Supabase only for authentication. Both new tables enable RLS and revoke
all table and sequence privileges from PUBLIC, `anon` and `authenticated`; Flask owns business
access through the existing trusted-role boundary.

## Explicit limitations and follow-up

- At the time SPL-51 was delivered, the account model had no client-organisation relationship and
  `organisation_id` remained `NULL`. SPL-45 now supersedes that temporary boundary by deriving a
  required organisation from trusted account membership; request input is still never trusted.
- The only current state is `submitted`. Adding draft or workflow states requires an additive
  migration to extend the database check; this migration must never be rewritten after merge.
- The slot calculation is display-only and does not create or imply a venue booking.
- Multi-day/multi-session events, PATCH, DELETE, drafts, bookings, assignments and status
  transitions are outside this batch.
- Preference columns do not complete the later venue, equipment or registration stories; those
  stories still own their interfaces and acceptance behaviour.

Sources: SPL-51; Week 4 core #2; Q50, Q72, Q107 and Q119; schema/API handoff supplied by Ranveer.

## Follow-up: venue/slot picker, redone QA, and save-draft integration

Owner: Ranveer.

- The free-text `start_time`/`end_time` inputs were replaced with an AM/PM/Night slot picker
  (`frontend/src/slots.ts`) tied to a real venue selection (`venue_id`, see SPL-52). The backend
  still stores concrete `start_time`/`end_time` (derived from the chosen slot) and validates that
  the selected venue actually operates in that slot (`_venue_id()` in `event_requests.py`).
- Fixed a genuine client/server contract defect found during QA: the live form sent equipment
  lines as `equipment_lines`, the backend only accepted `equipment_requirements`, so every real
  submission with equipment failed with a 400. Both sides now agree on `equipment_requirements`.
- QA redone end-to-end under the `QA-SPL-51-0XX` naming convention (13 test cases across all 6
  ACs, ≥2 per AC, each citing an exact automated test): see `QA-SPL-51` in the QA SPACE. AC1–AC5
  pass with no defects.
- AC6 (automatic organisation link) was blocked pending SPL-45 (view events in my client
  organisation), which added the `Organisation` entity and `Account`→`Organisation` relationship.
  SPL-45 merged to `main` at `deaf97f` (2026-09-19) and has now been merged into this branch.
  Re-verified end to end: `backend/tests/test_event_requests.py` asserts a created event's
  `organisation_id` is a server-derived, non-null integer (never accepted from request input),
  and `backend/tests/test_organisation_events.py` covers organisation scoping, draft exclusion and
  cross-organisation refusal. Full `npm run verify` passes (164 backend tests, 53 frontend tests,
  typecheck, build). AC6 now passes; no defects found.
- One test case, `QA-SPL-51-002`, is reserved for a manual full browser walkthrough recording,
  still pending.

**Save-draft integration, briefly:** SPL-56/57/58 (draft save/reopen/submit/delete) were merged in
from `main` on top of this rework. `EventRequestForm.tsx` now has a "Save as draft" action
(`POST /api/event-requests/drafts`, only the event name required) alongside the existing full
submit. Opening a draft (`draftId` prop) fetches and prefills every field, including the chosen
venue and slot. Once a draft exists, the same "Submit event request" button posts to
`POST /api/event-requests/drafts/<id>/submit` instead of the plain `POST /api/event-requests`; a
fresh submission that was never saved as a draft is unaffected and still goes straight to the
plain create endpoint. See `docs/development/SPL-56.md`/`SPL-57.md`/`SPL-58.md` for the feature
itself and its own acceptance criteria.
