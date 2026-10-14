# SPL-99 — See reservation status of each requirement

## Approved user story

As the assigned Event Coordinator, I want to see each equipment requirement's reservation state
and one equipment-readiness result so that I can identify unresolved equipment work before event
confirmation.

## Acceptance criteria and implementation

1. **Complete line state.** The assigned coordinator sees required and retained-reserved quantity,
   current status, latest planned return date, requirement and Technical Support notes,
   unavailability reasons and alternatives, and outstanding review reasons for each line.
2. **One reusable readiness rule.** Equipment is ready only when every active line has an
   Essential/Non-essential decision and catalogue mapping, and every Essential line is fully
   reserved with no outstanding review. Non-essential shortfalls stay visible without blocking.
3. **No-requirement boundary.** An event with no active equipment requirements has no equipment
   blocker. The interface states that this does not confirm the event or assess venue,
   registration or safety readiness.
4. **Read-only and scoped.** The result is available only through the existing assigned-coordinator
   detail boundary. Reading it creates no business or audit mutation, and the panel has no editing
   controls.

## Contract and design

`GET /api/event-requests/assigned/<event_id>` retains the SPL-64 detail shape and adds:

- detailed fields to each `equipment_requirements` item;
- `equipment_readiness.ready` and `has_equipment_blocker`;
- `active_requirement_count`; and
- stable blocker `code`, affected requirement id, and a coordinator-facing message.

The backend derives retained quantities from reservations minus append-only releases. Fully
released reservations do not contribute a return date. Removed lines remain visible as history but
do not participate in current readiness. The shared backend function is suitable for SPL-85 to
consume later; SPL-99 itself does not confirm an event.

The coordinator interface presents the result as a dedicated accessible, horizontally scrollable
read-only table. It uses the existing visual tokens from `DESIGN.md` and keeps the equipment-only
scope visible next to the readiness state.

## Security and migration

The existing assigned-event query continues to require the Event Coordinator role and a current
assignment. An inaccessible id and an event assigned to another coordinator retain the same
not-found boundary. Actor, role and assignment are derived from the verified session.

No schema change is required. The only model change declares the inverse SQLAlchemy relationship
for the already-migrated `equipment_review_notes` table so the projection can eager-load its
evidence without per-line queries.

## Test-case traceability

| Test case | AC | Behaviour | Automated location |
| --- | --- | --- | --- |
| TC-SPL-99-001 | 1 | Returns quantities, state, latest retained return, notes and reasons | `backend/tests/test_equipment_readiness.py` (`test_tc_spl_99_001_*`) |
| TC-SPL-99-002 | 1 | Fully released reservations contribute neither quantity nor return date | `backend/tests/test_equipment_readiness.py` (`test_tc_spl_99_002_*`) |
| TC-SPL-99-003 | 2 | Complete Essential lines permit readiness while Non-essential shortfalls remain visible | `backend/tests/test_equipment_readiness.py` (`test_tc_spl_99_003_*`) |
| TC-SPL-99-004 | 2 | Undecided, unmapped, Essential shortfall and review states return stable blockers | `backend/tests/test_equipment_readiness.py` (`test_tc_spl_99_004_*`) |
| TC-SPL-99-005 | 3 | No requirements returns no equipment blocker without changing event status | `backend/tests/test_equipment_readiness.py` (`test_tc_spl_99_005_*`) |
| TC-SPL-99-006 | 3 | Removed-only history does not create an active equipment blocker | `backend/tests/test_equipment_readiness.py` (`test_tc_spl_99_006_*`) |
| TC-SPL-99-007 | 4 | Only the assigned Event Coordinator can retrieve the projection | `backend/tests/test_equipment_readiness.py` (`test_tc_spl_99_007_*`) |
| TC-SPL-99-008 | 4 | Repeated reads leave event, requirement and audit rows unchanged | `backend/tests/test_equipment_readiness.py` (`test_tc_spl_99_008_*`) |
| TC-SPL-99-009 | 1,2 | UI shows line evidence and every active blocker | `frontend/src/AssignedEvents.test.tsx` |
| TC-SPL-99-010 | 2 | UI shows a Non-essential shortfall while reporting equipment ready | `frontend/src/AssignedEvents.test.tsx` |
| TC-SPL-99-011 | 3 | UI explains the no-requirement and equipment-only boundary | `frontend/src/AssignedEvents.test.tsx` |
| TC-SPL-99-012 | 4 | Readiness region exposes no button, textbox or link | `frontend/src/AssignedEvents.test.tsx` |

Every acceptance criterion has at least two dedicated automated cases. The mapping covers all four
criteria (4/4, 100% acceptance-criteria coverage); this is requirements coverage, not a code
coverage percentage.

## Verification record

- Focused backend readiness and related equipment/coordinator regressions: 137 passed.
- Focused coordinator interface suite: 38 passed.
- Frontend type-check: passed.
- Ruff lint and formatting checks for changed Python files: passed.
- Full `npm run verify`: passed — Ruff lint and format checks passed; 1,602 backend tests
  passed and 99 skipped; all 389 frontend tests passed; type-check and production build passed.
- PostgreSQL `npm run integration`: 99 passed against an empty disposable PostgreSQL 17.4
  container; the container was removed after the run.
- Manual functional test: passed in Chromium against an isolated SQLite business database and the
  local Auth fixture. The assigned Event Coordinator viewed (1) an Essential 3/4 reservation with
  the return date, Technical Support note, unavailability reason/alternative and outstanding review
  blockers, (2) a visible Non-essential 0/3 shortfall that remained equipment-ready, and (3) an
  event with no requirements and no equipment blocker. The readiness region exposed no editing
  controls, all three pages retained the event's Planning status, and visual inspection found no
  layout issue at a 1440 × 1000 viewport.

SPL-99 changes no migration. The story-specific browser journey above exercised the built frontend,
real local authentication, Flask endpoint and isolated database. The repository-wide E2E suite was
not run because its preparation script mutates the shared local Supabase business database and the
repository workflow forbids sharing that database between simultaneous workspaces; this is recorded
as not run, not as a pass.
