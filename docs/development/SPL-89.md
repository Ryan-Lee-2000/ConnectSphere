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
5. **Mark overlapping Requested/Approved bookings for review — implemented.** Creating a block
   marks each active booking whose persisted occupancy intersects the selected venue, inclusive
   date range and slots. The booking keeps its status and details. Terminal and non-overlapping
   bookings are not marked, and the block plus every marker commit atomically.

## Public interfaces

- `POST /api/venues/<venue_id>/operational-blocks`
- `GET /api/venues/<venue_id>/operational-blocks` (active blocks)
- `DELETE /api/venues/<venue_id>/operational-blocks/<block_id>` (audited soft removal)
- `operational_block_for_slot(session, venue_id, day, slot)` for server-side availability consumers
- Venue Staff manage active blocks from the selected venue in the venue catalogue.
- The create response reports `affected_booking_count`; the interface tells Venue Staff how many
  active bookings now require review.

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
| TC-SPL-89-07 | Overlapping Requested/Approved bookings gain an audited marker without status/detail mutation; alternatives remain unmarked | `backend/tests/test_venue_operational_blocks.py` |
| TC-SPL-89-08 | A refused block creates neither a block nor a booking marker | `backend/tests/test_venue_operational_blocks.py` |
| TC-SPL-89-09 | Concurrent booking and block writes cannot leave an unmarked overlap | `backend/tests/test_venue_conflicts_postgres.py` |

## Migration and security

Migration `s2_venue_operational_blocks.py` follows `s2_event_status_history`. It creates the block
table and availability index, enables PostgreSQL RLS, and revokes table and sequence privileges from
PUBLIC, `anon` and `authenticated`. Business access remains exclusively through Flask.

After SPL-83 introduced the shared booking model, additive migration
`s2_booking_review_marker.py` follows `s2_venue_booking_occupancy.py` and adds the persisted marker,
triggering block, marking actor and timestamp to `venue_bookings`. No merged migration is edited.

## Completed dependency

PR #28 delivered the operational-block foundation. SPL-83 is now on `main`, and the follow-up uses
its shared occupancy rows to complete acceptance criterion 5. Clearing a marker, notifications and
a review queue remain out of scope; SPL-77 and SPL-81 will expose booking-request and approval
workflows without duplicating this rule.

Block creation and booking claims use the same ordered PostgreSQL transaction advisory locks for
each venue/date/slot. This closes the cross-table write-skew race: the second transaction always
observes the first transaction's committed block or occupancy before making its decision. It is a
transaction policy change only and requires no migration.
