# SPL-64 — CS-E06-S1: View an assigned submitted request in full

**Epic:** CS-E06 Event Review and Approval
**Priority:** High — entry point to event review
**Estimate:** 2 story points

## User story

As an Event Coordinator, I want to view the complete details of an event request assigned to me so
that I can assess whether it is ready for planning.

## Acceptance criteria

1. The assigned Event Coordinator can retrieve the request's core details, venue requirements,
   equipment requirements, registration needs, client organisation, responsible Event Organiser,
   and submission date and time.
2. Submitted request information is read-only while it is being reviewed.
3. An Event Coordinator who is not assigned to the request cannot retrieve its protected details.
4. A missing or inaccessible request returns no protected event information.

## Dependencies

- SPL-44 — role-based authorisation.
- SPL-51 to SPL-55 — event-request information and submission.
- SPL-60 — Event Coordinator assignment.
- SPL-62 — assigned-events entry point.

## Out of scope

- Editing, clarification, approval, rejection, and withdrawal actions.
- Filtering the assigned-events list.

## Implementation

- `GET /api/event-requests/assigned/<id>` now returns every form field. It keeps the SPL-62
  assignment join, so the same 404 answers a missing request and another coordinator's request.
- Internal identifiers (organiser account id) are not returned.
- The detail page renders one read-only table grouped into core details, venue, equipment,
  registration, and organisation/submission. Empty fields show "Not provided".
- **Begin review** returns the summary shape; the page merges it into the loaded detail.

## Consolidated test cases

| ID | AC | Scenario | Expected result | Level |
|---|---|---|---|---|
| TC-SPL-64-01 | 1 | Assigned coordinator opens a fully populated request | Every field is returned and shown | API/UI |
| TC-SPL-64-02 | 1 | Optional fields are empty | Empty values returned; page shows "Not provided" | API/UI |
| TC-SPL-64-03 | 3,4 | Unassigned coordinator, reassigned-away coordinator, or unassigned event | 404 with no event data | API/UI |
| TC-SPL-64-04 | 4 | Request id does not exist | Identical 404 body to the unassigned case | API |
| TC-SPL-64-05 | 2,3 | Write methods, other roles, or no token | Refused (403/405/401); request unchanged | API |
| TC-SPL-64-06 | 1 | Begin review after the detail loads | Detail table stays visible; status updates | UI |

## Automated test traceability

| Test case | Executable evidence |
|---|---|
| TC-SPL-64-01 to 05 | `backend/tests/test_coordinator_assignment.py` (`tc_spl_64_*`) |
| TC-SPL-64-01, 02, 03, 06 | `frontend/src/AssignedEvents.test.tsx` |

```sh
uv run pytest backend/tests/test_coordinator_assignment.py -q -k spl_64
pnpm --dir frontend exec vitest run src/AssignedEvents.test.tsx -t "TC-SPL-64"
```

`npm run verify` remains the required full local gate.
