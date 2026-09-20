# SPL-59 — CS-E05-S1: See submitted events awaiting assignment

**Epic:** SPL-5 CS-E05 Coordinator Assignment (priority 1 of 4)
**Assignee:** Clive Lim
**Status (Jira):** Dev Ops — awaiting merge of PR #16

## User story

As an Event Operations Manager, I want to see submitted events that have no
Event Coordinator so that I can assign one promptly.

## Acceptance criteria

1. Lists events in Submitted status with no coordinator.
2. Shows for each event: name, client organisation, proposed date, submission date.
3. The list of events awaiting assignment is ordered by submission date,
   oldest first.
4. Shows how many events are awaiting assignment.
5. Once an event is assigned, it no longer appears the next time the manager
   opens or refreshes the list.
6. When no events are awaiting assignment, the list shows an empty-state
   message.
7. A user without the Event Operations Manager role who opens the list is
   denied access.

## Out of scope

- Assigning a coordinator to an event — SPL-60.
- Role authorisation — provided by SPL-44.
- Filtering, searching or paging the list.
- Notifying the manager when a new event is submitted.

## Open questions / assumptions (unconfirmed — do not harden into "Done")

- Oldest-first ordering (AC3) is the team's proposal; customer has not
  specified an order.
- Tie-break rule when two events share the same submission timestamp is not
  defined anywhere — raise with PO before relying on a specific order.
- "Identify new submissions" (Q117) — this list is the proposed mechanism,
  not confirmed as the only one.

## Dependencies (blocking full implementation)

- **SPL-44** (Ryan, *Done*, PR #14) — reusable role-authorization mechanism.
  AC7 uses `require_roles(Role.EVENT_OPERATIONS_MANAGER)`; no bespoke check.
- **SPL-51** (Ranveer, *In Progress*) — creates the real event request
  entity. Until it lands, `events` is a provisional stand-in.
- **SPL-55** (lin wang, *To Do*) — "Submit an event request." No Submitted
  events exist until this ships; its own AC says the submitted request
  "appears in the Event Operations Manager's list of events awaiting
  assignment" (i.e. this screen).

## Implementation status (branch `clive`, not merged)

Shared design notes: [architecture](../architecture.md#coordinator-assignment).

- Rebased onto SPL-51 (merged). The provisional `events` table and its migration are gone; the
  queue reads `event_requests`.
- `GET /api/event-requests/awaiting-assignment` returns `{events, count}` (AC1, AC4, AC7). The
  Workspace shows it to Event Operations Managers only, as a navigation destination, with an
  empty state (AC6).
- AC5 follows from the assignment record (TC-CS-E05-S1-05).
- **AC2 and AC3 are met** now that CS-E03-S5 records `submitted_at`: the queue is ordered oldest
  submission first, with request id as the tie-break (TC-CS-E05-S1-10). Requests stored before that
  story have no submission time and sort last.
- **AC2 partial:** the client organisation is `organisation_id`, which stays null until SPL-45,
  so the queue shows "Not recorded yet".
- TC-CS-E05-S1-13 passes for a multi-role account, and SPL-46 role switching is merged.

## Test cases

| ID | AC | Scenario | Pre-conditions | Steps | Test data | Expected result | Level |
|---|---|---|---|---|---|---|---|
| TC-CS-E05-S1-01 | 1,2,3 | Happy path — queue populated correctly | Signed in as EOM; 3 Submitted events, no coordinator, distinct submission times | Open the queue | 3 events submitted at T1<T2<T3 | All 3 shown with name/client org/proposed date/submission date; ordered T1,T2,T3 | E2E |
| TC-CS-E05-S1-02 | 4 | Count matches list length | Same as TC-CS-E05-S1-01 | Open the queue | — | Count = 3, list length = 3 | Integration |
| TC-CS-E05-S1-03 | 6 | Empty state | 0 Submitted-no-coordinator events | Open the queue | — | Empty-state message shown; count = 0 | Integration |
| TC-CS-E05-S1-04 | 1 | Filter correctness | 1 Draft, 1 Under Review, 1 Approved, 1 Submitted-with-coordinator, 1 Submitted-no-coordinator | Open the queue | 5 events, mixed statuses | Only the Submitted-no-coordinator event appears | Integration |
| TC-CS-E05-S1-05 | 5 | Drop-off after assignment | 1 Submitted-no-coordinator event; coordinator assigned via SPL-60 | Assign coordinator, reopen/refresh queue | — | Event no longer appears; count decreases by 1 | E2E |
| TC-CS-E05-S1-06 | 7 | Authorization — denied | Signed in as non-EOM role | Request the queue (UI or direct API) | — | 403; no event data in response | Integration |
| TC-CS-E05-S1-07 | 7 | Authorization — unauthenticated | No/invalid auth token | Request the queue | — | 401; no data returned | Integration |
| TC-CS-E05-S1-08 | 7 | Authorization — default deny | Role check absent/misconfigured (per SPL-44 default-deny rule) | Request the queue with an ungranted role | — | Denied (fail closed) | Integration |
| TC-CS-E05-S1-09 | 4 | Boundary — single event | Exactly 1 Submitted-no-coordinator event | Open the queue | — | 1 event shown, count = 1 (not empty-state) | Integration |
| TC-CS-E05-S1-10 | 3 | Boundary — tie on submission time | 2 events, identical submission datetime | Open the queue | Same T for both | Both appear; order deterministic and stable across repeated loads — **tiebreak rule needs PO confirmation** | Integration |
| TC-CS-E05-S1-11 | 2 | Field correctness | 1 event, known field values | Open the queue | — | Displayed values match stored values exactly; no extra/missing fields | E2E |
| TC-CS-E05-S1-12 | 5 | No side effects from viewing | 1 event in queue | Open the queue twice | — | Event still present after second view; read has no side effects | Integration |
| TC-CS-E05-S1-13 | 7 | Cross-role isolation | Multi-role account holding EOM + Organiser (depends on SPL-46, still To Do) | Open queue as EOM vs as Organiser-only | — | Accessible under EOM context; denied under Organiser-only context | E2E |

## Related resources

- QA test report: [QA-SPL-59](https://clivelim01-1787647390567.atlassian.net/wiki/spaces/QS/pages/5111924/QA-SPL-59)
- Every test case ID above is greppable in the test suite — TC-CS-E05-S1-10 is `test_tc_e05_s1_10_equal_submission_times_tie_break_on_request_id`.
- DevOps report — to be added once the branch is merged.
