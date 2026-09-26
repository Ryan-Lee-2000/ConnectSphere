# SPL-67 — CS-E06-S4: Approve an event request

**Epic:** CS-E06 Event Review and Approval
**Priority:** Highest — the handoff before venue booking can begin
**Estimate:** 3 story points

## User story

As an Event Coordinator, I want to approve an event request containing sufficient information so
that event planning can begin.

## Acceptance criteria

1. Only the assigned Event Coordinator can approve a request that is Under Review.
2. Approval is refused while an unanswered clarification request remains outstanding.
3. Approval records the decision-maker and date and time, and changes the event to Planning.
4. The responsible Event Organiser can retrieve the approval outcome.
5. Approval does not itself book a venue, reserve equipment, enable registration, or confirm the
   event.
6. An invalid or unauthorised approval attempt leaves the event unchanged.

## Dependencies

- SPL-64 — the complete request information.
- SPL-70 — the server-owned transition policy this story extends (Done).

## Out of scope

Venue booking, equipment reservation, registration setup, event confirmation and notifications.

## Decisions

- `POST /api/event-requests/<id>/approve` applies the `approve` rule: `under_review` to
  `planning` ("In planning"). The `approved` status stays unused, as the ticket says Planning.
- AC2 relies on the status guard. Requesting clarification moves the event to
  `returned_for_clarification`, so an event with an outstanding clarification is never
  `under_review` and is refused with 409. The organiser's response and resubmission flow is SPL-66;
  no answered flag is added here.
- The decision-maker and time live on `event_requests` (`approved_by_account_id`,
  `approved_at`, migration `s2_event_approval`). The append-only `event_status_history` row is the
  audit evidence.
- Errors follow the repo convention `{"error": "<message>"}`, which is also the display message:
  403 for other roles, 404 "Assigned event not found." when not assigned, 409 "Only an event under
  review can be approved." for the wrong status, 400 for a body. Success returns the message
  "Request approved. Event planning can begin."
- The organiser reads `approved_by` / `approved_at` from `GET /api/event-requests/<id>` and the
  request list; the coordinator also sees them in the assigned detail.

## Verification

Backend: `backend/tests/test_approve_event_request.py` (TC-SPL-67-01 to -09). Frontend:
`AssignedEvents.test.tsx` (TC-SPL-67-10 to -12) and `EventRequestDrafts.test.tsx` (TC-SPL-67-13).
