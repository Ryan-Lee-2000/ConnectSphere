# SPL-96 — CS-E15-S3: Mark units of equipment as unavailable

**Epic:** CS-E15 Equipment Inventory (SPL-15)

**QA report:** Confluence QS space, `QA-SPL-96` (test cases written before the code).

## User story

As Technical Support Staff, I want to record damaged or unavailable units so that they cannot be
offered to other events.

## Acceptance criteria

1. Technical Support can record a positive whole number of units of an equipment type as
   unavailable, with a non-blank reason, and later restore some or all of them. The unavailable
   total can never exceed total stock or fall below zero.
2. Every availability check and reservation made afterwards uses the reduced usable stock.
3. If usable stock falls below what is already reserved on any day, every reservation contributing
   to that shortfall is marked Review Required with the reason. Its quantities and history are kept.
4. Technical Support sees the Review Required flag and reason in the equipment review queue, and
   the assigned coordinator sees them on the affected requirement line.
5. Restoring units does not clear any Review Required flag or bring back a released reservation;
   Technical Support revalidates each flagged reservation.
6. Only Technical Support Staff can record or restore unavailable units; any other role, or no
   session, is refused and nothing changes.

## All six acceptance criteria

This change set was first built against AC1, AC2 and AC6 only, because AC3, AC4 and AC5 all turn
on the Review Required flag raised against *reservations*, and reservations are SPL-97's records.
SPL-97 merged on 10 October 2026, and AC3–AC5 were completed on 11 October.

**Why that order mattered, and what it exposed.** Until AC3 was built, **nothing anywhere in the
codebase ever set `review_required`** — which meant SPL-97's own `revalidate-reservation` route,
already merged, could never be reached: it refuses any line whose status is not `review_required`.
The missing half of this story left a merged teammate's route unreachable. That is the strongest
argument against shipping a story at half its criteria, and it is recorded here deliberately.

**AC4 is why this change set is stacked on SPL-92.** AC4 requires the flag and its reason to be
visible *in the equipment review queue*, and that queue is SPL-92. Building AC4 before SPL-92
existed would have meant inventing a queue inside the wrong story.

## Explaining this story in two minutes

**The problem.** A cracked microphone capsule is still a row in the catalogue. Until Technical
Support can say "three of these six are out of service", availability keeps promising units that
physically cannot be handed over.

**What it stores.** Two things, for one reason each:

| Stored | Where | Why not the other way |
| --- | --- | --- |
| The current unavailable total | `equipment_types.unavailable_units` | AC1 states a bound. A database can only check a bound against a stored number, so the total is a column with a CHECK constraint. Summing a ledger on every read could not be constrained. |
| Every change, with its reason, author and time | `equipment_unavailability_records` | AC1 asks for the reason, who and when on *every* change, restorations included. The total answers "how many"; the records answer "why". |

**How a recording is applied** (`backend/app/equipment_unavailability.py`):

| Step | What happens | Why |
| --- | --- | --- |
| 1 | Validate quantity and reason, and reject any other field | AC1; a bad request never opens a transaction |
| 2 | Lock the equipment type's row | Two people recording at once must not both read the same total and both add to it |
| 3 | Check the AC1 bounds against the locked figures | A clean 400 naming the room left, instead of a constraint error surfacing as a 500 |
| 4 | Write the new total and the history entry together | The audit trail can never disagree with the number it explains |

**How AC3 works — and why "contributing" is read per day.** Taking units out of service can
leave less usable stock than is already promised. A *day* is short when the units promised on it
exceed what is usable, and every reservation spanning such a day is contributing, because any one
of them could be the one released to resolve it. The story is explicit that the system does not
choose a winner, so all of them are flagged and none is cancelled: no reservation's quantity is
altered and nothing is deleted. The flag is the requirement line's existing `review_required`
status; `review_reason` and `review_flagged_at` carry the explanation.

**Why only a marking flags, never a restore (AC5).** Putting units back can only increase usable
stock, so it can never create a shortfall. A restore therefore writes no flag and clears none —
AC5 says Technical Support revalidates each flagged line through SPL-97's route instead. The
subtle case is a restore that leaves the line *still* short: it must not re-flag and overwrite the
original reason with the restore's wording. A test pins exactly that, because the first version of
the code would have passed without it.

**Where the reason is cleared.** SPL-97's `revalidate-reservation` clears the status; this change
set makes it clear `review_reason` and `review_flagged_at` in the same place, so a stale reason can
never outlive the state it explains.

**How AC2 works.** SPL-95 already took `unavailable_by_day` and was called with nothing in it; its
own response said so. This story fills it. Because the story rules out a maintenance schedule,
units are unavailable from when they are recorded until they are restored, so the same figure
applies to every day of a commitment, and SPL-95's "busiest day" logic is unchanged.

**Why these choices** (the questions a reviewer is likely to ask):

- *Why not just lower `total_stock`?* Total stock is how many units the organisation owns; that
  does not change because one is broken. Keeping the two numbers apart is what lets AC1 state a
  bound between them, and lets a restore be an ordinary event rather than a correction.
- *Why a record for restores too?* AC1 asks for it, and a restore is the claim that matters most
  later: it says a unit is fit to promise again, and names who decided that.
