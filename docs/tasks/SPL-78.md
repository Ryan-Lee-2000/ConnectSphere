# SPL-78 — CS-E09-S4: Withdraw a pending venue-booking request

**Epic:** CS-E10 Venue Booking Request (SPL-10)

**Priority:** High · **Estimate:** 3 story points

**QA report:** Confluence QS space, `QA-SPL-78` (test cases written before the code).

## User story

As the assigned Event Coordinator, I want to withdraw a venue-booking request in `Requested` status
so that I can stop pursuing a venue that is no longer required.

## Acceptance criteria

1. The Event Coordinator assigned to the booking's event can withdraw a venue-booking request while
   it is `Requested`.
2. A successful withdrawal sets the status to `Withdrawn` and records the withdrawing Event
   Coordinator and the withdrawal time.
3. After withdrawal, the request's event, setup and turnaround slots no longer count as occupied in
   venue availability search or booking conflict checks.
4. The system keeps the withdrawn request, and the assigned Event Coordinator can still retrieve it
   with its original details and withdrawal record.
5. After withdrawal, the assigned Event Coordinator can submit a new venue-booking request for the
   same event, including for the same venue and slots.
6. The system refuses a withdrawal, leaving the request's status and occupancy unchanged, when the
   user is not the assigned Event Coordinator or the request is `Approved`, `Rejected` or already
   `Withdrawn`.
7. A submitted venue-booking request cannot be amended. To act on an alternative suggested by Venue
   Staff (Q45, Q110), the assigned Event Coordinator withdraws the request and submits a new one.

**Assumptions (recorded on the Jira story):**

- Retrieval is through read-only endpoints for the event's latest request and for one request by id.
  The full status history and "no request" state remain SPL-79.
- A "Venue booking request" panel on the event's Venue search page offers "Withdraw request" with a
  confirmation step.
- Only the booking's own status gates withdrawal, so a cancelled or postponed event can still release
  its venue (Q60).

## Interface

All routes are Event Coordinator only and require the caller to be the event's current coordinator.

- `POST /api/event-requests/{event_id}/venue-bookings/{booking_id}/withdraw` — no body or `{}`.
  200 with the booking; 409 "Only a Requested venue-booking request can be withdrawn."; 400 if any
  parameter is supplied; 404 for an unassigned event, an unknown booking or a booking of another
  event (identical body).
- `GET /api/event-requests/{event_id}/venue-bookings/latest` — `{"booking": {...} | null}`.
- `GET /api/event-requests/{event_id}/venue-bookings/{booking_id}` — one booking.
- `PUT`/`PATCH` on a booking — 405 with "cannot be amended … withdraw it and submit a new request".

Every booking response (including SPL-77's) now carries `withdrawn_by: {id, name} | null` and
`withdrawn_at` (+08:00) | null. Withdrawal locks the booking row, checks it is still `Requested`,
and calls SPL-83's `transition_booking_status(session, booking, "withdrawn")`, which releases the
booking's occupancy, before recording the withdrawer and time.

## Schema

Migration `s2_venue_booking_withdrawal` (parent `s2_venue_booking_request`) adds nullable
`withdrawn_by_account_id` (FK accounts) and `withdrawn_at` to `venue_bookings`.

## Test cases

| ID | AC | Level | Location |
| --- | --- | --- | --- |
| TC-SPL-78-01 to -18, -20, -21 | 1–7 | Server | `backend/tests/test_venue_booking_withdrawals.py` |
| TC-SPL-78-19 | 6 | PostgreSQL | `backend/tests/test_venue_booking_withdrawals_postgres.py` |
| TC-SPL-78-22, -23 | 1, 2, 4, 6 | Component | `frontend/src/VenueBookingWithdrawal.test.tsx` |
| TC-SPL-78-24, -25 | 1, 3, 5; cross-cutting | Browser | `e2e/venue-booking-withdrawal.spec.ts` |

```sh
rg -n "TC-SPL-78" docs backend/tests frontend/src e2e
uv run --frozen pytest backend/tests/test_venue_booking_withdrawals.py -v
pnpm --dir frontend exec vitest run src/VenueBookingWithdrawal.test.tsx
npm run integration        # TC-SPL-78-19 and the migration, on disposable PostgreSQL
npm run check:e2e          # TC-SPL-78-24/-25, with npm start running
```

## Out of scope

Withdrawing an Approved booking, Venue Staff approval and rejection (SPL-81, SPL-82), the booking
status history view (SPL-79), withdrawing the event request itself (SPL-69, Q103), automatic release
when an event is cancelled (Q60), and notifications.
