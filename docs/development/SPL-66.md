# SPL-66 — Respond to a clarification request

## Approved user story

As the responsible Event Organiser, I want to respond to a clarification request so that the Event
Coordinator can continue reviewing my event.

## Acceptance criteria and implementation state

1. **Retrieve and respond — implemented.** The responsible organiser sees a response action only
   when their event has status `returned_for_clarification`. Opening it retrieves the request and
   its clarification history before accepting a non-blank response of at most 2,000 characters.
2. **Retain evidence — implemented.** The clarification row retains the original message and adds
   the response, trusted respondent account and server timestamp. Both organiser and coordinator
   reads use the shared clarification serializer.
3. **Resume review — implemented.** A successful response atomically returns the event to
   `under_review`, appends `respond_clarification` status history and leaves the existing
   coordinator assignment unchanged.
4. **Do not edit the request — implemented.** The response endpoint accepts only `response`; event
   request fields are absent from its contract and remain unchanged.
5. **Refuse invalid attempts — implemented.** Role and owner checks refuse unrelated accounts.
   Status, clarification ownership, outstanding state and payload checks complete before commit, so
   refusal changes neither event nor clarification evidence.

## Public interface

- `POST /api/event-requests/<event_request_id>/clarifications/<clarification_id>/respond`
- Exact JSON body: `{ "response": "..." }`
- Successful response: updated event summary, transition audit and complete clarification history.
- Event Organisers use the action from **My requests**. Organisation event pages remain read only,
  so colleagues from the same client organisation cannot respond for the responsible organiser.

## Test-case traceability

| Test case | Behaviour | Automated location |
| --- | --- | --- |
| TC-SPL-66-01 | Creator retrieves and responds; response resumes review without editing request data or assignment | `backend/tests/test_respond_clarification.py`, `frontend/src/EventRequestDrafts.test.tsx` |
| TC-SPL-66-02 | Response is retained with the question, respondent and server time | `backend/tests/test_respond_clarification.py`, `backend/tests/test_respond_clarification_postgres.py`, `frontend/src/ClarificationHistory.test.tsx` |
| TC-SPL-66-03 | Events outside Returned for clarification are unchanged and refused | `backend/tests/test_respond_clarification.py` |
| TC-SPL-66-04 | Blank, malformed and status-injection payloads are unchanged and refused | `backend/tests/test_respond_clarification.py` |
| TC-SPL-66-05 | An answered clarification cannot be answered again | `backend/tests/test_respond_clarification.py` |

The complete organiser → manager → coordinator → organiser → coordinator browser journey is
`e2e/clarification-response.spec.ts` and exercises TC-SPL-66-01/02 through the permanent UI.

## Migration and security

Migration `s2_clarification_responses.py` follows `s2_event_withdrawal`. It adds nullable response,
respondent and response-time columns to the existing RLS-protected `clarification_requests` table.
A database check requires all three response evidence values together or all three absent. Existing
rows remain valid and unanswered. Access continues exclusively through role-protected Flask routes;
the existing revoked grants and RLS boundary remain in force.

The PostgreSQL-specific column and completeness-constraint checks live in
`backend/tests/test_respond_clarification_postgres.py` and run through `npm run integration`.

## Verification commands

- `uv run --project backend pytest -q backend/tests/test_request_clarification.py backend/tests/test_respond_clarification.py backend/tests/test_migration_tooling.py`
- `uv run --project backend pytest -q --basetemp /tmp/connectsphere-spl66-pytest-final`
- `pnpm --dir frontend exec vitest run src/EventRequestDrafts.test.tsx src/ClarificationHistory.test.tsx src/AssignedEvents.test.tsx src/OrganisationEvents.test.tsx`
- `pnpm typecheck`, `pnpm test` and `pnpm build`
- `npm run integration` with a fresh disposable PostgreSQL database
- `pnpm exec playwright test e2e/clarification-response.spec.ts`
- `npm run budget`

Local result on 30 September 2026: backend 1,094 passed and 54 skipped; frontend 272 passed;
PostgreSQL integration 54 passed; the SPL-66 Playwright journey passed; type-check, production build,
formatting and lint passed. The budget snapshot remained `UNKNOWN` and reported 521 of 2,000
included minutes used; repository policy treats `UNKNOWN` as requiring the normal GitHub checks.
