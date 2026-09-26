# SPL-77 venue-booking integration contract

This handoff records how the approved SPL-77 booking-request story must consume the completed
SPL-87, SPL-83 and SPL-89 foundations. It does not change SPL-77's Jira acceptance criteria or
implement its endpoint.

## Transaction boundary

The booking request and all of its occupancy claims are one transaction:

1. Load the server-authorised event and selected venue. Never trust submitted user, role or
   organisation identifiers.
2. Create and flush the `VenueBooking` in `requested` state.
3. Call `claim_venue_occupancy(session, booking, event_slots=...)` with every dated event slot.
   The shared service derives setup and turnaround slots and coordinates concurrent bookings and
   operational blocks.
4. Commit only after the complete claim succeeds. On `VenueOccupancyConflict`, roll back the whole
   transaction and return a conflict that identifies the unavailable date and operating slot.

Do not duplicate the preparation-slot, active-status, operational-block or concurrency rules in the
route. Alternative venue/date checks may call the same shared policy in their own transaction.

## Retrieval contract inherited from SPL-89

Every SPL-77 booking detail/list response that exposes a booking must also expose its persisted
review state so an operational block cannot become invisible after creation:

- `requires_review`
- `review_trigger_block_id`
- `review_marked_at`

Expose `review_marked_by_account_id` only to roles authorised to see internal audit identity. The
API must serialize these values from the stored booking row; it must not infer them from the current
set of blocks or accept them from the request body.

## SPL-81 approval handoff

SPL-81 must approve only a Requested booking and call
`transition_booking_status(session, booking, "approved")` inside its approval transaction. A
conflict must roll back the status and audit mutation together. SPL-81 remains responsible for its
approved actor, timestamp, note and idempotency requirements.

## Required verification

- Booking request succeeds with all derived occupancy rows.
- Any booking or operational-block conflict leaves no partial booking or occupancy.
- A retrieved booking includes the persisted SPL-89 review marker fields.
- PostgreSQL integration runs TC-SPL-83-06 and TC-SPL-89-09, not only SQLite tests.
