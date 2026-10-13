# Shared equipment browser fixture repair

## Selected maintenance task

User-authorised repair of the three SPL-90/SPL-95 browser failures reported during SPL-93 work.
The tests assumed manually prepared Northstar/Civic Arts events. Main's E2E preparation only
created SPL-97 scenarios. Product behaviour, sprint scope and migrations are unchanged.

## Acceptance criteria

- A clean local setup plus the standard E2E runner supplies the assigned Planning event,
  equipment catalogue and consultation choices needed by both SPL-90 journeys.
- SPL-95 receives a six-unit unreserved microphone requirement and a partially reserved plinth
  requirement with zero free stock and a two-unit shortfall, including D-1 collection.
- SPL-97's feasible/infeasible review and partial-reservation scenarios remain independent.
- Preparation uses the browser fixture's exact Auth identity and validates its application role;
  another coordinator with a lower UUID must not take ownership accidentally.
- Preparation is repeatable. Cleanup removes owned events, assignments, requirements and
  reservations before deleting their stock pools, preserving ordinary development records.
- Fixture-content tests exercise the real scripts and Flask read APIs. Browser tests still assert
  the original user outcomes and run without manual event creation or weakened authentication.

## Implementation and checks

`scripts/equipment_e2e_fixtures.py` owns the named disposable scenarios. The preparation wrapper
resolves the configured local Auth emails from `auth.users` through the local database connection,
checks their trusted roles, and prepares all scenarios in one transaction. Both preparation and
cleanup reuse the same exact event/type names. No Auth users or role assignments are modified.

The browser journeys use `E2E SPL-90 Northstar Leadership Retreat` and
`E2E SPL-95 Civic Arts Open Studio`, with dedicated stock pools and a fixed 20 October 2030 date.
The SPL-90 mutation walkthrough explicitly selects its own microphone fixture.

Regression coverage: `scripts/tests/test_equipment_e2e_scenarios.py` (API visibility, stock
calculations, preservation of unrelated data, repeat preparation and cleanup). Existing
`scripts/tests/test_prepare_e2e_equipment.py` continues to enforce the local-only database guard.

Validation on an isolated local Supabase stack (API 5500, frontend 55173, database 55322):

- Fixture regression and local-host safety tests: 9 passed.
- `npm run integration`: 90 passed against a separate initially empty PostgreSQL database.
- Full E2E runner: 37 passed, 4 failed, 7 skipped. All three repaired equipment tests and
  SPL-97 reservation/revalidation passed. The existing skips require optional SPL-129,
  SPL-137, SPL-138 and SPL-107 fixtures; no skip or timeout setting was changed.
- The four failures were clarification response, coordinator assignment, event withdrawal,
  and venue booking rejection (30-second timeouts; the clarification assignment request
  returned HTTP 401). They remain failures, not waived checks.
- Browser command: `npm run e2e -- --config .tmp/playwright.fixture.config.ts`. This uses
  the standard preparation/test/cleanup runner with only the isolated frontend URL changed.
- `npm run budget`: UNKNOWN (stale account-usage snapshot); no optional CI reruns requested.
- A diagnostic rerun after equipment cleanup still failed clarification and withdrawal;
  coordinator assignment and venue rejection passed (3 passed, 2 failed including the
  assignment role-boundary test). This does not erase the original full-suite failures.
- `npm run verify`: passed lint, formatting, typecheck, 1517 backend/script tests,
  362 frontend tests, and production build. Its 90 PostgreSQL skips were covered by the
  separate passing integration run. Vite reported its existing large-bundle warning.
Review and deployment remain separate from implementation; no merge or deployment is performed.
