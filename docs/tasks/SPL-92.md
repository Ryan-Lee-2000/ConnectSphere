# SPL-92 — CS-E14-S3: See equipment requirements awaiting review

**Epic:** CS-E14 Equipment Requirements (SPL-14)

**QA report:** Confluence QS space, `QA-SPL-92` (test cases written before the code).

## User story

As Technical Support Staff, I want to see the equipment requirements awaiting review so that I can
identify and address upcoming equipment work.

## Acceptance criteria

1. The queue lists every Requested and Review Required requirement line for events that are In
   planning, Confirmed or Postponed, earliest required start date first. Lines in any other
   status, and lines on Completed or Cancelled events, do not appear.
2. Each line shows the event name and date, the assigned coordinator, equipment type, quantity,
   required dates and status. Opening a line also shows its technical notes, any review notes and
   the event's status. A line not yet mapped to a catalogue type shows the organiser's original
   text and is marked as needing mapping.
3. Technical Support can add a review note or clarification question to a line. It is saved with
   the author and time, and the event's assigned coordinator can read it.
4. Viewing the queue or adding a note does not reserve stock, change any line's status or message
   the organiser.
5. Only Technical Support Staff can open the queue or add notes; any other role, or no session, is
   refused and nothing changes. The assigned coordinator can read notes on their own event's lines
   but cannot open the queue.

## Explaining this story in two minutes

**The problem.** SPL-90 lets a coordinator record what an event needs, and SPL-97 lets Technical
Support reserve it. Between those two there was no list of what was actually waiting: Technical
Support would have had to open each event in turn to find the lines needing attention.

**What it stores.** One new table, `equipment_review_notes`, and nothing else. No requirement line
is ever modified, because AC4 says so outright. That is the whole reason notes are a separate
table rather than a column on the line: a column would mean writing to the line to leave a note.

**Two conditions, not one** (`backend/app/equipment_review_queue.py`):

| A line is in the queue when… | Why |
| --- | --- |
| its status is Requested or Review Required | AC1. It has been asked for, or something made it need another look |
| *and* its event is In planning, Confirmed or Postponed | AC1. Lines on Completed or Cancelled events are not work, and nor are lines on an event that has not reached planning |

Both live in one `_queue_statement()`, used by the list and by the detail route, so "what is in the
queue" cannot come to mean two different things.

**Who sees what** (AC5):

| Route | Technical Support | Assigned coordinator | Anyone else |
| --- | --- | --- | --- |
| The queue, and one entry | yes | **no** | 403, or 401 with no session |
| Add a note | yes | no | 403 / 401 |
| Read a line's notes | any line | their own event's lines only | 403 / 401 |

**Why these choices** (the questions a reviewer is likely to ask):

- *Why can a coordinator read notes but not open the queue?* AC3 requires a note to reach the
  coordinator; AC5 says the queue is not theirs. That is one route with an ownership filter, not a
  share of the queue.
- *Why does another coordinator get 404 rather than 403?* A 403 would confirm the line exists on
  someone else's event. Same rule as SPL-114, SPL-116, SPL-117 and SPL-118.
- *Why is a line that exists but is not awaiting review also 404?* On the queue routes the queue is
  the subject, so "not in the queue" and "not a line" are the same answer. The coordinator's note
  route deliberately does not apply that filter, because they should still be able to read the
  history of a line after it has moved on.
- *Why order by date and then two more columns?* AC1 only asks for earliest required start first,
  but ties would then come back in whatever order the database chose, which can differ between two
  identical requests. Event id and line id make the order total.
- *Why `needs_mapping` instead of letting the page check for a null?* AC2 makes an unmapped line a
  thing to act on. Saying so in the response keeps that judgement on the server, where the
  test can pin it.
- *Why are notes append-only?* AC3 asks for the author and time, and the coordinator reads them as
  a record of what was asked. Editing or deleting would make that record untrustworthy.

**How we know it works.** The QA-SPL-92 cases were published before the code. With the routes
unregistered, all 8 server cases failed; with an empty component, all 4 component cases failed.
Twelve deliberate bugs were each caught by at least one test (see the QA page). Every exclusion
test puts an excluded line beside an included one in the same response, so an empty queue cannot
make a case pass.

## Interpretation of the acceptance criteria

- **"Awaiting review" (AC1)** is the pair of conditions above. A Partially Reserved line is *not*
  in the queue, which is the working interpretation of the open question on the story.
