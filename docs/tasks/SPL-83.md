# SPL-83 — CS-E12-S1: Prevent overlapping venue bookings

**Epic:** CS-E12 Booking Conflict Detection

**Priority:** Highest — shared safety boundary for booking creation and approval

**Estimate:** 8 story points

## User story

As a Venue Staff member, I want conflicting venue occupancy to be prevented so that a venue is not
promised to overlapping events.

## Acceptance criteria

1. Before a venue-booking request is created or approved, the system checks all required event and
   preparation slots against existing occupancy for the same venue.
2. A conflicting operation is refused atomically and leaves no partial booking change; a different
   venue, date or non-overlapping slot does not conflict.
3. Requested and Approved bookings and active operational blocks occupy venue time; Rejected,
   Withdrawn and Cancelled bookings do not.
4. When conflicting operations are attempted concurrently for the same occupancy, at most one
   succeeds.

## Dependencies

- SPL-87 derives preparation slots.
- SPL-89 provides active operational blocks.
- SPL-77 booking request and SPL-81 approval consume the shared conflict policy; controlled fixtures
  verify this service before either consumer is complete.

## Public interface

- `claim_venue_occupancy(session, booking, event_slots=...)` derives and atomically claims every
  required event/preparation slot or raises `VenueOccupancyConflict` with the date and slot.
- Booking claims and operational-block creation share ordered PostgreSQL transaction advisory locks
  for each venue/date/slot, preventing cross-table write skew.
- `transition_booking_status(session, booking, resulting_status)` retains claims for active statuses,
  rechecks blocks before approval, and releases claims for terminal statuses.
- `occupancy_for_booking(session, booking_id)` exposes the active claims to later booking/calendar
  consumers.

Callers own the surrounding transaction. SPL-77 and SPL-81 must roll back their booking mutation
when `VenueOccupancyConflict` is raised. The nested occupancy savepoint prevents a multi-slot batch
from leaving earlier slots behind, and the database unique constraint resolves concurrent races.

## Consolidated test cases

| ID | AC | Scenario | Expected result | Level |
| --- | --- | --- | --- | --- |
| TC-SPL-83-01 | 1,3 | Requested or Approved booking claims a PM event at a venue requiring setup and turnaround | AM setup, PM event and Night turnaround are distinguishable active claims | Domain/database |
| TC-SPL-83-02 | 1,2,3 | A required slot meets an active operational block | Whole claim is refused with the conflicting date/slot and no partial occupancy | Domain/database |
| TC-SPL-83-03 | 1,2,3 | A required slot meets an active booking; alternatives use another venue or date | Exact overlap is refused; non-overlapping alternatives succeed | Domain/database |
| TC-SPL-83-04 | 3 | Requested booking becomes Rejected, Withdrawn or Cancelled | Its active claims are released and reusable | Domain/database |
| TC-SPL-83-05 | 1,2,3 | Approval encounters an operational block added after the request | Approval is refused without changing status or occupancy | Domain/database |
| TC-SPL-83-06 | 2,4 | Two PostgreSQL transactions claim the same venue/date/slots together | Exactly one complete claim succeeds | PostgreSQL integration |
| TC-SPL-89-09 | 2,4 | A booking claim and operational block are written together | No committed block overlaps an unmarked active booking | PostgreSQL integration |

## Automated traceability

- TC-SPL-83-01 to TC-SPL-83-05: `backend/tests/test_venue_conflicts.py`
- TC-SPL-83-06 and cross-story TC-SPL-89-09: `backend/tests/test_venue_conflicts_postgres.py`
- Migration, RLS and browser-grant denial: `backend/tests/test_postgres.py`

Find all executable story cases with:

```sh
rg -n "TC-SPL-83" docs backend/tests
```

Run the focused quick suite with:

```sh
uv run pytest backend/tests/test_venue_conflicts.py -q
```

Run the migration and real concurrency gate with a fresh disposable PostgreSQL database:

```sh
npm run integration
```

## Out of scope

The SPL-77 request endpoint and fields, SPL-81 approval endpoint, automatic hold expiry, alternative
venue recommendations, notifications, and calendar presentation.
