# SPL-91 — CS-E14-S2: Change an equipment requirement

**Epic:** CS-E14 Equipment Requirements (SPL-14)

**QA report:** Confluence QS space, `QA-SPL-91` (test cases written before the code).

## User story

As the assigned Event Coordinator, I want to revise an equipment requirement so that the equipment
arranged for my event matches what it currently needs.

## Acceptance criteria

1. While the event is In planning, the assigned coordinator can change a requirement line's
   equipment type, quantity (a positive whole number), required dates or technical notes.
2. Changing any of those on a Reserved or Partially Reserved line releases its reserved units and
   marks it Review Required for Technical Support. Saving without changing anything releases
   nothing.
3. While the event is In planning, the assigned coordinator can remove a requirement line. Any
   units still reserved for it are released once, the removed line and the release stay in
   history, and other lines and events are unaffected.
4. Every change or removal records the old and new values, who made it and when. Failed or
   simultaneous conflicting changes never leave a stale reservation or release the same units
   twice.
5. A change or removal is refused, with nothing changed, when the event is in any status other
   than In planning, or when made by anyone other than the event's assigned coordinator.

## Explaining this story in two minutes

**The problem.** SPL-90 lets the assigned coordinator change or remove a requirement line, but only
while it holds no stock (Unmapped or Requested). Once Technical Support reserved units for it
(SPL-97), the line was frozen: a coordinator whose event now needed 5 microphones instead of 4 had
no way to say so. This story opens up those lines (Reserved, Partially Reserved and Review
Required) without ever leaving a reservation describing a line that has since changed.

**The rule (AC2).** If a line holds stock and the coordinator changes what Technical Support
reviewed (the equipment type, quantity, dates or technical notes), then:

1. every unit still held for the line is released through SPL-98's release operation;
2. the line becomes Review Required, with a plain-English reason saying what changed and how many
   units were released, so it reappears in SPL-92's review queue;
3. one history row records the old and new values, who made the change, when, and how many units
   it released.

Removing a line (AC3) releases everything it holds the same way, marks it Removed and records one
history row. A save that changes nothing does nothing at all: no release and no history row.

**What it stores.** One new table, `equipment_requirement_changes`, with one row per accepted
change or removal. The release itself stays in SPL-98's `equipment_reservation_releases`, so units
are only ever released in one place. The history row just records how many units the action
released.

**Why these choices** (the questions a reviewer is likely to ask):

- *Why release everything, not just the difference?* AC2 says "releases its reserved units". A
  reservation was made for the line as it was. Once the line changes, Technical Support has to look
  again before anything is held for it, and holding a part of it would be a decision Technical
  Support never made. This is the reading the story's open question called "option A" (see
  Interpretation).
- *Why not release when only essentiality changes?* Recording whether equipment is essential is
  SPL-90's job, and it does not change what Technical Support reserved. Releasing four microphones
  because the coordinator marked them essential would punish the coordinator for recording a
  decision. TC-SPL-91-12 pins this, and it exists because mutation testing showed the first version
  of the suite could not tell the difference.
- *Why go through SPL-98's release operation rather than writing release rows here?* One owner for
  the release history. SPL-98 already locks the reservations it consumes, recalculates what is held
  and writes the audit row. A second way of releasing would be a second place for those rules to
  drift apart.
- *Why lock the equipment type, then the line?* Every route that changes stock takes those two
  row locks in that order. Two requests on the same line therefore run one after the other, and
  the second re-reads the line once it gets the lock. Taking them in the opposite order anywhere
  would let two requests deadlock.
- *Why is validation done before any release?* So a refused change (AC5, or a bad value) releases
  nothing. The request is validated first, then the stock is released, then the line is changed,
  all in one transaction.

**What the coordinator sees.** When editing a line that holds stock, the form warns that the change
releases the reserved units and sends the line back to Technical Support (not just afterwards).
Removing such a line asks for confirmation and says its units will be released. After a save, the
page reports how many units were released, and the line shows **Back with Technical Support for
review** with the reason. That warning shows only while the line is Review Required. Once Technical
Support reserves units for it again, the warning and its reason are gone (see SPL-97 under
Integration).

