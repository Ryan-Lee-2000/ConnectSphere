# SPL-98 — Release a reservation

**User outcome:** Technical Support Staff can release part or all of an event's held equipment
without losing the original reservation or release audit record.

## Acceptance-criteria test map

| Acceptance criterion | Test cases | Evidence |
| --- | --- | --- |
| AC1: positive bounded release with a reason | TC-SPL-98-01 partial API release; TC-SPL-98-03 invalid quantity/reason refusal; TC-SPL-98-06 browser validation | `backend/tests/test_equipment_availability.py`, `frontend/src/EquipmentReleases.test.tsx` |
| AC2: Requested / Partially Reserved / Reserved state rules | TC-SPL-98-01 retains partial status; TC-SPL-98-02 returns a zero-held line to Requested; TC-SPL-98-08 proves release preserves Review Required; existing TC-SPL-97-02 proves fully held lines are Reserved | `backend/tests/test_equipment_availability.py` |
| AC3: release all held equipment for one event without changing event status | TC-SPL-98-04 releases two requirement lines, retains history and leaves the event in Planning; TC-SPL-98-09 verifies the confirmed event-wide browser action | backend and frontend focused tests |
| AC4: audit, failed/repeated/unauthorised protection | TC-SPL-98-01 checks audit fields and immutable original reservation; TC-SPL-98-03 checks no mutation on failure; TC-SPL-98-05 checks role and repeated-release guards; TC-SPL-98-10 proves competing PostgreSQL releases cannot double-release held stock | `backend/tests/test_equipment_availability.py`, `backend/tests/test_equipment_reservations_postgres.py` |

## Focused checks

```sh
./.venv/bin/python -m pytest backend/tests/test_equipment_availability.py -q
npx pnpm --dir frontend exec vitest run src/EquipmentAvailability.test.tsx src/EquipmentReleases.test.tsx
npm run verify
```

Run `npm run integration` with an empty disposable PostgreSQL database before review. The migration
adds a release-history table with RLS and the release routes share the equipment-type lock with
reservation and return-date changes.

## Scope boundary

SPL-98 supplies the manual partial/all equipment-release operation only. SPL-86 owns whole-event
cancellation, its all-resource rollback and removal of cancelled requirements from actionable
queues. Consumers must call the shared release operation instead of deleting reservation records.
