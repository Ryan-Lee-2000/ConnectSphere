# SPL-74 — Pre-fill venue search from the event

## Story and requirement source

Assignee: Daniel Seow Shi Hong.

As an Event Coordinator, I want venue-search criteria filled from the event so that I do not
have to re-enter information already provided.

Source: Jira SPL-74 (CS-E08-S4), Week 4 core requirement #10; customer answers Q75, Q83, Q111.

## Acceptance criteria

1. Opening search from an event fills its date, mapped operating slots, expected attendance,
   room layout, facilities, accessibility requirements, and location preference where recorded.
2. The coordinator can alter search criteria without changing the event request.
3. Missing optional requirements do not prevent searching.
4. Reopening search uses the event's currently recorded information.

## Scope and dependencies

Reuse the permanent assigned-event venue-search screen and its local editable controls from
SPL-71–73. SPL-51/52 supply the recorded event requirements. The existing assigned-coordinator
and Planning-stage boundaries remain applicable. No schema, migration, or API contract changes.

Refreshing the assigned-event read on a detail/search view change makes current-data loading
explicit even when navigation preserves the component. Existing route remounts also reload it.
Search controls remain local copies and queries use the existing read-only availability API.

Excluded: modifying the event through search, compulsory preferred venues, booking changes,
new search screens, and work on other stories.

## Automated test traceability

Dedicated executable file: `frontend/src/VenueSearchPrefill.test.tsx`.

| Case | AC | Scenario and expected result |
| --- | --- | --- |
| TC-SPL-74-01 | 1 | Load an assigned Planning event. All seven recorded criteria populate the controls, including slot selection and requirement chips. |
| TC-SPL-74-02 | 2 | Edit all seven criteria and search. The GET query contains the edited criteria; the original event is unchanged and no write request is made. |
| TC-SPL-74-03 | 3 | Load an event missing every optional requirement. Search remains enabled with valid date, slots and attendance and sends explicit empty optional filters. |
| TC-SPL-74-04 | 4 | Edit a filter, leave search, change the server record, then reopen search without remounting. A fresh event read populates all updated criteria and discards the exploratory edit. |

Additional cases establish the professor's minimum of two executable tests per acceptance criterion:

| Case | AC | Scenario and expected result |
| --- | --- | --- |
| TC-SPL-74-05 | 1 | Night-only event with custom layout, facilities, accessibility and location absent from catalogue suggestions. Recorded selections remain available and selected. |
| TC-SPL-74-06 | 2 | Clear all optional filters, rerender with equivalent event values, and search. The local blank remains selected and is sent explicitly without clearing the event or its brief. Covered by the screen journey and a component regression for fresh array references. |
| TC-SPL-74-07 | 3 | Only some optional requirements are recorded. Search succeeds and retains the recorded facility filter while leaving other optionals empty. |
| TC-SPL-74-08 | 4 | Unmount and reopen search after saved optional requirements are removed. A fresh read clears old preferences and prior search results. |

Coverage count: AC1 = 01/05; AC2 = 02/06; AC3 = 03/07; AC4 = 04/08.

Focused command:

```sh
npm exec --yes --package=pnpm@10.15.1 -- pnpm --dir frontend test VenueSearchPrefill.test.tsx
```

Required regression gate: `npm run verify`.

## Manual walkthrough before review

1. Sign in as the assigned Event Coordinator and open an event in Planning.
2. Choose Find venues; compare date, slots, attendance and optional criteria with the event brief.
3. Alter filters and search; return to the event and confirm its recorded requirements are unchanged.
4. Reopen search and confirm the recorded criteria return, rather than the exploratory values.
5. Repeat with no optional requirements and confirm searching remains available.

## Verification and delivery

Verification date: 2026-10-01.

Focused component checks: 8 screen-prefill cases and 7 venue-search component cases passed (TC-SPL-74-06 is covered in both files). The focused case passed 10 consecutive runs after adding an explicit wait for filter options to load.

Reset-race follow-up on `codex/SPL-74-clear-filter-fix`: the prop-synchronization effect was removed because it could reapply the event snapshot over local exploratory filters after a parent render. Search state initializes from the event snapshot on mount; leaving and reopening the search mounts it again with the latest assigned-event read. A component regression rerenders with equivalent event values and fresh array references after clearing, then confirms the layout remains blank in the search query.

Latest `npm run verify` on 2026-10-01: PASS — Ruff lint and formatting; 1,109 Python tests passed / 54 skipped; 280 frontend tests passed; TypeScript check and production build passed. The build reports the existing large-chunk advisory; it does not fail the build. Executed in the SCHOOL checkout using the repository's temporary Node 24 runtime. Existing React `act(...)` warnings in unrelated tests remain non-failing. The initially restricted run failed the fixture-server test because local sockets/process signals were denied; the permitted rerun passed. A test-fixture response typing error was corrected before the earlier final pass.

`npm run budget`: UNKNOWN (dated snapshot, live account usage unverified).
Browser E2E: not run. Manual walkthrough: passed, reported by Daniel on 2026-10-01.
PostgreSQL-specific gate: not required by this frontend-only change; no migration or DB rules changed.
Daniel reported the documented manual walkthrough as “all clear”; this is assignee-reported evidence, not an agent-observed browser run.
The previously failing main run reported an `available-venues` request with `preferred_room_layout=Theatre`. This regression is addressed by the local change above; a new CI run is required to verify it in GitHub Actions. PR review and hosted deployment: pending.
