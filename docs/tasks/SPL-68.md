# SPL-68 — CS-E06-S5: Reject an event request

**Epic:** CS-E06 Event Review and Approval
**Priority:** High — the required negative review outcome
**Estimate:** 2 story points

## User story

As an Event Coordinator, I want to reject an event request with a reason so that the Event
Organiser understands why it cannot proceed.

## Acceptance criteria

1. Only the assigned Event Coordinator can reject a request that is Under Review.
2. A non-blank rejection reason is required.
3. Rejection records the reason, decision-maker, and date and time and changes the event to
   Rejected.
4. The responsible Event Organiser can retrieve the rejection outcome and reason.
5. A rejected request cannot undergo further review or planning; proceeding requires a new event
   request.
6. An invalid or unauthorised rejection attempt leaves the event unchanged.

## Dependencies

- SPL-64 — the complete request information.
- SPL-70 — the server-owned transition policy this story extends (Done).
- SPL-67 — the approve story this one mirrors.

## Out of scope

Editing or resubmitting the rejected request; notification delivery (SPL-102).

## Decisions

- `POST /api/event-requests/<id>/reject` applies the `reject` rule: `under_review` to `rejected`
  ("Not approved") through `transition_event_status`, so the audit row is written.
- Rejection is final (Q67). No rule leaves `rejected`, so begin-review, approve,
  request-clarification and reject all answer 409 on a rejected event.
- The body must be exactly `{"reason": "<text>"}`. The reason is trimmed, must be non-blank and may be at most 2,000 characters after
  trimming (matching clarification requests); a longer one is refused with 400. QA found that
  "no cap" was not real anyway: the API refuses any body over 16 KiB with 413. Any other key, including a status, is refused with 400.
- The decision lives on `event_requests` in separate columns `rejected_by_account_id`,
  `rejected_at`, `rejection_reason` (migration `s2_event_rejection`), not shared with the
  `approved_*` columns. Generic decision columns were considered and rejected: they would rewrite
  merged, QA'd SPL-67 code and need a destructive migration. A check constraint keeps the three
  columns all set or all null. Consolidating decisions can be its own story.
- Errors follow `{"error": "<message>"}`: 403 other roles, 404 "Assigned event not found." when
  not assigned, 409 "Only an event under review can be rejected.", 400 for a bad body or reason.
- The organiser reads `rejected_by`, `rejected_at` and `rejection_reason` from
  `GET /api/event-requests/<id>` and the list; the coordinator sees them in the assigned detail.
- UI: **Reject request** opens a required reason form, then a final "Rejection is final" step with
  **Confirm rejection**. The repo uses inline confirmations, not modal dialogs.

## Verification

Backend: `backend/tests/test_reject_event_request.py` (TC-SPL-68-01 to -11). Frontend:
`AssignedEvents.test.tsx` (TC-SPL-68-12 to -14) and `EventRequestDrafts.test.tsx` (TC-SPL-68-15).
