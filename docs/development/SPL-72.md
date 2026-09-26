# SPL-72 — Filter venues by expected attendance

## Approved user story

As an Event Coordinator, I want to filter available venues by expected attendance so that I only
consider venues with sufficient capacity.

## Acceptance criteria

1. Venue search filters the existing available-venue result set using the expected attendance.
   - Without a preferred layout, a venue is shown only if at least one saved supported layout has a
     stated capacity equal to or greater than expected attendance.
   - With a preferred layout, that exact saved layout must be supported and have a stated capacity
     equal to or greater than expected attendance.
2. The capacity rule combines with the existing date, operating-slot, booking, operational-block
   and setup/turnaround availability rules.

## Implementation

- The protected Flask availability endpoint starts with `expected_attendance` and
  `preferred_room_layout` from the server-owned assigned event. The coordinator may provide
  validated, read-only catalogue filter overrides for attendance and layout; these change neither
  the event nor authorisation. An explicitly cleared layout means any persisted layout may qualify.
  The browser still supplies no account, role or organisation selector.
- `qualifying_layouts()` is a pure helper. It compares the event-level attendance requirement with
  persisted per-layout capacity; it does not estimate capacity. If a preferred layout is recorded,
  comparison is case-insensitive but the response retains the stored layout name.
- Availability is still evaluated first for every requested event and preparation slot. A venue
  must pass both availability and capacity checks before it appears.
- Each result now exposes the matching layout(s) and their stated capacity. The existing search
  screen presents the event attendance target, matching layout details, and whether any or the
  preferred layout qualified. It remains discovery only: no booking, selection or hold is created.

## Requirement sources

- Week 1 Customer Briefing and Week 4 Project Instructions: venue search filters by expected
  attendance/capacity and must precede booking.
- `IS212-2026_discussions_QA.xlsx`: Q112 requires capacity to vary by stored room layout; Q119
  keeps expected attendance as one event-level requirement; Q83 keeps search/filtering separate
  from later venue suitability.
- Jira SPL-72: capacity filtering must combine with SPL-71 availability filters.

## Automated traceability

| Test case | Coverage | Location |
| --- | --- | --- |
| TC-SPL-72-01 | No preferred layout: exclude too-small venue and retain venues with any qualifying saved layout | `backend/tests/test_venue_availability.py` |
| TC-SPL-72-02 | Preferred layout: require that exact layout and its capacity, including equality boundary | `backend/tests/test_venue_availability.py` |
| TC-SPL-72-03 | Unit equivalence partitions: below/equal/above capacity and preferred-layout match/mismatch | `backend/tests/test_venue_availability_unit.py` |
| TC-SPL-72-04 | Unit negative case: no event-level expected attendance yields no qualifying layout | `backend/tests/test_venue_availability_unit.py` |
| TC-SPL-72-05 | Component result presents the trusted attendance target and matching layout | `frontend/src/VenueAvailabilitySearch.test.tsx` |
| TC-SPL-72-06 | Authenticated browser regression: assigned event search displays the 120-guest capacity target | `e2e/coordinator-assignment.spec.ts` |
| TC-SPL-72-07 | Coordinator can adjust prefixed attendance and layout filters without mutating the assigned event | `backend/tests/test_venue_availability.py`, `backend/tests/test_venue_availability_unit.py`, `frontend/src/VenueAvailabilitySearch.test.tsx` |
| TC-SPL-72-08 | Invalid attendance filter values are refused before venue search | `backend/tests/test_venue_availability_unit.py` |

## Week 6 unit-test and coverage evidence

`qualifying_layouts()` is intentionally pure so tests exercise capacity boundary and equivalence
partitions without Flask, a database or time-dependent availability state. API tests then prove the
rule is combined with the assigned-coordinator authorisation and SPL-71 availability result set.

Run `npm.cmd run coverage:spl72` for statement and branch coverage of the shared
`app.venue_availability` module. Coverage is diagnostic evidence, not a substitute for the
acceptance tests above.

No Alembic migration is required: SPL-72 reads existing event and venue-layout data.
