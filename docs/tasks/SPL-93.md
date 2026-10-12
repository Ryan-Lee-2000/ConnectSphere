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
  It follows `s3_equipment_return_dates`, the current main migration head.

## Integration boundary

This story changes only `EquipmentRequirement.status` and writes its own history. It does not
change an event, physical equipment stock, or any reservation. The stock pool is still locked
before the requirement row so this eligibility decision cannot race a reservation into violating
the zero-held-unit rule.

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