- **"Earliest required start date first" (AC1)** ties break on event id, then line id.
- **"The assigned coordinator" (AC2)** is the current `EventCoordinatorAssignment`, read in one
  query for the whole queue rather than one per line. A line on an event with no assignment shows
  no coordinator rather than failing.
- **"Does not message the organiser" (AC4)** needs no code: nothing here writes a notification.
  TC-SPL-92-08 pins it by checking every line, quantity and stock figure is unchanged after the
  queue is opened and a note is saved.
- **A note's limit** is 2,000 characters, the same ceiling SPL-90 puts on a coordinator's technical
  notes, so the two read alike.

## Interface

- `GET /api/equipment-review-queue`: Technical Support only. `{"requirements": [...]}`, earliest
  required start date first; an empty list when nothing is waiting.
- `GET /api/equipment-review-queue/{id}`: Technical Support only. One entry plus `notes` (the
  coordinator's technical notes) and `review_notes`. 404 for an unknown line or one not in the
  queue.
- `POST /api/equipment-review-queue/{id}/notes`: Technical Support only. `{"note"}` → 201
  `{"note": ...}`. 400 for a blank, over-long or unexpected payload.
- `GET /api/equipment-requirements/{id}/review-notes`: Technical Support, or the event's assigned
  coordinator. `{"review_notes": [...]}` oldest first; 404 for another coordinator's line.
- Each entry: `id`, `event` (`id`, `name`, `date`, `status`, `status_label`), `coordinator`,
  `organiser_equipment_text`, `equipment_type`, `needs_mapping`, `quantity`,
  `required_start_date`, `required_end_date`, `status`.
- Each note: `id`, `note`, `author`, `created_at`.

## Schema

`s3_equipment_review_notes`, following `s3_equipment_reservations`:

- `equipment_review_notes`: the line, the note, its author and time, with a CHECK constraint
  refusing a blank note and an index on `(equipment_requirement_id, created_at)` for the
  oldest-first read. Row-level security on, Supabase browser roles revoked, like every other
  product table.
- `equipment_requirements` is **not** altered, because AC4 is explicit that this story changes no
  line.

**Note for whoever merges second:** SPL-96's `s3_equipment_unavailable_units` also branches from
`s3_equipment_reservations`. Whichever of the two merges second must re-point its `down_revision`
at the other, or there will be two heads and `test_postgres.py` will fail.

## Integration

- Reuses `coordinator_assignment.is_assigned_coordinator` and `event_statuses.status_label`
  unchanged.
- `frontend/src/EquipmentReviewQueue.tsx` is a new page at `/workspace/equipment-review-queue`,
  offered only to Technical Support. It does no filtering or sorting of its own, so the page and
  the server cannot drift.
- `backend/tests/test_postgres.py` gains the new table in `PRODUCT_TABLES`, which is also what
  asserts its row-level security.

## Test cases

| ID | AC | Level | Location |
| --- | --- | --- | --- |
| TC-SPL-92-01 | 1, 3, 4 | Server | `backend/tests/test_equipment_review_queue.py` |
| TC-SPL-92-02 | 5 | Server | `backend/tests/test_equipment_review_queue.py` |
| TC-SPL-92-03 | 2 | Server | `backend/tests/test_equipment_review_queue.py` |
| TC-SPL-92-04 | 1 | Server | `backend/tests/test_equipment_review_queue.py` |
| TC-SPL-92-05 | 1 | Server | `backend/tests/test_equipment_review_queue.py` |
| TC-SPL-92-06 | 1 | Server | `backend/tests/test_equipment_review_queue.py` |
| TC-SPL-92-07 | 3, 5 | Server | `backend/tests/test_equipment_review_queue.py` |
| TC-SPL-92-08 | 4 | Server | `backend/tests/test_equipment_review_queue.py` |
| TC-SPL-92-09 | 2, 3 | Component | `frontend/src/EquipmentReviewQueue.test.tsx` (4 cases) |
| TC-SPL-92-10 | 1, 3 | Browser | Not yet written: needs a requirement line in the local stack |

```sh
rg -n "TC-SPL-92" docs backend/tests frontend/src
uv run --frozen pytest backend/tests/test_equipment_review_queue.py -v
cd frontend && ./node_modules/.bin/vitest run src/EquipmentReviewQueue.test.tsx
```

## Out of scope

Reserving or releasing stock from the queue (SPL-97, SPL-98), and messaging the organiser.
