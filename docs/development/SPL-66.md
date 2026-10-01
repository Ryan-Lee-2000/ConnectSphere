# SPL-66 — Respond to a clarification request

## Story and requirement source

Assigned developer: Daniel Seow Shi Hong.

As the responsible Event Organiser, I want to respond to a clarification request so that the Event
Coordinator can continue reviewing my event.

Source: [Jira SPL-66](https://clivelim01-1787647390567.atlassian.net/browse/SPL-66),
CS-E06-S3; Week 4 core #4; Q15, Q81 and Q102. The following criteria were checked against Jira
on 1 October 2026.

## Acceptance criteria

1. The responsible Event Organiser can retrieve and respond to an outstanding clarification request
   for their event.
2. The response is retained with the clarification message, respondent, and date and time.
3. A successful response returns the event to Under Review and preserves its assigned Event Coordinator.
4. Responding does not directly edit the submitted event-request fields.
5. A response from an unrelated organiser or from an invalid event status is refused without changing
   the event.

## Scope and dependencies

SPL-65 supplies clarification requests; SPL-70 supplies controlled review transitions; SPL-51–54
supply the submitted event information. The permanent organiser response form and shared history
component remain in use.

This follow-up strengthens tests and corrects test traceability only. It changes no application
behaviour, API contract or migration. Direct editing of submitted event fields remains out of scope.
No requirement or acceptance criterion is changed.

## Public interface

- `POST /api/event-requests/<event_request_id>/clarifications/<clarification_id>/respond`
- Exact JSON body: `{ "response": "..." }`
- Successful response: updated event summary, transition audit and complete clarification history.
- Organisers use **My requests**. Only the responsible organiser can respond; same-client colleagues
  retain read-only access.
- Responses must be non-blank and at most 2,000 characters; the server derives respondent and time.

## Two tests per acceptance criterion

The minimum is met by distinct named backend tests, without counting parameter variants, frontend
checks or the browser journey as extra cases. All primary cases below are in
`backend/tests/test_respond_clarification.py`.

| AC | First case | Second case |
| --- | --- | --- |
| 1 — Retrieve and respond | TC-SPL-66-01: successful responsible-organiser response | TC-SPL-66-07: retrieve the outstanding question and answer its returned ID |
| 2 — Retain evidence | TC-SPL-66-02: both authorised readers retrieve complete persisted evidence | TC-SPL-66-08: a second clarification cycle preserves both questions and responses |
| 3 — Resume review and preserve coordinator | TC-SPL-66-09: persisted status/audit agree and the entire assignment is unchanged | TC-SPL-66-10: preserve the replacement coordinator after reassignment |
| 4 — Preserve submitted fields | TC-SPL-66-11: successful response preserves saved content and equipment | TC-SPL-66-12: injected field changes reject the entire response without mutation |
| 5 — Refuse invalid attempts | TC-SPL-66-06: unrelated organiser and other roles refused without mutation | TC-SPL-66-03: invalid statuses refused without mutation |

## Detailed automated traceability

| Case | AC | Scenario and expected result |
| --- | --- | --- |
| TC-SPL-66-01 | 1 | The responsible organiser submits a whitespace-padded valid response. It is accepted and trimmed; persisted response, transition and assignment are checked. |
| TC-SPL-66-07 | 1 | GET retrieves the outstanding question with no answer. POST using that returned question ID succeeds and retains the supplied response. |
| TC-SPL-66-02 | 2 | After responding, organiser and assigned-coordinator GETs return identical original question/author/time and response/respondent/time. The saved response time falls within the request's server execution interval. |
| TC-SPL-66-08 | 2 | Complete a response, ask a second question through the coordinator API, and answer again. Newest-first history contains both entries, with the original evidence unchanged. |
| TC-SPL-66-09 | 3 | Respond successfully. The database holds Under Review, one matching transition audit, matching response/status/audit timestamps, and unchanged assignment identity and metadata. |
| TC-SPL-66-10 | 3 | Seed a reassignment after the original coordinator asked the question. Responding returns Under Review and preserves the replacement assignee, while retaining the original question author. |
| TC-SPL-66-11 | 4 | Populate optional requirements, registration details and two equipment lines. A response mentioning different attendance/layout values changes no event content or equipment; only permitted workflow fields may change. |
| TC-SPL-66-12 | 4 | Parameterised attempts inject attendance, name, date, facilities, registration or equipment changes. Every attempt returns 400 and preserves event content, assignment and equipment, with no response or transition audit. |
| TC-SPL-66-06 | 5 | An unrelated organiser receives 404; coordinator and manager roles receive 403. Saved content, assignment, clarification and status history remain unchanged. |
| TC-SPL-66-03 | 5 | Submitted, Under Review, Planning and Rejected events refuse the response with 409 and preserve saved content and response/audit evidence. |
| TC-SPL-66-04 | 1, 5 | Blank, whitespace-only, non-string, missing-response and status-injection bodies return 400 without response or transition evidence. |
| TC-SPL-66-05 | 1, 5 | A repeated response returns 409 and does not replace the original answer. |

### Supporting frontend, PostgreSQL and browser checks

| Case | File | Expected result |
| --- | --- | --- |
| TC-SPL-66-01 | `frontend/src/EventRequestDrafts.test.tsx` | Response action retrieves the question, sends only response text and refreshes the displayed status. |
| TC-SPL-66-02 | `frontend/src/ClarificationHistory.test.tsx` | The original question, answer, respondent, saved date and saved time are visible. |
| TC-SPL-66-13 | `backend/tests/test_respond_clarification_postgres.py` | Migrated PostgreSQL response columns have the expected types/nullability and completeness constraint. |
| TC-SPL-66-14 | `backend/tests/test_respond_clarification_postgres.py` | PostgreSQL rejects an incomplete response-evidence write. |
| TC-SPL-66-01/02 | `e2e/clarification-response.spec.ts` | The permanent organiser → manager → coordinator → organiser → coordinator journey resumes review and displays the answer. |

### ID correction

Previously TC-SPL-66-02 was reused for unrelated-account refusal, response display and schema checks.
It now consistently denotes retained response evidence. The refusal case is TC-SPL-66-06; schema and
constraint cases are TC-SPL-66-13/14. Existing QA references should use this corrected mapping.

## Migration and security

The existing merged migration `s2_clarification_responses.py` follows `s2_event_withdrawal` and adds
response, respondent and response-time columns to `clarification_requests`. The completeness check
requires all three evidence fields together or all absent. RLS and revoked browser grants remain.
This testing follow-up does not edit that migration or the schema. The PostgreSQL test changes are
ID/comment corrections only; their executable assertions are unchanged.

## Verification commands

From the repository root:

```sh
uv run --frozen pytest -q backend/tests/test_respond_clarification.py
npm exec --yes --package=pnpm@10.15.1 -- pnpm --dir frontend test ClarificationHistory.test.tsx EventRequestDrafts.test.tsx
npm run verify
npm run budget
```

For the existing PostgreSQL gate, use `npm run integration` with an empty disposable database as
described in README.md. For the existing browser journey, with the local stack running:

```sh
npm exec --yes --package=pnpm@10.15.1 -- pnpm exec playwright test e2e/clarification-response.spec.ts
```

## Verification and delivery evidence

### Testing follow-up — 1 October 2026

- Focused backend: 26 passed across 12 named acceptance cases (parameter variants expand execution count).
- Focused frontend: 7 passed across ClarificationHistory and EventRequestDrafts.
- `npm run verify`: PASS — 1,106 backend tests passed / 54 skipped; 280 frontend tests passed;
  Ruff lint/format, TypeScript and production build passed.
- `git diff --check`: passed.
- Verification used matching source under `/tmp/connectsphere-spl66-ac-check` because reads in the
  synced checkout stalled. Existing unrelated React act warnings remain non-failing.
- `npm run budget`: UNKNOWN; live account usage unverified.
- PostgreSQL integration and browser E2E: not rerun for this test-only change. PostgreSQL assertions
  and product code are unchanged; only PostgreSQL test IDs/comments changed.
- New manual QA: not performed; earlier reports remain historical.

This follow-up is prepared for review on `codex/SPL-66-test-ac-coverage`. CI, reviewer approval
and deployment for this follow-up are pending. Manual and browser results from earlier implementation work must
not be relabelled as newly executed evidence.

### Original implementation — historical evidence

The 30 September 2026 handoff recorded: 1,094 backend tests passed / 54 skipped; 272 frontend tests
passed; PostgreSQL integration 54 passed; the SPL-66 Playwright journey passed; lint, formatting,
type-check and production build passed. Original implementation PR:
[PR #52](https://github.com/Ryan-Lee-2000/ConnectSphere/pull/52), subsequently merged.
Those historical results are separate from this test-only follow-up.