- *Why is the bound both in Python and in the database?* The Python check produces the message the
  user reads. The constraint is what makes the bound true. Removing the Python check in testing
  turned the refusal into a 500, not a bad save — which is the behaviour we want from a backstop.
- *Why does SPL-97's revalidate route need editing?* It clears the status but knew nothing of
  the reason, which this story introduced. Clearing them together is what keeps the pair
  honest.
- *Why did SPL-94's edit route have to change?* Lowering total stock is the other way to break AC1.
  It now refuses with a message instead of failing as a constraint error. SPL-94's response shape
  is deliberately untouched, so nothing else about the catalogue changes.

**How we know it works.** The QA-SPL-96 cases were published before the code. With no routes, all
four server cases failed; with an empty component, all four component cases failed. Eight
deliberate bugs were each caught by at least one test, and removing the row lock makes the
PostgreSQL race fail, so the lock is doing the work the test claims (see the QA page).

## Interpretation of the acceptance criteria

- **"A positive whole number" (AC1)** excludes zero, negatives, fractions and `true`. Python treats
  booleans as integers, so they are refused explicitly: `true` is not a quantity of one.
- **"Can never exceed total stock" (AC1)** is enforced at both ends: recording more than is usable
  is refused, and so is lowering total stock below the unavailable total.
- **"Every availability check afterwards" (AC2)** means reads are live. Nothing is cached, so a
  recording is reflected the next time the availability workspace is opened.
- **Usable stock** is `total_stock - unavailable_units`, worked out in one place and sent to the
  page, so the figure shown is never arithmetic done twice.

## Interface

- `POST /api/equipment-types/{id}/unavailable-units`: Technical Support only. `{"quantity",
  "reason"}` → 201 `{"equipment_type", "record"}`. 400 outside the bounds or on a bad field, 404
  for an unknown type.
- `POST /api/equipment-types/{id}/restored-units`: the same shape, in the other direction.
- `GET /api/equipment-types/{id}/unavailability`: Technical Support only.
  `{"equipment_type", "history"}`, newest entry first.
- `equipment_type`: `id`, `name`, `total_stock`, `unavailable_units`, `usable_stock`.
- `record`: `id`, `action` (`marked_unavailable` or `restored`), `quantity`, `reason`,
  `recorded_by`, `recorded_at`.

## Schema

`s3_equipment_unavailable_units`, following `s3_registration_withdrawals`:

- `equipment_types.unavailable_units`: NOT NULL, server default `0`, so existing rows read as "all
  stock usable" without being rewritten and the previous version keeps working while it deploys.
- `ck_equipment_types_unavailable_in_stock`: `0 <= unavailable_units <= total_stock` (AC1). The
  constraint text is imported from `app.models`, so the model and the database cannot drift.
- `equipment_unavailability_records`: the history, with its own constraints on quantity and action.

## Integration

- `backend/app/equipment_availability.py` (SPL-95) now receives a real `unavailable_by_day` and its
  `input_notice` no longer claims unavailable units are missing. The calculation itself is
  unchanged; it already took this input.
- `backend/app/equipment_catalogue.py` (SPL-94) refuses a `total_stock` below the unavailable total.
- `frontend/src/EquipmentUnavailability.tsx` is a new page at
  `/workspace/equipment-types/{id}/unavailability`, offered only to Technical Support and reached
  from a link on each catalogue card.

## Test cases

| ID | AC | Level | Location |
| --- | --- | --- | --- |
| TC-SPL-96-01 | 1, 2, 3, 5 | Server | `backend/tests/test_equipment_unavailability.py` |
| TC-SPL-96-02 | 1, 6 | Server | `backend/tests/test_equipment_unavailability.py` |
| TC-SPL-96-03 | 4 | Server | `backend/tests/test_equipment_unavailability.py` (queue and coordinator paths) |
| TC-SPL-96-04 | 2 | Server | `backend/tests/test_equipment_unavailability.py` |
| TC-SPL-96-05 | 3 | Server | `backend/tests/test_equipment_unavailability.py` |
| TC-SPL-96-06 | 1 | Server | `backend/tests/test_equipment_unavailability.py` |
| TC-SPL-96-10 | 1 | Server | `backend/tests/test_equipment_unavailability.py` (added during implementation) |
| TC-SPL-96-12 | 3, 5 | Server | `backend/tests/test_equipment_unavailability.py` (added during implementation) |
| TC-SPL-96-07 | 1 | PostgreSQL | `backend/tests/test_equipment_unavailability_postgres.py` (concurrency half) |
| TC-SPL-96-11 | 1 | PostgreSQL | `backend/tests/test_equipment_unavailability_postgres.py` (added during implementation) |
| TC-SPL-96-08 | 1 | Component | `frontend/src/EquipmentUnavailability.test.tsx` |
| TC-SPL-96-03 | 4 | Component | `frontend/src/EquipmentReviewQueue.test.tsx` |
| TC-SPL-96-09 | 1, 2 | Browser | Not yet written: needs a catalogue type in the local stack |

```sh
rg -n "TC-SPL-96" docs backend/tests frontend/src
uv run --frozen pytest backend/tests/test_equipment_unavailability.py -v
npm run integration   # includes the PostgreSQL cases
```

## Out of scope

Notifying the coordinator when a flag is raised, and scheduling maintenance.
