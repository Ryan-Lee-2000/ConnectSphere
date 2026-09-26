# SPL-89 — Record venue operational unavailability

## Approved user story

As a Venue Staff member, I want to record and remove periods when a venue is operationally
unavailable so that venue availability reflects when the venue cannot be used.

## Acceptance criteria and implementation state

1. **Create a block — implemented.** Venue Staff can record an inclusive ISO date range, one or
   more operating slots configured for the selected venue, and a non-blank reason.
2. **Shared availability — implemented.** Submitted event requests reject a venue/date/slot covered
   by an active block. `operational_block_for_slot()` is also the shared dependency for SPL-71,
   SPL-75 and SPL-83 rather than asking each story to reinterpret block rows.
3. **Remove a block — implemented.** Removal is soft and active reads immediately exclude the row.
4. **Audit and atomic refusal — implemented.** Creation and removal record the trusted actor and
   timezone-aware timestamp. Validation and role checks occur before a transaction is committed.
5. **Mark overlapping Requested/Approved bookings for review — blocked by SPL-83.** The repository
   does not yet contain the shared venue-booking and occupancy model. This branch does not invent
   one. SPL-77 will consume that model later when it creates booking requests.

## Public interfaces

- `POST /api/venues/<venue_id>/operational-blocks`
- `GET /api/venues/<venue_id>/operational-blocks` (active blocks)
- `DELETE /api/venues/<venue_id>/operational-blocks/<block_id>` (audited soft removal)
- `operational_block_for_slot(session, venue_id, day, slot)` for server-side availability consumers
- Venue Staff manage active blocks from the selected venue in the venue catalogue.

Identity and role are always derived from the verified session. The request body cannot choose the
actor. React accesses the records only through Flask.

## Test-case traceability

| Test case | Behaviour | Automated location |
| --- | --- | --- |
| TC-SPL-89-01 | Record and retrieve an audited active block | `backend/tests/test_venue_operational_blocks.py` |
| TC-SPL-89-02 | Remove only the selected block and retain removal audit evidence | `backend/tests/test_venue_operational_blocks.py` |
| TC-SPL-89-03 | Invalid and unauthorised attempts make no change | `backend/tests/test_venue_operational_blocks.py` |
| TC-SPL-89-04 | Inclusive active blocks feed the shared availability boundary | `backend/tests/test_venue_operational_blocks.py` |
| TC-SPL-89-05 | A submitted event request cannot select an actively blocked venue slot | `backend/tests/test_event_requests.py` |
| TC-SPL-89-06 | Venue Staff create and remove a block through the interface | `frontend/src/VenueCatalogue.test.tsx` |

## Migration and security

Migration `s2_venue_operational_blocks.py` follows `s2_event_status_history`. It creates the block
table and availability index, enables PostgreSQL RLS, and revokes table and sequence privileges from
PUBLIC, `anon` and `authenticated`. Business access remains exclusively through Flask.

## Remaining dependency

PR #28 is a mergeable enabling increment for SPL-83, but merging it does not make SPL-89 Done. Keep
SPL-89 In Progress until SPL-83's shared booking/occupancy model is on `main` and acceptance
criterion 5 has tests proving that overlapping Requested/Approved bookings are preserved, keep their
status/details, and gain a persisted review marker. Clearing that marker, notifications and a review
queue remain out of scope.
