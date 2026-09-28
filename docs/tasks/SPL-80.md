# SPL-80 — CS-E10-S2: View pending venue-booking requests

**Epic:** CS-E10 Venue Booking Request (SPL-10)

**Assignee:** Clive Lim

**QA report:** Confluence QS space, `QA-SPL-80` (test cases written before the code).

## User story

As a Venue Staff member, I want to view pending venue-booking requests so that I can identify
requests awaiting review.

## Acceptance criteria

1. Venue Staff can retrieve an organisation-wide list of venue-booking requests in Requested status.
2. Each list item identifies the event, requested venue, Singapore date, event slot(s), preparation
   slot(s), selected layout, expected attendance, requesting Event Coordinator, and request time.
3. Venue Staff can open a pending request to view the event information required for a booking
   decision.
4. Personal attendee information that is not required for the decision is not displayed.
5. Requests in Approved, Rejected, or Withdrawn status are not included in the pending list.
6. When no requests are pending, the system returns a clear empty state.

## Interpretation of the acceptance criteria

Three phrases in the ACs needed a decision before the tests could be written. Each is recorded here
so the test cases have a single, checkable meaning.

**"Organisation-wide" (AC1) means the whole venue operator's estate, not one client organisation.**
Venue Staff work for the venue operator, not for a client: the seeded Venue Staff account holds no
`organisation_id`, and SPL-89's operational blocks and SPL-81's approval are likewise scoped by
venue, never by client organisation. The pending list is therefore every Requested booking across
every client organisation, which is what a venue operator's review queue has to be.

**"Personal attendee information" (AC4) is handled as an allowlist, not a blocklist.** The event
payload lists the fields a venue decision needs and nothing else, so a field added to
`event_requests` later cannot leak by default. Registration fields (`registration_required`,
`registration_notes`) are the attendee-facing data on the event and are excluded deliberately:
whether and how attendees register does not bear on whether the venue fits. The organiser's account
identity is excluded for the same reason — the requesting coordinator is already named by AC2, and
that is the person Venue Staff would contact about the request.

**AC3 extends the existing review view rather than adding a second one.** SPL-81 already serves
`GET /api/venue-bookings/{id}` to Venue Staff with `event` as `{id, name, status}`. That is enough
to approve against, but not enough to *decide* against, which is what AC3 requires. SPL-80 therefore
widens that one payload instead of introducing a competing detail endpoint. See **Integration**.

## Interface

### The pending queue (AC1, AC2, AC5, AC6)

`GET /api/venue-bookings/pending` — Venue Staff only (401 unauthenticated, 403 any other role).

Ordered oldest request first, so the longest-waiting request is at the top of the queue. Bookings
created by fixtures without a request time sort last by id rather than first, because NULL ordering
differs between PostgreSQL and SQLite.

```json
{
  "requests": [
    {
      "id": 12,
      "event": { "id": 7, "name": "Coastal Forum" },
      "venue": { "id": 2, "name": "Harbour Hall" },
      "date": "2026-10-14",
      "event_slots": ["PM"],
      "setup": { "date": "2026-10-14", "slot": "AM" },
      "turnaround": { "date": "2026-10-14", "slot": "NIGHT" },
      "layout": "theatre",
      "expected_attendance": 150,
      "requested_by": { "id": "…", "name": "Casey Lim" },
      "requested_at": "2026-09-28T09:00:00+08:00",
      "requires_review": false
    }
  ],
  "count": 1
}
```

With nothing pending: `{"requests": [], "count": 0, "message": "No venue-booking requests are
awaiting review."}` (HTTP 200).

### The decision view (AC3, AC4)

`GET /api/venue-bookings/{booking_id}` — SPL-81's route, with `event` widened from `{id, name,
status}` to the decision allowlist:

```json
{
  "event": {
    "id": 7, "name": "Coastal Forum", "status": "planning",
    "organisation": { "id": 3, "name": "Northstar Community Partners" },
    "purpose": "Community consultation", "description": "…",
    "proposed_date": "2026-10-14", "start_time": "13:00", "end_time": "17:00",
    "expected_attendance": 150, "preferred_room_layout": "theatre",
    "required_facilities": ["Projector"], "accessibility_needs": ["Step-free access"],
    "facilities_notes": "…", "location_preference": "…", "venue_notes": "…"
  },
  "booking": { "…": "unchanged, as SPL-77 serialises it" },
  "review": { "…": "unchanged, SPL-89's stored marker" }
}
```

`registration_required`, `registration_notes` and the organiser's identity are **not** serialised
(AC4). `app.venue_booking_queue.decision_event_details` is the single place that builds this
payload, so the list and the decision view cannot drift apart.

### Interface (UI)

- `/workspace/booking-requests` — Venue Staff only. The pending queue, oldest first, each row
  opening SPL-81's existing review page at `/workspace/venue-bookings/{id}`. An explicit empty state
  when nothing is pending.
- SPL-81's review page shows the widened event details under an "Event details" section.

## Schema

None. SPL-80 is read-only: no migration, no new table, no new column. Every field it returns is
already stored by SPL-77 (the request), SPL-83/SPL-87 (the derived preparation slots recorded on the
booking) and SPL-89 (the review marker).

## Integration

**Touches other stories' code/tests.** SPL-81's `GET /api/venue-bookings/{id}` now calls
`decision_event_details` for its `event` key. The change is additive — every key SPL-81 returned is
still returned with the same value — but `TC-SPL-81-21` asserts on `body["event"]` by exact
equality, so that one assertion is widened in `backend/tests/test_venue_booking_approval.py`.
No SPL-81 behaviour changes.

**For later stories.** SPL-82 (reject) acts on a booking reached from this queue; the queue needs no
change when it lands, because a Rejected booking leaves Requested status and AC5 already excludes
it. The same is true of SPL-81's approvals and SPL-78's withdrawals, which is what `TC-SPL-80-07`
proves.

## Test cases

| ID | AC | Level | Location |
| --- | --- | --- | --- |
| TC-SPL-80-01 to -09 | 1, 2, 4, 5, 6 | Server | `backend/tests/test_venue_booking_queue.py` |
| TC-SPL-80-10 to -12 | 3, 4 | Server | `backend/tests/test_venue_booking_queue.py` |
| TC-SPL-80-13 to -16 | 1, 2, 5, 6 | Component | `frontend/src/PendingBookingRequests.test.tsx` |
| TC-SPL-80-17 | 3 | Component | `frontend/src/VenueBookingReview.test.tsx` |
| TC-SPL-80-18 | 1–3, 6; cross-cutting | Browser | `e2e/pending-booking-requests.spec.ts` |

```sh
rg -n "TC-SPL-80" docs backend/tests frontend/src e2e
uv run --frozen pytest backend/tests/test_venue_booking_queue.py -v
npm run verify
npm run check:e2e          # TC-SPL-80-18, with npm start running
```

## Out of scope

Approving, rejecting or changing a request from the list (SPL-81, SPL-82); notifications; the
Event Coordinator's and Organiser's own views of booking status (SPL-79).
