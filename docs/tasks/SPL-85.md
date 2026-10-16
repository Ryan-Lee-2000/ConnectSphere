# SPL-85 — CS-E07-S3: Confirm an event

**Epic:** CS-E07 Event Status Management (SPL-7)

**QA report:** Confluence QS space, `QA-SPL-85` (test cases published before the code).
**DevOps report:** Confluence QS space, `DEVOPS-SPL-85`.

## User story

As an Event Coordinator, I want to confirm an event once its essential arrangements are complete
so that everyone involved knows it will proceed as planned.

## Acceptance criteria

1. Only the assigned coordinator can confirm, and only from Planning.
2. Confirmation is refused when the event has no approved venue booking.
3. Confirmation is refused when any equipment requirement marked as essential is not fully
   reserved (essential flag set per requirement, proposed mechanism).
4. Confirmation is refused while any booking or reservation is flagged 'Review required'.
5. On success the status becomes Confirmed, the organiser can view the confirmed arrangements, and
   the confirmer and time are recorded.
6. Registration setup is not a precondition (it is enabled after confirmation, CS-E19-S1).

Sources: Week 4 core #6; Q80, Q98, Q106; Q132 (the Event Coordinator Lead cannot act for the
assigned coordinator).

## What was built

- `POST /api/event-requests/<id>/confirm` — assigned Event Coordinator only, no body. Planning →
  Confirmed through the shared `TRANSITION_RULES`, recording `confirmed_by_account_id` and
  `confirmed_at` (migration `s3_event_confirmation`) and an `event_status_history` row.
- `app/event_confirmation.py` — the single gate. `derive_confirmation_readiness` returns
  `{ready, blockers}`; every blocker has a stable `code`, a message and the booking or requirement
  it concerns. A refusal is `409 {"error": "This event cannot be confirmed yet.", "blockers": [...]}`.
- The assigned-event detail carries `confirmation_readiness`, so the coordinator's checklist and
  the server gate are the same function. The organiser's `GET /api/event-requests` carries
  `confirmed_by`, `confirmed_at` and `confirmed_arrangements` (Approved venues and active equipment
  lines with what is actually held), null until the event is Confirmed.
- Interface: a "Confirm this event" panel on the coordinator's event page (blockers, a two-step
  Confirm); the organiser's "My requests" shows who confirmed and the arrangements.

| Blocker code | AC | Meaning |
| --- | --- | --- |
| `no_approved_venue_booking` | 2 | No Approved booking (the venue is always essential). |
| `venue_booking_pending` | 2 | A booking is still Requested (team interpretation, ready for SPL-131). |
| `venue_booking_review_required` | 4 | SPL-89 marker, or SPL-137's current review reasons. |
| `essential_not_fully_reserved` | 3 | From SPL-99 readiness: retained units below the quantity. |
| `essentiality_undecided`, `legacy_requirement_unmapped` | 3 | From SPL-99: the line could still be essential (Q80, Q106). |
| `essential_review_outstanding` | 4 | From SPL-99: an Essential line under review. |
| `equipment_review_required` | 4 | Any other active line under review (AC4 says "any"). |

**Concurrency.** The route locks event (and assignment), each active booking's venue, the bookings,
then the equipment lines — the order booking writers (event, venue, booking), block writers (venue,
booking) and equipment writers (stock pool, line) already use, so there is no cycle. A release,
review flag or booking change either commits before the gate reads or waits until it commits.
TC-SPL-85-21 shows that without the line lock a release and a confirmation both succeed.

## Acceptance-criteria test map

| AC | Test cases | Evidence |
| --- | --- | --- |
| AC1 | TC-SPL-85-01, -02, -03, -04 | `backend/tests/test_event_confirmation.py`; component TC-24 (d) |
| AC2 | TC-SPL-85-05, -06, -07 | `backend/tests/test_event_confirmation.py` |
| AC3 | TC-SPL-85-08, -09, -10, -11, -21 | backend tests; `backend/tests/test_event_confirmation_postgres.py` |
| AC4 | TC-SPL-85-12, -13, -14, -15 | `backend/tests/test_event_confirmation.py` |
| AC5 | TC-SPL-85-16, -17, -18, -19, -20, -24, -25 | backend, PostgreSQL and `frontend/src/EventConfirmation.test.tsx` |
| AC6 | TC-SPL-85-22, -23 | `backend/tests/test_event_confirmation.py` |
| End to end | TC-SPL-85-26 | `e2e/spl85-uat-evidence.spec.ts` (fixture in `scripts/equipment_e2e_fixtures.py`) |

## Focused checks

```sh
uv run --frozen pytest backend/tests/test_event_confirmation.py -q
npx pnpm --dir frontend exec vitest run src/EventConfirmation.test.tsx
npm run integration        # empty disposable PostgreSQL; includes test_event_confirmation_postgres.py
npm run e2e:record -- e2e/spl85-uat-evidence.spec.ts   # app running, after npm run setup
rg -n "TC-SPL-85-08" docs backend/tests frontend/src e2e
```

## Out of scope

Week 7 Safety Officer check and the Preparing state (SPL-135); whole-event cancellation (SPL-86);
multi-venue management (SPL-131 — the gate already handles several bookings); notifications
(SPL-102/103); registration setup (SPL-114, enabled once Confirmed).