**How we know it works.** The QA-SPL-91 cases were published on 10 October, before the code. On the
branch without the code, all 8 server cases written then failed, each on SPL-90's refusal to touch
a reserved line (the right reason). Of the 5 component cases, 3 failed. The other 2 are guards that
pass on `main` by nature ("no warning on an unreserved line", "a refusal never lands in another
line's form"). Each was proved by planting the bug it guards against and watching it fail. Of 15
deliberate bugs planted in the server code, 14 were caught first time; the fifteenth (releasing on
an essentiality-only change) led to TC-SPL-91-12. Removing this story's row locks makes both
PostgreSQL race cases fail.

## Interpretation of the acceptance criteria

- **"Releases its reserved units" (AC2)** was read as written: *all* held units are released,
  whichever field changed. The story's open question asked whether a quantity, date or note change
  should instead keep the units held under Review Required (as SPL-96 does) and release only on an
  equipment-type change. It was posted for the product owner with a fallback at the 10 October
  stand-up; no answer came, so the working interpretation (option A, AC2 as written) stands. If the
  answer is ever option B, only the "releases" part of TC-SPL-91-01 and -02 changes.
- **"Reserved or Partially Reserved" (AC2)** also covers a line already in **Review Required** that
  still holds units (SPL-96 can flag a line without releasing it). A further change to such a line
  releases what it still holds, so no stale reservation outlives the change (AC4).
- **"Technical notes" (AC2)** covers any change to the notes, including a typo fix, because the
  system cannot tell a typo from a change that affects suitability (the story's assumption).
- **"Saving without changing anything" (AC2)** means every submitted field equals the stored value.
  No history row is written, because nothing happened.
- **"Old and new values, who made it and when" (AC4)** is recorded on every accepted change and
  removal. The assigned coordinator can read it through
  `GET .../equipment-requirements/{id}/history`, newest first. The page does not yet display that
  history: AC4 asks for it to be recorded, and TC-SPL-91-08 reads it through the API.
- **"A refused value is shown beside its field" (TC-SPL-91-10, the QA wording)** is met by
  showing the refusal inside the open form, just above Save, and keeping what the coordinator
  typed. The server's validation messages name the field in their wording ("Quantity must
  be…") but carry no field key, so the form cannot attach a message to a single input.
- **"Refused, with nothing changed" (AC5)** follows the codebase's existing conventions: 409 when
  the event is not In planning, 404 for a coordinator not assigned to the event (so the event's
  existence is not revealed), 403 for any other role, 401 with no session.

## Interface

- `PATCH /api/event-requests/{event_id}/equipment-requirements/{id}`: assigned Event Coordinator,
  event In planning. The existing SPL-90 route, now also accepted on Reserved, Partially Reserved
  and Review Required lines. Response gains `released_quantity`:
  `{"requirement": ..., "released_quantity": 4}`.
- `DELETE /api/event-requests/{event_id}/equipment-requirements/{id}`: the same rules. The response
  gains `released_quantity`.
- `GET /api/event-requests/{event_id}/equipment-requirements/{id}/history`: assigned Event
  Coordinator, any event status (history is not a change). Returns `{"history": [...]}`, newest
  first; each entry has `id`, `action` (`changed` or `removed`), `old_values`, `new_values`,
  `released_quantity`, `changed_by`, `changed_at`.
- Refusals: 400 for a bad value or unexpected field, 401 no session, 403 wrong role, 404 unknown
  line or unassigned coordinator, 409 when the event is not In planning or the line is Removed or
  Unavailable.

## Schema

`s3_equipment_requirement_changes`, following SPL-98's `s3_equipment_releases`:

- New table `equipment_requirement_changes`: `equipment_requirement_id` (cascade with the line, as
  SPL-92's review notes and SPL-98's releases do), `action`, `old_values` and `new_values` (JSON),
  `released_quantity`, `changed_by_account_id`, `changed_at`.
- Two CHECK constraints: `action` is `changed` or `removed`, and `released_quantity` is never
  negative. Row level security is enabled, as on every product table.
- `equipment_requirements` is not altered: the Review Required reason reuses SPL-96's
  `review_reason` and `review_flagged_at` columns.

## Integration

- **SPL-98:** every release goes through `_release_from_requirement`, and the held quantity comes
  from `_held_quantity`, which locks the reservation rows it reads.
- **SPL-96:** a coordinator change writes the same `review_reason`/`review_flagged_at` columns that
  SPL-96 writes when units become unavailable. The badge on the requirements page therefore now
  reads "Back with Technical Support for review: {reason}" instead of wording that named SPL-96's
  cause, because the reason can now come from either story.
- **SPL-92:** a line marked Review Required here appears in Technical Support's review queue with
  no change to SPL-92.
- **SPL-97:** two of SPL-97's tests encoded "a reserved line cannot be edited". SPL-91 AC2 changes
  that rule on purpose, so both were updated to keep SPL-97's real promise: three units are never
  left held against a line that now needs one, and a reserved line is never silently overwritten.
  - `test_tc_spl_97_14_a_reserved_line_is_never_silently_overwritten`
    (`backend/tests/test_equipment_requirements.py`)
  - `test_tc_spl_97_13_quantity_change_racing_a_reservation_never_leaves_stale_units_held`
    (`backend/tests/test_equipment_reservations_postgres.py`). This race has no fixed winner, so
    both orderings were exercised: in 12 runs, the reservation won 8 times and the edit 4 times,
    and every run passed.
- **SPL-97's reserve route now clears the review explanation** (a fix from review on PR #78). When
  a reservation takes a line out of Review Required, to Reserved or Partially Reserved, it now
  also clears `review_reason` and `review_flagged_at`, as SPL-97's revalidate route already did.
  Before this, a coordinator whose changed line had been re-reserved still saw "Back with
  Technical Support for review" and the old release explanation. The same gap affected SPL-96's
  flags, so the fix covers both. The change and release history live in their own tables and are
  untouched. The page also shows the warning only while the line is Review Required, so a stale
  reason can never read as an active warning (TC-SPL-91-14 to -16).

## Test cases

| ID | AC | Level | Location |
| --- | --- | --- | --- |
| TC-SPL-91-01 | 1, 2, 4 | Server | `backend/tests/test_equipment_requirement_changes.py` |
| TC-SPL-91-02 | 1, 2, 3 | Server | `backend/tests/test_equipment_requirement_changes.py` |
| TC-SPL-91-03 | 5 | Server | `backend/tests/test_equipment_requirement_changes.py` |
| TC-SPL-91-05 | 1 | Server | `backend/tests/test_equipment_requirement_changes.py` |
| TC-SPL-91-06 | 2 | Server | `backend/tests/test_equipment_requirement_changes.py` |
| TC-SPL-91-07 | 3 | Server | `backend/tests/test_equipment_requirement_changes.py` |
| TC-SPL-91-08 | 4 | Server | `backend/tests/test_equipment_requirement_changes.py` |
| TC-SPL-91-09 | 5 | Server | `backend/tests/test_equipment_requirement_changes.py` |
| TC-SPL-91-12 | 2 | Server | `backend/tests/test_equipment_requirement_changes.py` (added after mutation testing) |
| TC-SPL-91-04 | 3, 4 | PostgreSQL | `backend/tests/test_equipment_requirement_changes_postgres.py` (two races) |
| TC-SPL-91-13 | 4 | PostgreSQL | `backend/tests/test_equipment_requirement_changes_postgres.py` (added during implementation) |
| TC-SPL-91-10 | 1, 2, 3 | Component | `frontend/src/EquipmentRequirements.test.tsx` (5 cases) |
| TC-SPL-91-14 | 2, 4 | Server | `backend/tests/test_equipment_requirement_changes.py` (added from review: full re-reservation) |
| TC-SPL-91-15 | 2, 4 | Server | `backend/tests/test_equipment_requirement_changes.py` (added from review: partial re-reservation) |
| TC-SPL-91-16 | 2 | Component | `frontend/src/EquipmentRequirements.test.tsx` (added from review) |
| TC-SPL-91-11 | 1, 2 | Browser | Not yet written: needs a reserved line on a planning event in the local stack |

```sh
rg -n "TC-SPL-91" docs backend/tests frontend/src
uv run --frozen pytest backend/tests/test_equipment_requirement_changes.py -v
npm run integration   # includes the PostgreSQL cases
cd frontend && ./node_modules/.bin/vitest run src/EquipmentRequirements.test.tsx
```

## Out of scope

Recording whether equipment is essential (SPL-90). Releasing reservations by hand (SPL-98).
Changes to Confirmed events, which go through the event change workflow. A screen showing the
change history.
