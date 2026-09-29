# SPL-69 — CS-E06-S6: Record withdrawal of a submitted request

**Epic:** CS-E06 Event Review and Approval
**Priority:** Medium — retained secondary review outcome
**Estimate:** 2 story points

## User story

As an Event Coordinator, I want to record an Event Organiser's withdrawal of a submitted request so
that it is not reviewed or planned further.

## Acceptance criteria

1. The assigned Event Coordinator can record withdrawal while the request is Submitted, Under
   Review, or Returned for Clarification.
2. An optional withdrawal note may be recorded.
3. Withdrawal changes the status to Withdrawn and records the actor and date and time.
4. The withdrawn request remains retrievable but cannot undergo further review or planning.
5. Withdrawal remains distinct from rejection and event cancellation.
6. An invalid or unauthorised withdrawal attempt leaves the event unchanged.

## Dependencies

- SPL-70 provides the server-owned transition policy and append-only status history.
- SPL-62 and SPL-64 provide the assigned-event entry point and protected request detail.

## Decisions and public interface

- `POST /api/event-requests/<id>/withdraw` is restricted to the currently assigned Event
  Coordinator. Its body may be empty or exactly `{"note": "<optional text>"}`; clients cannot
  provide a target status, actor or timestamp.
- `withdraw` accepts `submitted`, `under_review` and `returned_for_clarification`, and atomically
  produces `withdrawn`. The audit row records the actual previous status.
- `event_requests` retains `withdrawn_by_account_id`, `withdrawn_at` and optional
  `withdrawal_note`. A check constraint prevents a partial withdrawal record.
- The assigned coordinator and responsible organiser can continue reading the request and its
  withdrawal evidence. Existing record scoping continues to hide it from unrelated organisers.
- Withdrawn is terminal in the current transition policy. It is separate from Rejected and
  Cancelled and creates no booking or planning action.
- The coordinator detail uses an inline confirmation with an optional note, matching the existing
  operational interaction pattern.

## Consolidated test cases

| ID | AC | Scenario | Expected result | Level |
| --- | --- | --- | --- | --- |
| TC-SPL-69-01 | 1,3,5 | Assigned coordinator withdraws from each permitted status | Status becomes Withdrawn; actor, time and actual prior status are recorded; assignment remains | API/database |
| TC-SPL-69-02 | 2 | Withdraw with no note, null, empty or whitespace note | Withdrawal succeeds and stores no note | API |
| TC-SPL-69-03 | 6 | Organiser or Operations Manager attempts withdrawal | Request is refused and unchanged | API |
| TC-SPL-69-04 | 6 | Unassigned coordinator attempts withdrawal | 404 is returned and the protected request is unchanged | API |
| TC-SPL-69-05 | 1,4,5,6 | Withdraw from a non-permitted or terminal status | 409 is returned with no status, audit or evidence change | API |
| TC-SPL-69-06 | 2,3,6 | Supply invalid fields, client status or a non-text note | 400 is returned and nothing changes | API |
| TC-SPL-69-07 | 2,6 | Exercise the 2,000-character note boundary | 2,000 succeeds; 2,001 is refused unchanged | API |
| TC-SPL-69-08 | 4 | Responsible users retrieve the withdrawn request | Outcome remains readable; unrelated organiser receives 404 | API |
| TC-SPL-69-09 | 4,5 | Attempt review, approval, clarification, rejection or withdrawal again | Every action is refused; no booking is created | API |
| TC-SPL-69-10 | 3,6 | Persist incomplete withdrawal evidence directly | Database constraint refuses it | Database |
| TC-SPL-69-11 | 1,4 | Render actions across statuses | Withdrawal is offered only in the three permitted statuses | UI |
| TC-SPL-69-12 | 2,3,4 | Confirm through the coordinator interface | API is called once and retained actor, time and note are shown | UI |
| TC-SPL-69-13 | 6 | Cancel locally or receive server refusal | No action is sent on cancel; refused form and note remain actionable | UI |
| TC-SPL-69-14 | 1,2,3,4 | Submit, assign and withdraw through the browser | Withdrawn status and retained evidence are visible; review actions are gone | Browser |

## Automated test traceability

- TC-SPL-69-01 to TC-SPL-69-10: `backend/tests/test_withdraw_event_request.py`
- TC-SPL-69-11 to TC-SPL-69-13: `frontend/src/AssignedEvents.test.tsx`
- TC-SPL-69-14: `e2e/event-request-withdrawal.spec.ts`
- Migration head and clean upgrade: `backend/tests/test_migration_tooling.py` and `npm run integration`

Find every executable story case:

```sh
rg -n "TC-SPL-69" docs backend/tests frontend/src e2e
```

Run the focused checks:

```sh
uv run pytest backend/tests/test_withdraw_event_request.py -q
pnpm --dir frontend exec vitest run src/AssignedEvents.test.tsx
```

Run `npm run verify`, the disposable-PostgreSQL `npm run integration` gate and the applicable
browser regression suite before review.

## Out of scope

- An in-system withdrawal request initiated directly by the Event Organiser.
- Reopening, resubmitting or planning a withdrawn request.
- Notification delivery; SPL-102 remains a future integration.
