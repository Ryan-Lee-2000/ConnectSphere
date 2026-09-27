# SPL-77 — CS-E09-S3: Request a venue booking for an approved event

**Epic:** CS-E10 Venue Booking Request (SPL-10)

**Priority:** Highest · **Estimate:** 5 story points

**QA report:** Confluence QS space, `QA-SPL-77` (test cases written before the code).

## User story

As the assigned Event Coordinator, I want to submit a suitable venue-booking request for an approved
event so that Venue Staff can review the proposed venue arrangement.

## Acceptance criteria

1. Only the Event Coordinator assigned to the event can submit a venue-booking request, and only
   while the event is in `Planning`. The system refuses a request from any other user, or for an
   event in any other status, and creates no booking or occupancy.
2. The system refuses the request unless the selected venue passes every suitability check against
   the event's saved requirements (timing and preparation, layout and capacity, required
   facilities, accessibility needs, and preferred location), and the selected layout is supported
   by the venue with a capacity of at least the event's expected attendance. The refusal names each
   failed check.
3. The system derives setup and turnaround slots from the venue's recorded preparation
   requirements: the slot directly before the event slots for setup, and directly after for
   turnaround, where the venue requires them. The request cannot supply or replace these slots.
4. An event can have at most one `Requested` or `Approved` venue-booking request at a time. The
   system refuses a second request for the same event while one is active.
5. Before creating the request, the system checks every event, setup and turnaround slot against
   `Requested` or `Approved` bookings and active operational blocks. If any slot is occupied, the
   system creates no request and no occupancy, and the refusal states the earliest conflicting
   Singapore date and operating slot (for example, "2026-10-14 PM").
6. A created request has status `Requested`. Its Singapore date and event slot(s) come from the
   event's saved date and time, and the request cannot supply different ones. It records the event,
   venue, Singapore date, event slot(s), selected layout, expected attendance, setup and turnaround
   slots, the requesting Event Coordinator, and the request time.
7. A `Requested` request's event, setup and turnaround slots count as occupied in venue
   availability search and in conflict checks for other booking requests.

**Assumption (recorded on the Jira story):** the booked layout may differ from the event's
preferred layout, provided the venue passes the preferred-layout suitability check and the chosen
layout holds the expected attendance. No customer answer requires otherwise (Q111, Q112).

## Interface

`POST /api/event-requests/{event_id}/venue-bookings`, Event Coordinator only.

- Body: exactly `{"venue_id": <int>, "layout": "<name>"}`. Any other key is refused with 400.
- 201: `{"booking": {...}}` with id, event, venue, date, event slots, setup, turnaround, layout,
  expected attendance, status, requester, request time (+08:00), and the stored SPL-89 review
  fields `requires_review`, `review_trigger_block_id`, `review_marked_at`.
- 401 no session · 403 other role · 404 unknown or unassigned event (identical body) · 409 not in
  Planning · 409 `failed_checks` · 409 active booking exists · 409 `conflict: {date, slot}`.

The route follows `docs/development/SPL-77-integration-contract.md`: it flushes a `requested`
booking and calls `claim_venue_occupancy` in the same transaction, rolling back on
`VenueOccupancyConflict`. It locks the event row so concurrent requests for one event serialise.

The Venue search detail panel offers **Request booking** for suitable venues, with a layout picker
limited to the venue's layouts that hold the event's expected attendance.

## Schema

Migration `s2_venue_booking_request` (parent `s2_event_rejection`) adds nullable columns to
`venue_bookings`: `layout`, `expected_attendance`, `booking_date`, `event_slots` (jsonb on
PostgreSQL), `setup_date`, `setup_slot`, `turnaround_date`, `turnaround_slot`,
`requested_by_account_id` (FK accounts), `requested_at`. They are nullable because SPL-83/SPL-89
fixtures create bookings without a request. The one-active-booking rule is enforced under the event
row lock rather than a unique index, so a later multi-session story (Q74) is not precluded.

## Test cases

| ID | AC | Level | Location |
| --- | --- | --- | --- |
| TC-SPL-77-01 | 1, 6 | Server | `backend/tests/test_venue_booking_requests.py` |
| TC-SPL-77-02 | 1 | Server | same file |
| TC-SPL-77-03 | 1 | Server | same file |
| TC-SPL-77-04 | 1 | Server | same file |
| TC-SPL-77-05 | 2 | Server | same file |
| TC-SPL-77-06 | 2 | Server | same file |
| TC-SPL-77-07 | 2 | Server | same file (includes the preferred-layout assumption) |
| TC-SPL-77-08 | 3 | Server | same file |
| TC-SPL-77-09 | 3 | Server | same file |
| TC-SPL-77-10 | 3, 6 | Server | same file |
| TC-SPL-77-11 | 4 | Server | same file |
| TC-SPL-77-12 | 4 | Server | same file |
| TC-SPL-77-13 | 4 | PostgreSQL | `backend/tests/test_venue_booking_requests_postgres.py` |
| TC-SPL-77-14 | 5, 7 | Server | `backend/tests/test_venue_booking_requests.py` |
| TC-SPL-77-15 | 5 | Server | same file |
| TC-SPL-77-16 | 5 | Server | same file |
| TC-SPL-77-17 | 5 | Server | same file |
| TC-SPL-77-18 | 5 | PostgreSQL | `backend/tests/test_venue_booking_requests_postgres.py` |
| TC-SPL-77-19 | 6 | Server | `backend/tests/test_venue_booking_requests.py` |
| TC-SPL-77-20 | 6 | Server | same file |
| TC-SPL-77-21 | 7 | Server | same file |
| TC-SPL-77-22 | 7 | Server | same file |
| TC-SPL-77-23 | 2, 6 | Component | `frontend/src/VenueBookingRequest.test.tsx` |
| TC-SPL-77-24 | 5, 6 | Component | same file |
| TC-SPL-77-25 | 1, 6, 7 | Browser | `e2e/venue-booking-request.spec.ts` |
| TC-SPL-77-26 | Cross-cutting | Browser | same file (390 × 844, keyboard) |

```sh
rg -n "TC-SPL-77" docs backend/tests frontend/src e2e
uv run --frozen pytest backend/tests/test_venue_booking_requests.py -v
pnpm --dir frontend exec vitest run src/VenueBookingRequest.test.tsx
npm run integration        # TC-SPL-77-13, -18 and the migration, on disposable PostgreSQL
npm run check:e2e          # TC-SPL-77-25/-26, with npm start running
```

## Out of scope

Venue Staff approval and rejection (SPL-81, SPL-82), withdrawal (SPL-78), the booking status view
(SPL-79), the pending list (SPL-80), automatic expiry (Q39), notifications, amending a submitted
request (Q45, Q110), and multi-session events (Q74).
