# SPL-75 — Assess venue suitability for an event

## Approved user story

As an Event Coordinator, I want to assess a selected venue against the event’s requirements so
that I can identify whether it is suitable before submitting a venue booking request.

## Acceptance criteria

1. A venue assessment considers the saved event’s date and slots (including the venue’s one-slot
   setup and turnaround occupancy), requested layout and per-layout capacity, required facilities,
   accessibility needs and location preference.
2. A venue is suitable only when every applicable requirement passes.
3. The assessment clearly identifies whether the venue is suitable and which requirements are not
   met.
4. The assessment does not change the event or venue, create a booking, reserve a venue, or treat
   a preference as approval.

## Implementation

- `GET /api/event-requests/<event_request_id>/available-venues` continues to be the existing
  assigned-coordinator, Planning-only and read-only catalogue endpoint. Each returned candidate
  now includes a `suitability` object with an overall result and named timing, layout/capacity,
  facilities, accessibility and location checks.
- `assess_venue_suitability()` uses only the server-owned saved event. A coordinator may broaden
  discovery filters to compare options, but those browser inputs cannot make a venue appear
  suitable for a different event. Timing reuses the existing operating-slot, booking,
  operational-block, setup and turnaround logic.
- Stored layout capacities are assessed per layout; capacity is never estimated. Facility and
  accessibility checks require every requested value, while the optional location preference uses
  the existing catalogue location-match rule.
- The marketplace card presents a restrained pass/fail badge. Opening a card expands an inline
  assessment panel that explains every check and explicitly reminds the coordinator that the
  result is neither a booking nor a hold.
- No migration is required. SPL-75 reads the existing Alembic-owned event, venue, layout,
  booking-occupancy and operational-block records. A later booking-request story owns creating a
  request from a suitable venue.

## Requirement sources

- Jira SPL-75 and the approved SPL-76 presentation consolidation.
- Week 1 Customer Briefing: venue selection considers schedule, capacity, layout, facilities,
  accessibility, operating availability and existing bookings before the booking request.
- `IS212-2026_discussions_QA.xlsx`: Q83 separates discovery filtering from suitability; Q112
  preserves stated per-layout capacity; Q119 keeps attendance event-level; Q123 limits adjacent
  setup/turnaround to one slot.

## Automated traceability

| Test case | Coverage | Location |
| --- | --- | --- |
| TC-SPL-75-01 | API assessment is tied to saved event requirements, not editable discovery overrides | `backend/tests/test_venue_availability.py` |
| TC-SPL-75-02 | Unit equivalence/boundary checks for layout capacity, facilities, accessibility and location | `backend/tests/test_venue_availability_unit.py` |
| TC-SPL-75-03 | API assessment identifies a saved-event timing failure caused by a required setup slot operational block | `backend/tests/test_venue_availability.py` |
| TC-SPL-75-04 | Component test shows the unsuitable badge and the unmet-requirement explanation after a card is opened | `frontend/src/VenueAvailabilitySearch.test.tsx` |
| TC-SPL-75-05 | Browser journey shows and expands the suitability result in the assigned coordinator catalogue workflow | `e2e/coordinator-assignment.spec.ts` |

## Week 6 unit-test and coverage evidence

`profile_suitability_checks()` is deliberately free of HTTP, database and wall-clock collaborators,
so its layout-capacity equivalence and requirement-boundary cases are fast, deterministic unit
tests. Endpoint tests then confirm the pure profile decision is combined with trusted assigned-event
authorisation and persisted availability/one-slot setup rules. The component and browser tests
cover the visible assessment presentation.

Run `npm.cmd run coverage:spl75` for statement and branch coverage of the shared
`app.venue_availability` module. Coverage is a diagnostic that complements requirement-based
tests; it is not a substitute for them.
