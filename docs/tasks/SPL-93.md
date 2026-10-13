# SPL-93 — Mark a requested item as unavailable

**User outcome:** Technical Support can explain why an unheld Requested equipment requirement
cannot currently be fulfilled, the assigned coordinator can see that decision, and Technical
Support can return the same line to Requested without losing its history.

## Acceptance-criteria test map

| Acceptance criterion | Test cases | Evidence |
| --- | --- | --- |
| AC1: mark an unheld Requested line Unavailable with a non-blank reason and optional suggestion | TC-SPL-93-001 marks and audits a valid decision; TC-SPL-93-002 rejects blank, unexpected and reserved inputs; TC-SPL-93-007 checks client-side required reason; TC-SPL-93-008 sends reason and suggestion | `backend/tests/test_equipment_requirement_unavailability.py`, `frontend/src/EquipmentAvailability.test.tsx` |
| AC2: assigned coordinator sees status, reason and suggestion; other lines/reservations remain unchanged | TC-SPL-93-003 checks the coordinator read model and an unaffected sibling line; TC-SPL-93-004 protects mutations by role; TC-SPL-93-009 renders the complete coordinator history | backend API and `frontend/src/EquipmentRequirements.test.tsx` |
| AC3: restore Unavailable to Requested while retaining earlier reason, actor and time history | TC-SPL-93-005 restores and preserves both entries; TC-SPL-93-006 rejects invalid/unauthorised restores without erasing history; TC-SPL-93-008 drives the restore control | backend API and `frontend/src/EquipmentAvailability.test.tsx` |

The six server test IDs and three component test IDs map every acceptance criterion to at least
two meaningful tests. This is 3 of 3 acceptance criteria covered (100% acceptance-criteria
coverage); it is not a measured code-coverage percentage.

## Interface and schema

- `POST /api/equipment-requirements/{id}/mark-unavailable` — Technical Support only; accepts
  `reason` and optional `alternative_suggestion`. Only a Requested line with no currently held
  reservation may transition to Unavailable.
- `POST /api/equipment-requirements/{id}/restore-requested` — Technical Support only; no body;
  only an Unavailable line with no held reservation returns to Requested.
- The existing equipment-availability response includes `unavailability_history`; the assigned
  coordinator's existing equipment-requirements response includes that same audit history.
- `s3_requirement_unavailability` adds
  `equipment_requirement_unavailability_records`, an append-only RLS-protected history table.
  It follows `s3_notifications`, the main migration head after SPL-101 merged.

## Integration boundary

This story changes only `EquipmentRequirement.status` and writes its own history. It does not
change an event, physical equipment stock, or any reservation. Both actions require the parent
event to be Planning, Confirmed or Postponed, matching the Technical Support review queue.
The transaction locks the event first, then the stock pool and requirement row. Holding the
event lock through commit serializes decisions with concurrent lifecycle changes; re-reading
after a wait refuses a newly closed event without changing the requirement or audit history.
The event-first order matches event-wide release; the pool still precedes the requirement so
the zero-held-unit rule remains protected against concurrent reservations.

## Focused checks

```sh
./.venv/bin/python -m pytest backend/tests/test_equipment_requirement_unavailability.py -v
frontend/node_modules/.bin/vitest run frontend/src/EquipmentAvailability.test.tsx frontend/src/EquipmentRequirements.test.tsx
npm run verify
npm run integration
```

Run browser evidence and the manual workflow after the local stack is running. Record actual
results in the published QA and DevOps reports; do not claim a passing CI or deployment before it
is verified.

## Verification after main integration — 2026-10-13

Merged main at `d91f52c` into the existing SPL-93 branch. Conflict resolution retains both
requirement-change and unavailable/restored histories; the unmerged SPL-93 migration now follows
`s3_notifications`. Alembic reports exactly one head.

- `nvm use` then `VITEST_POOL=vmThreads VITEST_MAX_WORKERS=1 VITEST_MIN_WORKERS=1 npm run verify`: passed; Ruff lint/format passed, 1,583 backend tests passed / 92 skipped, 385 frontend tests passed, type-check and production build passed.
- `npm run integration` against a new empty disposable PostgreSQL 17.4 container: 90 passed. This includes migration rerunnability, product-table RLS and browser-role grant denial. Existing Supabase data was not used or reset.
- Manual functional testing previously passed as reported by Daniel: blank-reason rejection, mark unavailable with reason/alternative, restore, and assigned-coordinator audit-history visibility. Not repeated during this integration.
- Earlier repository E2E had three Daniel-reported SPL-90/SPL-95 failures caused by the missing `Northstar Leadership Retreat` fixture. E2E not rerun; no passing E2E claim.
- Budget check returned UNKNOWN; live usage unverified. CI, review, merge and deployment remain separate evidence.


## Ryan review follow-up

[Review request](https://github.com/Ryan-Lee-2000/ConnectSphere/pull/80#discussion_r4259160490):
refuse mark/restore actions on closed events, including concurrent lifecycle transitions.

- TC-SPL-93-010/011: both actions return 409 on Cancelled and Completed events and all other
  inactive event states, preserving the complete history, line status, sibling line and reservation.
- Active-state checks retain mark/restore on Planning, Confirmed and Postponed events.
- TC-SPL-93-012: eight real PostgreSQL races cover both actions, both terminal states and both
  transaction orderings. The shared race driver proves the competing writer waits on a row lock.
  Closure first refuses the decision without mutation; decision first commits one audit entry
  before closure proceeds. Included in `npm run integration`.
- Focused tests passed: 31 API/lifecycle cases and eight PostgreSQL races. Initial fixture errors
  (required event times, foreign-key insert order, migration-seeded organisation ID) and import
  formatting were corrected before these passes.
- No migration, frontend or API-payload changes. Earlier manual/E2E evidence remains as reported
  above; neither was repeated for this review fix.

Final review-fix checks: full `npm run verify` passed (lint/format, backend tests, 385 frontend tests, type-check and production build); `npm run integration` passed all 98 cases, including the eight new races. Budget remained UNKNOWN. E2E and manual testing were not rerun.
