# SPL-60 — CS-E05-S2: Assign an Event Coordinator

**Epic:** SPL-5 CS-E05 Coordinator Assignment (priority 2 of 4)
**Assignee:** Clive Lim
**Status (Jira):** Dev Ops — awaiting merge of PR #16

## User story

As an Event Operations Manager, I want to assign an Event Coordinator to a
submitted event so that they can start planning it.

## Acceptance criteria

1. The manager can choose an Event Coordinator from a list.
2. An event can be assigned only if it has no assigned coordinator.
3. An event that already has an assigned coordinator cannot be assigned again.
4. The event records which Event Coordinator is assigned to it, with no
   acceptance step required from the coordinator.
5. On assignment the event remains Submitted; SPL-70 owns the coordinator's explicit transition
   to Under Review. This supersedes the original combined assignment/status interpretation.
6. The Event Organiser sees the assigned coordinator's name when they view
   the event.
7. The event's history records who assigned, who was assigned, and when —
   visible to the Event Operations Manager.
8. When there are no Event Coordinators to choose from, the manager is told
   why and the assignment does not complete.
9. A user without the Event Operations Manager role who attempts to assign
   is denied.

## Out of scope

- Changing an existing coordinator — SPL-61.
- Role authorisation — provided by SPL-44.
- Notifying the coordinator that they have been assigned.
- Any workload, capacity or availability rule for choosing between
  coordinators.

## Open questions / assumptions (unconfirmed)

- Status name "Under Review" (AC5) is a proposal.
- "An event with no coordinator is always Submitted in R1" — if a status is
  ever added before assignment, this story keys off the coordinator, not
  the status. Test defensively (TC-CS-E05-S2-06) in case the UI path is bypassed.
- How the manager picks which coordinator (workload/availability) is a
  business judgement outside the system — no rule enforced (Q95).
- Coordinators are not notified of assignment in R1 — to be confirmed.

## Dependencies (blocking full implementation)

- **SPL-44** (Ryan, *Done*, PR #14) — reusable role-authorization mechanism
  (AC9).
- **SPL-59** (this epic, priority 1) — the queue this action is launched
  from; built on the same branch.
- **SPL-51** (Ranveer, *In Progress*) — the real event entity; `events` is
  provisional until then.
- **SPL-55** (lin wang, *To Do*) — Submitted events must exist first.

## Implementation status (branch `clive`, not merged)

Shared design notes: [architecture](../architecture.md#coordinator-assignment).

- `GET /api/event-requests/<id>/coordinator-options` — active Event Coordinators, or
  `unavailable_reason` when none exist (AC1, AC8).
- `POST /api/event-requests/<id>/coordinator` — assigns immediately while leaving the request
  Submitted (AC2–5, AC9). The one-row-per-request key makes the first of two concurrent
  assignments win (TC-CS-E05-S2-04, proved on PostgreSQL). SPL-70 separately starts review.
- `GET /api/event-requests/<id>/coordinator-history` — who assigned whom and when (AC7).
- Workspace queue has an inline assignment panel (no modal).
- **AC6 is met.** The organiser's own request view (CS-E07-S1) now names the coordinator
  responsible, or says none is assigned yet. Reads there are already scoped to the organiser's
  own requests, so nothing is disclosed across organisations.
- **Status vocabulary:** CS-E07-S1 owns it in `app.event_statuses`; this story reads that module.
  Assignment does not stamp `status_changed_at`; SPL-70 does so when review begins.
- **Needs team agreement:** the picker is filtered by a new `accounts.is_active`
  flag, which no story manages yet. Coordinator names come from
  `accounts.display_name`, which SPL-45 now owns and makes non-null, so only
  `is_active` is still unowned.

## Test cases

| ID | AC | Scenario | Pre-conditions | Steps | Test data | Expected result | Level |
|---|---|---|---|---|---|---|---|
| TC-CS-E05-S2-01 | 1,4,5,6,7 | Happy path — assign coordinator | Signed in as EOM; 1 Submitted event, no coordinator; 2 active Event Coordinators exist | Select event, pick a coordinator, confirm | Coordinator "Alice" | Status remains Submitted; coordinator = Alice; Organiser sees "Alice"; history records assigner, Alice, timestamp; no pending/acceptance state | E2E |
| TC-CS-E05-S2-02 | 1 | Picker shows only active Event Coordinators | 2 active Coordinators, 1 inactive Coordinator, 1 active Venue Staff | Open the coordinator picker | — | Only the 2 active Coordinators listed; inactive and other-role users excluded | Integration |
| TC-CS-E05-S2-03 | 3 | Cannot assign an already-assigned event | Event already has a coordinator | Attempt to assign again | — | Refused; existing coordinator unchanged; no duplicate history entry | Integration |
| TC-CS-E05-S2-04 | 3 | Concurrency — two EOMs assign the same event simultaneously | 1 unassigned Submitted event; 2 EOM sessions | Both submit an assignment for the same event near-simultaneously | 2 different coordinators picked | Exactly one assignment succeeds; the other is refused as "already assigned"; no split-brain state | Integration |
| TC-CS-E05-S2-05 | 8 | No active coordinators available | 0 active Event Coordinator-role users | Attempt to assign | — | Manager told why (specific reason, not a generic error); assignment not completed | Integration |
| TC-CS-E05-S2-06 | 2 | Defensive — reject assignment on non-Submitted event | Event in Draft/Under Review/Approved status, no coordinator (bypassing UI, e.g. direct API call) | Attempt to assign | — | Refused server-side even though client UI wouldn't normally allow it | Integration |
| TC-CS-E05-S2-07 | 9 | Authorization — denied | Signed in as non-EOM role | Attempt to assign | — | 403; no state change | Integration |
| TC-CS-E05-S2-08 | 9 | Authorization — unauthenticated | No/invalid auth token | Attempt to assign | — | 401; no state change | Integration |
| TC-CS-E05-S2-09 | 7 | History visible to EOM only where specified | After a successful assignment | EOM views event history | — | Assigner, assignee, timestamp all present and accurate | Integration |
| TC-CS-E05-S2-10 | 1 | Boundary — exactly one active coordinator | 1 active Event Coordinator | Open the picker | — | That coordinator is the only option; assignable | Integration |

## Related resources

- QA test report: [QA-SPL-60](https://clivelim01-1787647390567.atlassian.net/wiki/spaces/QS/pages/4882482/QA-SPL-60)
- Every test case ID above is greppable in the test suite — TC-CS-E05-S2-04 is `test_tc_e05_s2_04_concurrent_assignment_cannot_overwrite_the_first`.
- DevOps report — to be added once the branch is merged.
