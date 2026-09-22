# SPL-52 — State venue requirements on a request

Owner: Ranveer.

## User story

As an Event Organiser, I want to state my venue requirements on an event request so that a
suitable venue can be identified.

## Acceptance criteria (current)

- Can record preferred room layout, required facilities, accessibility needs, location
  preference and free-text notes.
- Can select a venue from the list of venues.
- All venue requirement fields are optional at creation.
- Saved requirements are visible to the assigned Event Coordinator.

## What changed and why

The AC originally read "can optionally name a preferred venue" (free text, preference only, never
books it). That was superseded: organisers now pick a real venue from the catalogue instead of
typing a name.

- `EventRequest.preferred_venue_name` (free text) replaced by `venue_id`, a nullable foreign key
  to `venues.id` (`ON DELETE SET NULL`). Migration: `s1_event_request_venue_id.py`.
- Backend validation (`_venue_id()` in `event_requests.py`) checks the venue exists and that the
  chosen time actually falls in one of that venue's `operating_slots` — this is enforced
  server-side, not just as a UI hint.
- Frontend: `EventRequestForm.tsx` has a venue `<select>` populated from `GET /api/venues`; picking
  a venue disables the AM/PM/Night slot options that venue doesn't support.

## QA

Redone end-to-end as `QA-SPL-52` (10 test cases across all 4 ACs, ≥2 per AC). All four ACs pass
with no defects, including the AC2 rewrite above. See the QA SPACE report for the full per-test
breakdown and the automated test scripts each case cites
(`backend/tests/test_event_requests.py`, `backend/tests/test_qa_spl51_54.py`).

**Save-draft integration, briefly:** a draft can carry a `venue_id` before a time slot is chosen
(drafts don't run the slot-availability check — that only applies once the request is submitted).
`_draft_attributes()`/`_editable_data()` in `event_requests.py` pass `venue_id` through untouched;
the full slot-vs-venue validation still runs in `_event_request_attributes()`, reused by both the
plain create route and `POST /api/event-requests/drafts/<id>/submit`.
