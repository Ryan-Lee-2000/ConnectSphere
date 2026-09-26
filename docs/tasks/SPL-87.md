# SPL-87 — CS-E12-S3: Derive venue preparation slots

**Epic:** CS-E12 Booking Conflict Detection

**Priority:** Highest — prerequisite for SPL-83 and SPL-71

**Estimate:** 5 story points

## User story

As an Event Coordinator, I want required setup and turnaround slots to be calculated automatically
for a venue booking so that all venue time needed for the event is considered.

## Acceptance criteria

1. For each venue booking, a venue requiring setup derives one full slot immediately before its
   first event slot, and a venue requiring turnaround derives one full slot immediately after its
   last event slot.
2. Adjacency follows the AM, PM and Night sequence across Singapore calendar days: before AM is the
   previous day's Night, and after Night is the following day's AM.
3. No more than one setup slot and one turnaround slot are derived, and unrelated non-adjacent slots
   cannot be substituted.
4. Derived preparation slots remain distinguishable from event slots and are included when
   evaluating venue availability and booking conflicts.

## Dependencies

- SPL-47 provides venue setup and turnaround requirements.
- SPL-49 provides the fixed AM, PM and Night operating-slot vocabulary.

Search, booking, calendar and conflict stories consume this derivation; they are not prerequisites.

## Implementation

- `app.slots.derive_venue_occupancy()` accepts dated event slots and the venue's existing zero-or-one
  setup and turnaround requirements.
- The function returns immutable `VenueOccupancySlot` values in chronological order. Each value is
  explicitly typed as `event`, `setup` or `turnaround`.
- Setup and turnaround are derived internally from the earliest and latest event slots. Callers
  cannot supply a substitute preparation slot.
- AM and Night boundaries roll across Singapore calendar dates without timezone conversion because
  the domain input is already a Singapore local date and named operating slot.
- This story adds no booking table, endpoint or interface. SPL-71, SPL-77, SPL-81 and SPL-83 will
  consume the shared calculation when their respective search, booking and conflict workflows exist.

## Consolidated test cases

| ID | AC | Scenario | Expected result | Level |
|---|---|---|---|---|
| TC-SPL-87-01 | 1,4 | Derive occupancy for a venue with or without preparation requirements | Required adjacent slots appear once with distinct kinds; a venue without a requirement gets only event occupancy | Domain |
| TC-SPL-87-02 | 2 | Setup precedes AM or turnaround follows Night | Setup becomes the previous day's Night; turnaround becomes the following day's AM | Domain |
| TC-SPL-87-03 | 1,3,4 | Derive preparation for an unordered multi-slot event and reject counts above one | Event slots are ordered; exactly one adjacent slot is placed before the first and after the last; invalid counts are refused | Domain |

## Automated test traceability

All three cases are executable in `backend/tests/test_slots.py`. A documented case is reused for
separate input partitions where the behavior is the same, such as the two calendar boundaries.

Find the documentation and executable assertions for one case from the repository root:

```sh
rg -n "TC-SPL-87-02" docs backend/tests frontend/src
```

Run the story's focused automated tests:

```sh
uv run pytest backend/tests/test_slots.py -q -k tc_spl_87
```

Run one documented case:

```sh
uv run pytest backend/tests/test_slots.py -q -k tc_spl_87_03
```

The full `npm run verify` gate remains required before review. No migration, PostgreSQL-specific
constraint, browser interaction or external integration is introduced by this story.

## Out of scope

Multiple preparation slots, partial-slot preparation, user-selected non-adjacent preparation,
availability search, venue-booking persistence, conflict enforcement and calendar presentation.
