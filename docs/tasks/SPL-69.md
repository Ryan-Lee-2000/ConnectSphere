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

## Two tests per acceptance criterion

This follow-up is based on main `da9a995` (merged SPL-66 PR #54). It changes tests and documentation
only; no application logic, API or migration changes. Source: current Jira SPL-69, Week 4 core #4,
and Q103, checked on 1 October 2026.

| AC | First named case | Second named case |
| --- | --- | --- |
| 1 — Assigned coordinator / allowed status | TC-SPL-69-01: each permitted state | TC-SPL-69-17: reassignment changes who may withdraw |
| 2 — Optional note | TC-SPL-69-02: absent or empty note | TC-SPL-69-19: supplied multiline note is retained |
| 3 — Withdrawn / actor / time | TC-SPL-69-01: successful withdrawal evidence | TC-SPL-69-18: persisted evidence agrees across authorised reads and audit |
| 4 — Retrievable / no further review or planning | TC-SPL-69-08: authorised retrieval and client isolation | TC-SPL-69-09: subsequent workflow actions are refused |
| 5 — Distinct from rejection / cancellation | TC-SPL-69-15: real rejection and withdrawal keep separate fields and audits | TC-SPL-69-16: a cancelled event remains Cancelled and cannot be withdrawn |
| 6 — Invalid / unauthorised leaves unchanged | TC-SPL-69-03: other roles refused | TC-SPL-69-04: unassigned coordinator refused |

All primary cases are executable backend tests in `backend/tests/test_withdraw_event_request.py`.
Parameter variations are not counted as separate named cases. TC-SPL-69-01 checks both AC1 and AC3;
it is intentionally mapped to both rather than duplicated. Cases 05–07 add invalid-state, payload,
identity/time-injection and note-boundary coverage. Cancellation is a seeded existing outcome in
case 16; this test does not claim to implement or verify a cancellation API.

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
| TC-SPL-69-15 | 5 | Withdraw one request and reject another through the real APIs | Distinct status labels, evidence fields and audit actions; no rejection evidence on withdrawal or vice versa | API/database |
| TC-SPL-69-16 | 5 | Compare a withdrawn request with an existing cancelled event; try withdrawing the cancelled event | Labels remain Withdrawn and Cancelled; cancelled event and audit remain unchanged | API/database |
| TC-SPL-69-17 | 1 | Reassign from Alice to Bob; attempt withdrawal as both | Old assignee gets 404 unchanged; current assignee succeeds and is recorded | API/database |
| TC-SPL-69-18 | 3 | Withdraw and read through organiser/coordinator endpoints and database | Actor and timestamp agree with persisted status/audit; timestamp is server-generated within the request interval | API/database |
| TC-SPL-69-19 | 2 | Supply a whitespace-padded multiline note | Outer whitespace is trimmed, internal newline retained, saved note retrievable | API/database |

## Automated test traceability

- TC-SPL-69-01 to TC-SPL-69-10 and TC-SPL-69-15 to TC-SPL-69-19: `backend/tests/test_withdraw_event_request.py`
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

Run `npm run verify` before review. Run the disposable-PostgreSQL `npm run integration` gate when
changing database behavior, and applicable browser checks when changing the interface. This
follow-up changes test assertions and documentation only; separate PostgreSQL and browser checks
have not been rerun. Prior implementation evidence must not be relabelled as a new run.

## Verification — 1 October 2026

- Focused backend: 33 passed across 15 named tests, including parameter variants.
- Full gate: `npm run verify` passed — 1,116 backend tests passed / 54 skipped; 280 frontend tests passed; Ruff lint/format, TypeScript and production build passed.
- Latest main CI: [run 36865016632](https://github.com/Ryan-Lee-2000/ConnectSphere/actions/runs/36865016632) failed in SPL-74 case TC-SPL-74-06; deployment skipped. This is separate from the passing local SPL-69 follow-up.
- Budget: UNKNOWN; live account usage unverified.
- Manual QA / browser E2E / separate PostgreSQL integration: not newly executed for this follow-up.
- Original implementation: [PR #50](https://github.com/Ryan-Lee-2000/ConnectSphere/pull/50), merged.
- Follow-up: local branch `codex/SPL-69-test-ac-coverage`; publication prepared for review; see the branch PR for current CI/review status.

## Report and repository links

- [QA-SPL-69](https://clivelim01-1787647390567.atlassian.net/wiki/spaces/QS/pages/11272210/QA-SPL-69)
- [DEVOPS-SPL-69](https://clivelim01-1787647390567.atlassian.net/wiki/spaces/QS/pages/11206732/DEVOPS-SPL-69)

The reports link to each other and distinguish original delivery evidence from this local test-only follow-up.
See the [repository map](../../README.md#repository-map) and [documentation index](../README.md).

## Out of scope

- An in-system withdrawal request initiated directly by the Event Organiser.
- Reopening, resubmitting or planning a withdrawn request.
- Notification delivery; SPL-102 remains a future integration.
