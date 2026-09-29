# SPL-82 — CS-E10-S4: Reject a venue-booking request with a reason

**Epic:** CS-E10 Venue Booking Request (SPL-10)

**Priority:** High

**QA report:** Confluence QS space, `QA-SPL-82` (test cases written before the code).

## User story

As a Venue Staff member, I want to reject an unsuitable venue-booking request with a reason so that
the Event Coordinator can understand the decision.

## Acceptance criteria

1. Venue Staff can reject only a venue-booking request in `Requested` status.
2. A non-blank rejection reason is required; Venue Staff may also record a free-text alternative
   suggestion.
3. A successful rejection changes the request to `Rejected` and records the reason, acting user, and
   time.
4. The rejected request's event and preparation slots no longer count as occupied.
5. The assigned Event Coordinator can retrieve the rejection outcome and recorded reason.
6. Venue Staff cannot directly amend the requested venue, date, layout, or slots while rejecting it.
7. An unauthorised or invalid rejection is refused and leaves the request and occupancy unchanged.

## Interpretation of the acceptance criteria

Two decisions made before any test was written:

- **The reason and the alternative suggestion are two separate fields, not one.** AC2 asks for a
  required reason and an optional suggestion; conflating them into one free-text field would let a
  rejection carry a suggestion with no reason, or bury the reason inside suggestion text a coordinator
  has to parse. `rejection_reason` is required; `rejection_alternative_suggestion` is optional. Only
  the reason is written as the SPL-79 history entry's note — the suggestion is not a status change,
  it is extra context on top of one.
- **Rejection does not recheck the event's status.** SPL-81's approval rechecks that the event is
  still `Planning` before committing venue time to it (Q120: approving must not silently commit a
  venue to an event that has moved on). Rejection commits nothing — like SPL-78's withdrawal, it only
  releases something the event no longer needs, so only the booking's own status gates it. This
  matches AC1 and AC7 exactly as written: neither mentions the event's status, only the booking's.

## Interface

- `POST /api/venue-bookings/{booking_id}/reject` — Venue Staff only. Body
  `{"reason": "...", "alternative_suggestion": "..."}`; `alternative_suggestion` is optional and may
  be omitted or `null`. 200 with the booking; 400 if `reason` is missing, blank, not a string, over
  1000 characters, or any field other than `reason`/`alternative_suggestion` is sent; 409 "Only a
  Requested venue-booking request can be rejected." if the booking is not `Requested`; 404 "Venue-
  booking request not found." for an unknown booking; 403 for any role but Venue Staff; 401 with no
  session.
- Every booking response (SPL-77's, SPL-78's, SPL-79's, SPL-80's, SPL-81's) now also carries
  `rejected_by: {id, name} | null`, `rejected_at` (+08:00) | null, `rejection_reason: string | null`
  and `rejection_alternative_suggestion: string | null`. The assigned Event Coordinator already reads
  a booking through SPL-78's `GET` routes, so AC5 needs no new read endpoint.
- Rejection locks the booking row, checks it is still `Requested`, calls SPL-83's
  `transition_booking_status(session, booking, "rejected")` — which releases the booking's occupancy
  through the same shared lifecycle rule SPL-78's withdrawal and SPL-81's approval already use — then
  records the rejector, time, reason and suggestion, and appends a `"reject"` entry to SPL-79's status
  history with the reason as its note.

## Schema

Migration `s2_venue_booking_rejection` (parent `s2_venue_booking_approval`, the current head) adds
nullable `rejected_by_account_id` (FK `accounts`), `rejected_at`, `rejection_reason` and
`rejection_alternative_suggestion` to `venue_bookings`.

## Integration

Additive only. `serialize_venue_booking` (SPL-77) gains four fields every existing caller already
tolerates unknown-to-them additions from (SPL-78's, SPL-80's and SPL-81's own tests assert specific
keys, not the whole object, precisely because each story before this one already had to do the same
widening). `record_booking_transition` (SPL-79) already documents `"SPL-82 (reject, with reason)"` as
an expected caller. `transition_booking_status` (SPL-83) already frees occupancy for any status
outside `ACTIVE_BOOKING_STATUSES`, and `"rejected"` already is not one — no change needed there at
all.

## Test cases

| ID | AC | Level | Location |
| --- | --- | --- | --- |
| TC-SPL-82-01 to -16 | 1–7 | Server | `backend/tests/test_venue_booking_rejection.py` |
| TC-SPL-82-17 | 4 | PostgreSQL | `backend/tests/test_venue_booking_rejection_postgres.py` |
| TC-SPL-82-18, -19 | 2, 3, 5, 6 | Component | `frontend/src/VenueBookingReview.test.tsx` |
| TC-SPL-82-20 | 1, 3, 4, 5; cross-cutting | Browser | `e2e/venue-booking-rejection.spec.ts` |

```sh
rg -n "TC-SPL-82" docs backend/tests frontend/src e2e
uv run --frozen pytest backend/tests/test_venue_booking_rejection.py -v
pnpm --dir frontend exec vitest run src/VenueBookingReview.test.tsx
npm run integration        # TC-SPL-82-17 and the migration, on disposable PostgreSQL
npm run check:e2e          # TC-SPL-82-20, with npm start running
```

## Out of scope

A formal counter-offer workflow (the alternative suggestion is free text, not a new request), and
notifications.
