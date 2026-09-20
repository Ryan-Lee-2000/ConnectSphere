# SPL-61 — CS-E05-S3: Reassign an Event Coordinator

**Epic:** SPL-5 CS-E05 Coordinator Assignment (priority 3 of 4)
**Assignee:** Clive Lim
**Status (Jira):** Dev Ops — awaiting merge of PR #16

## User story

As an Event Operations Manager, I want to reassign an event to a different
Event Coordinator so that planning continues when the current coordinator is
unavailable.

## Acceptance criteria

1. The manager can reassign an event that has an assigned coordinator, in
   any status other than Completed, Cancelled, Rejected or Withdrawn.
2. Events in Completed, Cancelled, Rejected or Withdrawn status cannot be
   reassigned.
3. The manager can choose from coordinators other than the event's current
   one.
4. When there are no other Event Coordinators to choose from, the manager is
   told why and the reassignment does not complete.
5. On reassignment the new coordinator can edit the event and the previous
   coordinator no longer can.
6. The Event Organiser sees the new coordinator's name in place of the
   previous one.
7. The event's history shows previous coordinator, new coordinator, who
   reassigned, and when — visible to the EOM; across multiple reassignments
   the entries read in chronological order.
8. Reassigning does not change the event's status.
9. A user without the Event Operations Manager role who attempts to
   reassign is denied.

## Out of scope

- The reassignment screen — SPL-62 owns the coordinator's assigned-events
  list it would be launched from.
- Role authorisation — provided by SPL-44.
- Notifying either coordinator of the change.

## Open questions / assumptions (unconfirmed)

- The excluded statuses in AC2 are the team's proposal.
- Whether reassignment is allowed on Confirmed events is **assumed yes** —
  needs customer confirmation.
- AC5 (edit-rights hand-over) depends on an event-edit route existing. No such
  route exists yet, so `is_assigned_coordinator()` is the single check any
  future edit route must use, and until then AC5 reduces to name-visibility
  only (TC-CS-E05-S3-05 has a conditional variant for this).
  **Proposed: move AC5 out of scope — needs team agreement.**
- Deliberately paired with SPL-60 in the same sprint — reuses its screen and
  coordinator-picker component.

## Dependencies (blocking full implementation)

- **SPL-60** — must exist first; an event needs a coordinator before it can
  be reassigned. Built on the same branch.
- **SPL-44** (Ryan, *Done*, PR #14) — role-authorization mechanism (AC9).
- Coordinator edit-permission model (referenced by AC5) — not yet confirmed
  as in scope for R1; see open questions above.
- **SPL-51** (Ranveer, *In Progress*) — the real event entity; `events` is
  provisional until then.

## Implementation status (branch `clive`, not merged)

Shared design notes: [architecture](../architecture.md#coordinator-assignment-provisional).

- `PUT /api/event-requests/<id>/coordinator` — reassigns in any status except
  Completed, Cancelled, Rejected or Withdrawn, never changes status, and
  records previous/new coordinator, who and when (AC1–4, AC7–9). The update
  applies only while the coordinator is unchanged **and** the request is still
  reassignable, both in one statement, proved with interleaved PostgreSQL
  transactions.
- `GET /api/event-requests/<id>/coordinator-options` excludes the current coordinator
  and explains when no other is active (AC3, AC4).
- AC5: `is_assigned_coordinator()` is the single check future event-edit
  routes must use; after reassignment it is true only for the new coordinator.
  No event edit route exists yet.
- **AC6 is met:** after reassignment the organiser's own request view shows the new coordinator
  in place of the previous one.
- **No reassignment UI yet** — there is no assigned-events screen to launch
  it from (SPL-62 is Daniel's). Backend and tests only.
- TC-CS-E05-S3-05 (Confirmed events) is currently allowed but deliberately not
  tested as final.

## Test cases

| ID | AC | Scenario | Pre-conditions | Steps | Test data | Expected result | Level |
|---|---|---|---|---|---|---|---|
| TC-CS-E05-S3-01 | 1,5,6,7,8 | Happy path — reassign in an allowed status | Event Under Review, coordinator = Alice; 1 other active Coordinator Bob | Select event, pick Bob, confirm | — | Coordinator = Bob; Bob can edit, Alice cannot; Organiser sees "Bob"; status unchanged (still Under Review); history: Alice→Bob, who, when | E2E |
| TC-CS-E05-S3-02 | 2 | Blocked — Completed status | Event Completed, coordinator = Alice | Attempt reassignment | — | Refused | Integration |
| TC-CS-E05-S3-03 | 2 | Blocked — Cancelled status | Event Cancelled, coordinator = Alice | Attempt reassignment | — | Refused | Integration |
| TC-CS-E05-S3-04 | 2 | Blocked — Rejected / Withdrawn status | Event Rejected (repeat for Withdrawn), coordinator = Alice | Attempt reassignment | — | Refused for both statuses | Integration |
| TC-CS-E05-S3-05 | 1 | Confirmed-status reassignment — flagged pending clarification | Event Confirmed, coordinator = Alice | Attempt reassignment | — | Currently assumed allowed; **do not implement/test as final until customer confirms** | Integration (blocked) |
| TC-CS-E05-S3-06 | 3 | Picker excludes current coordinator | Coordinator = Alice; active Coordinators = Alice, Bob, Carol | Open the reassignment picker | — | Only Bob and Carol listed; Alice excluded | Integration |
| TC-CS-E05-S3-07 | 4 | No other active coordinator available | Only active Coordinator is the current one (Alice) | Attempt reassignment | — | Manager told why; reassignment not completed | Integration |
| TC-CS-E05-S3-08 | 7 | History ordering across multiple reassignments | Event reassigned Alice→Bob, then later Bob→Carol | View event history | — | Entries read chronologically: Alice→Bob before Bob→Carol | Integration |
| TC-CS-E05-S3-09 | 8 | Status never changes on reassignment | Event in each allowed status (e.g. Under Review, Approved) | Reassign coordinator | — | Status identical before and after, for every allowed status tested | Integration |
| TC-CS-E05-S3-10 | 9 | Authorization — denied | Signed in as non-EOM role | Attempt reassignment | — | 403; no state change | Integration |
| TC-CS-E05-S3-11 | 9 | Authorization — unauthenticated | No/invalid auth token | Attempt reassignment | — | 401; no state change | Integration |
| TC-CS-E05-S3-12 | 3 | Boundary — exactly one other active coordinator | Current = Alice; only other active Coordinator = Bob | Open picker | — | Bob is the only option | Integration |
| TC-CS-E05-S3-13 | — | Negative — reassign an event with no coordinator at all | Event Submitted, no coordinator assigned | Attempt reassignment (defensive/API-level; UI shouldn't expose this) | — | Refused — reassignment presupposes an existing coordinator (use SPL-60 instead) | Integration |

## Related resources

- QA test report: [QA-SPL-61](https://clivelim01-1787647390567.atlassian.net/wiki/spaces/QS/pages/4882507/QA-SPL-61)
- Every test case ID above is greppable in the test suite — TC-CS-E05-S3-08 is `test_tc_e05_s3_08_history_reads_chronologically_across_reassignments`.
- DevOps report — to be added once the branch is merged.
