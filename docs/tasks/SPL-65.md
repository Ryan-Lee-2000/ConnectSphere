# SPL-65 — CS-E06-S2: Request clarification from the Event Organiser

**Epic:** CS-E06 Event Review and Approval
**Priority:** High — Sprint 2 review flow
**Estimate:** 3 story points

## User story

As an Event Coordinator, I want to request clarification about a submitted event request so that
the Event Organiser can provide the information needed for review.

## Acceptance criteria

1. The assigned Event Coordinator can request clarification while the event is Under Review.
2. A non-blank clarification message is required.
3. The clarification request records its message, author, and date and time.
4. The event moves to Returned for Clarification after the request is recorded.
5. The responsible Event Organiser can retrieve the clarification message with the event request.
6. Clarification history is retained if clarification is requested more than once.
7. Clarification cannot be requested from a status where that action is not permitted.

## Dependencies

- SPL-64 — the full assigned request view.
- SPL-70 — the server-owned status transition this story extends.
- SPL-63 — the status vocabulary, which gains one value here.
- SPL-102 — will deliver the corresponding notification (not built here).

## Out of scope

- Annotating individual form fields, and external messaging.
- The organiser's reply, editing the request and resubmitting it for review.
- Notifications.

## Decisions

- One clarification message applies to the whole request. The ticket's UI note asked for per-field
  comment buttons and a row-expand popup; per-field annotation is out of scope, and SPL-64 already
  shows every field in one table, so neither is built.
- The status vocabulary stays flat. `returned_for_clarification` ("Returned for clarification") is
  one new top-level status; there are no sub-statuses under Under Review.
- The label "Submitted" is unchanged. It means received and waiting for the coordinator to begin
  review, not waiting for approval.
- A message is trimmed and limited to 2000 characters. The limit is this story's own default, not
  a customer requirement.

## Implementation

- `event_statuses.py` adds `returned_for_clarification`. Migration `s2_clarification_requests`
  replaces `ck_event_requests_known_status` from that vocabulary and creates
  `clarification_requests` (message, author, `created_at`; append-only; RLS on, no browser grants).
  Downgrade is refused while any request holds the new status.
- `event_review.TRANSITION_RULES` gains `request_clarification`
  (`under_review` → `returned_for_clarification`).
- `POST /api/event-requests/<id>/request-clarification` accepts exactly `{"message": "..."}`. The
  server checks the Event Coordinator role and current assignment (404 otherwise), then makes the
  conditional status update, the `event_status_history` row and the `clarification_requests` row in
  one transaction. A wrong status returns 409; a blank, oversized or extra-field body returns 400.
- `clarifications` (newest first: id, message, author, `created_at`) is returned with
  `GET /api/event-requests/<id>`, `GET /api/organisation/events/<id>` (which now also carries the
  status) and `GET /api/event-requests/assigned/<id>`.
- The assigned-event page shows a **Request clarification** form only while the event is Under
  Review, and the clarification history. The organiser's event page shows the status, its
  explanation and the history, read-only.

## Consolidated test cases

| ID | AC | Scenario | Expected result | Level |
|---|---|---|---|---|
| TC-SPL-65-01 | 1,3,4 | Assigned coordinator requests clarification on an Under Review event | Status becomes Returned for clarification; message, author, time and one audit row are stored | API |
| TC-SPL-65-02 | 2 | Message is blank, whitespace, not text, or over 2000 characters | Request refused; nothing recorded; a padded message is stored trimmed | API |
| TC-SPL-65-03 | 1 | Manager, organiser or an unassigned coordinator attempts the action | Refused (403 / 404); nothing recorded | API |
| TC-SPL-65-04 | 7 | Event is Submitted, already Returned, or Approved | Refused (409); nothing recorded | API |
| TC-SPL-65-05 | 4 | Client also sends a target status | Refused (400); server-owned transition is not bypassed | API |
| TC-SPL-65-06 | 5 | Organiser reads the request after clarification | Message, author, time and new status come back with the request | API |
| TC-SPL-65-07 | 6 | Clarification is requested a second time | Both messages are kept, newest first, with two audit rows | API |
| TC-SPL-65-08 | 5,6 | Coordinator reopens the assigned event | History is listed with the request | API |
| TC-SPL-65-09 | 1,7 | Coordinator uses the assigned-event page | Form appears only while Under Review; success shows the new status and history and hides the form | UI |
| TC-SPL-65-10 | 2 | Blank message, or server refusal, on the page | Blank is refused without a request; a refusal keeps the form and the typed text | UI |
| TC-SPL-65-11 | 6 | Event has more than one clarification | History lists newest first | UI |
| TC-SPL-65-12 | 5 | Organiser opens the event | Status, explanation and message are shown, with no input | UI |

## Automated test traceability

| Test case | Executable evidence |
|---|---|
| TC-SPL-65-01 to TC-SPL-65-08 | `backend/tests/test_request_clarification.py` |
| TC-SPL-65-09 to TC-SPL-65-11 | `frontend/src/AssignedEvents.test.tsx` |
| TC-SPL-65-12 | `frontend/src/OrganisationEvents.test.tsx` |

```sh
rg -n "TC-SPL-65-04" docs backend/tests frontend/src
uv run pytest backend/tests/test_request_clarification.py -q
pnpm --dir frontend exec vitest run src/AssignedEvents.test.tsx src/OrganisationEvents.test.tsx
```

`npm run verify` remains the required full local gate.

## Migration notes

- New revision `s2_clarification_requests` (down revision `s2_accessibility_needs_list`). No merged
  migration is edited. Existing rows stay valid because the status list only grows.
- `test_migration_tooling.py` and `test_postgres.py` were updated for the new head and table.
