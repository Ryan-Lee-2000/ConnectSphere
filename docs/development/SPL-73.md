# SPL-73 — Filter venues by event requirements

## Approved user story

As an Event Coordinator, I want to filter available venues by the event's venue requirements so
that I can shortlist venues that meet the Event Organiser's needs.

## Acceptance criteria

1. Venue search can be narrowed by supported room layout, facilities, accessibility features and
   location preference.
2. A result is shown only when it meets every active requirement filter. Multiple facility or
   accessibility selections use AND logic.
3. Requirement filtering combines with date, operating-slot and expected-attendance filters.
4. Changing or clearing a requirement filter changes the search result only; it does not alter the
   saved assigned event.

## Implementation

- The authenticated, assigned Event Coordinator opens the existing read-only venue catalogue
  search. The initial controls are prefixed with server-owned event requirements, while the
  coordinator may adjust or clear them to explore alternatives. No event, booking, hold or venue
  request is created by this search.
- The Flask endpoint validates repeated `required_facility` and `accessibility_need` parameters,
  plus the optional `location_preference`. When those parameters are omitted, it applies the
  stored event requirements. Explicit blank values clear a requirement category for that search.
- A protected catalogue-facets endpoint returns venue-profile facilities, accessibility features
  and recorded building/site locations only to the assigned Event Coordinator. The UI uses those
  values as selectable suggestions: removable chips for multi-value requirements and an optional
  location selector.
- `venue_satisfies_requirements()` is a pure helper. Facility and accessibility requirements use
  case-insensitive AND matching; a location preference matches the stored venue location without
  changing it. The helper runs only after the existing availability and per-layout capacity checks.
- The search UI keeps the date, slots, attendance, layout, facility, accessibility and location
  filters in one responsive panel. The assigned-event requirement summary remains visible as a
  read-only reminder, while the applied filters are shown in an expanded venue result.

## Requirement sources

- Week 1 Customer Briefing and Week 4 Project Instructions: Event Coordinators filter venue
  options by date/time, capacity, location, accessibility, room layout and required facilities.
- `IS212-2026_discussions_QA.xlsx`: Q83 distinguishes discovery filtering from later suitability;
  Q111 confirms preferences do not create a booking or bypass approval; Q112 and Q119 preserve
  per-layout capacity and event-level attendance requirements.
- Jira SPL-73: active requirement filters use AND logic and combine with the SPL-71/SPL-72 rules.

## Automated traceability

| Test case | Coverage | Location |
| --- | --- | --- |
| TC-SPL-73-01 | API combines facility, accessibility and location requirements; excludes any venue missing one active requirement | `backend/tests/test_venue_availability.py` |
| TC-SPL-73-02 | Saved event requirements are used by default; explicitly clearing a filter changes results without mutating the event | `backend/tests/test_venue_availability.py` |
| TC-SPL-73-03 | Unit equivalence partitions trim, de-duplicate and case-normalise requirement values | `backend/tests/test_venue_availability_unit.py` |
| TC-SPL-73-04 | Unit negative/boundary cases reject overlong facility, accessibility and location inputs | `backend/tests/test_venue_availability_unit.py` |
| TC-SPL-73-05 | Component test edits facility, accessibility and location controls and sends only the transient read-only query | `frontend/src/VenueAvailabilitySearch.test.tsx` |
| TC-SPL-73-06 | Existing authenticated browser regression retains the coordinator's catalogue search workflow; the full E2E suite is run before review | `e2e/coordinator-assignment.spec.ts` |
| TC-SPL-73-07 | API returns de-duplicated venue-profile facilities, accessibility features and building/site locations as coordinator-only filter suggestions | `backend/tests/test_venue_availability.py` |
| TC-SPL-73-08 | API refuses catalogue filter suggestions to an unassigned Event Coordinator | `backend/tests/test_venue_availability.py` |
| TC-SPL-73-09 | Requirement matches remain excluded when their selected-slot setup buffer cannot be operated | `backend/tests/test_venue_availability.py` |

## Week 6 unit-test and coverage evidence

`parse_requirement_filters()` and `venue_satisfies_requirements()` keep normalisation, boundary
validation and AND matching deterministic and independently testable. API tests establish that the
pure rule is combined with assigned-coordinator authorisation, availability and capacity. Component
tests prove the browser creates the expected read-only catalogue query.

Run `npm.cmd run coverage:spl73` for statement and branch coverage of the shared
`app.venue_availability` module. Coverage is diagnostic evidence and complements, rather than
replaces, acceptance tests and browser regression.

No Alembic migration is required: SPL-73 reads existing event requirement and venue profile data.
