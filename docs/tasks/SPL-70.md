# SPL-70 — CS-E07-S2: Begin reviewing an assigned event

**Epic:** CS-E07 Event Status Management
**Priority:** Highest — Sprint 2 workflow foundation
**Estimate:** 3 story points

## User story

As the assigned Event Coordinator, I want to begin reviewing a submitted event so that its status
reflects that review has started.

## Acceptance criteria

1. The assigned Event Coordinator can begin reviewing an event whose current status is Submitted,
   changing it to Under Review.
2. An attempt by an unauthorised or unassigned user, or for an event not in Submitted, is refused
   without changing the event.
3. The client cannot change status by supplying an arbitrary status value; the transition happens
   through the supported begin-review action.
4. A successful transition records the action, previous status, resulting status, actor, and
   date/time.

## Dependencies

- SPL-44 — server-owned role authorisation.
- SPL-55 — submitted event requests.
- SPL-60 — assigned Event Coordinator.
- SPL-63 — shared event-status vocabulary.

## Out of scope

- Clarification requests, approval, rejection, withdrawal, confirmation, cancellation,
  completion, postponement, and notifications.

## Implementation

- `POST /api/event-requests/<id>/begin-review` is an action-specific endpoint with no client-owned
  target status.
- The server verifies both the Event Coordinator role and current assignment before making a
  conditional `submitted` to `under_review` update.
- `event_status_history` stores the action, before/after states, actor, and timestamp in the same
  transaction as the event update.
- The assigned-event detail page shows **Begin review** only while the event is Submitted and
  updates the visible status after success.
- SPL-60 assignment now leaves the event Submitted so this explicit action has a valid start state.

## Consolidated test cases

| ID | AC | Scenario | Expected result | Level |
|---|---|---|---|---|
| TC-SPL-70-01 | 1,4 | Assigned coordinator begins review | Status becomes Under Review and one complete audit record is stored | API/UI |
| TC-SPL-70-02 | 2 | Wrong role or unassigned coordinator attempts action | Request refused; status and audit history unchanged | API |
| TC-SPL-70-03 | 2 | Event is not Submitted or action is repeated | Request refused; no second transition or audit record | API |
| TC-SPL-70-04 | 3 | Client submits an arbitrary target status | Request refused; server-owned transition is not bypassed | API |
| TC-SPL-70-05 | 1,2 | Coordinator uses the assigned-event page | Button appears only for Submitted; success refreshes status; refusal remains actionable | UI |
