# SPL-71 — Find venues available for an event

## Approved user story

As an Event Coordinator, I want to find venues available for an event so that I can identify
appropriate options before making a venue booking request.

## Acceptance criteria

1. Search accepts one Singapore calendar date and one or more fixed AM, PM and Night slots.
2. A venue is excluded when any selected slot, or its required one-slot setup/turnaround
   occupancy, is unavailable because of an active Requested/Approved booking or active
   operational block.
3. Each result shows the venue name, location and maximum recorded room-layout capacity.
4. When nothing is available, the applied date and slots stay visible with a clear empty result.
5. Before starting search, the assigned Event Coordinator can read the event date, slots, expected
   attendance, layout preference, facilities, accessibility needs and location preference.

## Implementation

- `GET /api/event-requests/<event_request_id>/available-venues?date=YYYY-MM-DD&slot=AM&slot=PM`
  is restricted to an Event Coordinator who is currently assigned to the referenced event.
  The server derives the trusted coordinator from the session; the browser supplies no account,
  role or organisation selector.
- Each candidate first has to operate in every event slot. `derive_venue_occupancy()` then adds
  that candidate venue's one-slot setup and turnaround requirements. Every derived occupancy slot
  must be an operating slot, free of a persisted active booking claim, and free of an active
  `operational_block_for_slot()` result.
- The search is strictly read-only: it creates neither a venue booking nor a tentative hold.
  Booking request/decision and suitability requirements remain owned by their later stories.
- The assigned-event detail presents a read-only event brief before its single **Find venues** action.
  The dedicated search page repeats that context, pre-fills date and slots, and still allows the
  coordinator to explore another date/slot combination without changing the saved event.
- Available results use the existing marketplace-card pattern. Opening one confirms timing only;
  non-available venues remain excluded, and suitability is deliberately reserved for SPL-75.

## Requirement sources

- Customer briefing: venue identification follows initial event approval and precedes a venue
  booking request.
- `IS212-2026_discussions_QA.xlsx`: Q36 (Singapore), Q50 (three fixed slots), Q83 (search versus
  suitability), Q107 (each selected slot is consumed fully), Q108/Q123 (one immediately adjacent
  setup/turnaround slot), Q112 (layout-specific stated capacity).
- Shared completed dependencies: SPL-83 booking occupancy, SPL-87 preparation derivation and
  SPL-89 operational unavailability.

## Automated traceability

| Test case | Coverage | Location |
| --- | --- | --- |
| TC-SPL-71-01 | Multi-slot search excludes booked and operationally blocked venues; result facts | `backend/tests/test_venue_availability.py`, `frontend/src/VenueAvailabilitySearch.test.tsx` |
| TC-SPL-71-02 | Required adjacent setup/turnaround occupancy is considered | `backend/tests/test_venue_availability.py` |
| TC-SPL-71-03 | Empty result retains the applied search controls | `backend/tests/test_venue_availability.py`, `frontend/src/VenueAvailabilitySearch.test.tsx` |
| TC-SPL-71-04 | Invalid/missing date and slot parameters are refused | `backend/tests/test_venue_availability.py` |
| TC-SPL-71-05 | Only the currently assigned Event Coordinator can search an event | `backend/tests/test_venue_availability.py` |
| TC-SPL-71-06 | Assigned-event brief exposes the saved, read-only search context | `backend/tests/test_coordinator_assignment.py`, `frontend/src/AssignedEvents.test.tsx` |
| TC-SPL-71-07 | Unit-level valid slot equivalence partitions are accepted and normalised | `backend/tests/test_venue_availability_unit.py` |
| TC-SPL-71-08 | Unit-level invalid date/slot partitions, including duplicate slots, are refused | `backend/tests/test_venue_availability_unit.py`, `backend/tests/test_venue_availability.py`, `frontend/src/VenueAvailabilitySearch.test.tsx` |
| TC-SPL-71-09 | Setup and turnaround buffer boundaries across midnight are excluded when blocked | `backend/tests/test_venue_availability.py` |
| TC-SPL-71-10 | A venue missing a selected event slot or a required buffer operating slot is excluded | `backend/tests/test_venue_availability.py` |
| TC-SPL-71-11 | Browser journey carries the assigned event's date and slots into a read-only availability search | `e2e/coordinator-assignment.spec.ts` |

No migration is required. The implementation reads the existing Alembic-owned tables only.

## Week 6 unit-test and coverage evidence

`backend/tests/test_venue_availability_unit.py` keeps the search-input contract independent of
Flask, the database and wall-clock state. It uses valid and invalid equivalence partitions, while
TC-SPL-71-09 exercises the setup/turnaround day-boundaries through the API. The tests use exact
requirement-derived outcomes rather than reproducing implementation calculations.

Run `npm run coverage:spl71` to measure statement and branch coverage for this story's owned
availability module. Coverage is used to identify unexercised code; it is not treated as proof that
the acceptance criteria are complete.
