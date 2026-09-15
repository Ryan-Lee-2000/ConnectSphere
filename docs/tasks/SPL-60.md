# SPL-60 — CS-E05-S2: Assign an Event Coordinator

**Epic:** SPL-5 CS-E05 Coordinator Assignment (priority 2 of 4)
**Assignee:** Clive Lim
**Status (Jira):** To Do — blocked, see Dependencies

## User story

As an Event Operations Manager, I want to assign an Event Coordinator to a
submitted event so that I can hand it to someone accountable for planning it.

## Acceptance criteria

1. The manager can choose from every active user holding the Event
   Coordinator role.
2. An event can be assigned only if it has no assigned coordinator.
3. An event that already has an assigned coordinator cannot be assigned again.
4. On assignment the coordinator becomes responsible immediately — no
   acceptance step required from them.
5. On assignment the event status changes from Submitted to Under Review.
6. The Event Organiser sees the assigned coordinator's name when they view
   the event.
7. The event's history records who assigned, who was assigned, and when —
   visible to the Event Operations Manager.
8. When no active user holds the Event Coordinator role, the manager is told
   why and cannot complete the assignment.
9. A user without the Event Operations Manager role who attempts to assign
   is denied.

## Open questions / assumptions (unconfirmed)

- Status name "Under Review" (AC5) is a proposal.
- "An event with no coordinator is always Submitted in R1" — if a status is
  ever added before assignment, this story keys off the coordinator, not
  the status. Test defensively (TC-60-06) in case the UI path is bypassed.
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
- `POST /api/event-requests/<id>/coordinator` — assigns immediately and moves the
  request from Submitted to Under Review (AC2–5, AC9). The one-row-per-request key
  plus a conditional status update make the first of two concurrent
  assignments win (TC-60-04, proved on PostgreSQL).
- `GET /api/event-requests/<id>/coordinator-history` — who assigned whom and when (AC7).
- Workspace queue has an inline assignment panel (no modal).
- **AC6 is met.** The organiser's own request view (CS-E07-S1) now names the coordinator
  responsible, or says none is assigned yet. Reads there are already scoped to the organiser's
  own requests, so nothing is disclosed across organisations.
- **Status vocabulary:** CS-E07-S1 owns it in `app.event_statuses`; this story reads that module
  and stamps `status_changed_at` when it moves a request to Under Review.
- **Not done — AC6** (Organiser sees the coordinator name): there is no
  organiser event view yet (SPL-51/SPL-63) and no organisation isolation
  (SPL-45) to scope it safely.
- **Needs team agreement:** "active" is a new `accounts.is_active` flag and
  names come from a new `accounts.display_name`; no story manages either yet.

## Test cases

| ID | AC | Scenario | Pre-conditions | Steps | Test data | Expected result | Level |
|---|---|---|---|---|---|---|---|
| TC-60-01 | 1,4,5,6,7 | Happy path — assign coordinator | Signed in as EOM; 1 Submitted event, no coordinator; 2 active Event Coordinators exist | Select event, pick a coordinator, confirm | Coordinator "Alice" | Status → Under Review; coordinator = Alice; Organiser sees "Alice"; history records assigner, Alice, timestamp; no pending/acceptance state | E2E |
| TC-60-02 | 1 | Picker shows only active Event Coordinators | 2 active Coordinators, 1 inactive Coordinator, 1 active Venue Staff | Open the coordinator picker | — | Only the 2 active Coordinators listed; inactive and other-role users excluded | Integration |
| TC-60-03 | 3 | Cannot assign an already-assigned event | Event already has a coordinator | Attempt to assign again | — | Refused; existing coordinator unchanged; no duplicate history entry | Integration |
| TC-60-04 | 3 | Concurrency — two EOMs assign the same event simultaneously | 1 unassigned Submitted event; 2 EOM sessions | Both submit an assignment for the same event near-simultaneously | 2 different coordinators picked | Exactly one assignment succeeds; the other is refused as "already assigned"; no split-brain state | Integration |
| TC-60-05 | 8 | No active coordinators available | 0 active Event Coordinator-role users | Attempt to assign | — | Manager told why (specific reason, not a generic error); assignment not completed | Integration |
| TC-60-06 | 2 | Defensive — reject assignment on non-Submitted event | Event in Draft/Under Review/Approved status, no coordinator (bypassing UI, e.g. direct API call) | Attempt to assign | — | Refused server-side even though client UI wouldn't normally allow it | Integration |
| TC-60-07 | 9 | Authorization — denied | Signed in as non-EOM role | Attempt to assign | — | 403; no state change | Integration |
| TC-60-08 | 9 | Authorization — unauthenticated | No/invalid auth token | Attempt to assign | — | 401; no state change | Integration |
| TC-60-09 | 7 | History visible to EOM only where specified | After a successful assignment | EOM views event history | — | Assigner, assignee, timestamp all present and accurate | Integration |
| TC-60-10 | 1 | Boundary — exactly one active coordinator | 1 active Event Coordinator | Open the picker | — | That coordinator is the only option; assignable | Integration |
