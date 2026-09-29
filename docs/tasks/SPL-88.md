# SPL-88 — CS-E11-S1: View venue occupancy on a calendar

**Epic:** CS-E11 (SPL-11)

**QA report:** Confluence QS space, `QA-SPL-88` (test cases written before the code).

## User story

As an authorised internal user, I want to view a venue's occupancy by date and operating slot so
that I can understand when the venue is available.

## Acceptance criteria

1. An authorised internal user can select a venue and a Singapore date or date range to retrieve its
   supported AM, PM, and Night slots.
2. Each supported slot is shown as Available, Requested, Booked, Preparation, or Blocked according
   to active occupancy.
3. Requested and Approved bookings, their derived preparation slots, and venue operational blocks
   are reflected in the calendar.
4. If a slot has more than one relevant reason for review, the calendar preserves the applicable
   occupancy information instead of presenting it as simply Available.
5. Unsupported operating slots are distinguishable from available supported slots.
6. Changing the venue or date range refreshes the view without modifying booking or block data.
7. If a supported slot has no active booking, preparation requirement, or operational block, it is
   shown as Available.
8. Users without an authorised internal role cannot retrieve the operational calendar.

## Interpretation of the acceptance criteria

Posted to the Jira story's Assumptions section for team confirmation; used as the working
interpretation until answered, the same way SPL-80's "organisation-wide" reading was.

- **Multi-reason precedence (AC2/AC4 read together).** A slot can have more than one applicable
  reason (for example Booked and Blocked, after SPL-89 lets a block overlap an existing booking
  rather than reverting it). The single label shown is the most serious:
  **Blocked > Booked > Requested > Preparation > Available**. Every applicable reason is still
  returned in a `reasons` list, so AC4's "preserves the applicable occupancy information" holds even
  though AC2 asks for one label. Blocked ranks first because it means the venue cannot be used at
  all, which is the single fact a viewer most needs to see first.
- **Preparation slots follow the occupying booking's status, not a separate state.** A setup or
  turnaround slot held by a Requested booking is labelled Preparation regardless of whether the
  booking itself is Requested or Approved — the label describes what the slot is for, not what stage
  its booking has reached. (The booking's own event slots do split by status: Requested → Requested,
  Approved → Booked.)
- **"Authorised internal user" (AC1, AC8) is Venue Staff, Event Coordinator, or Event Operations
  Manager.** These are the three roles who schedule venues; Organisers and Attendees are refused.
- **Maximum range: 31 days.** AC1 places no bound on the requested range, but an unbounded range
  means computing every slot's status for every day requested, which must be capped the same way
  other endpoints cap unbounded inputs. A range longer than 31 days is refused with 400.
- **No occupant identity is shown.** AC2/AC4 ask for a status and reasons, not who holds a slot.
  Since Event Coordinators are one of the three authorised roles, and coordinators only work for one
  organisation, naming another coordinator's event or organisation on a shared operational view would
  repeat the leak SPL-80's allowlist was built to avoid. The calendar names only the status and reason
  category (`booking`, `preparation`, `block`), never the event, organisation, or requester.

## Interface

- `GET /api/venues/{venue_id}/occupancy?start_date=YYYY-MM-DD&end_date=YYYY-MM-DD` — Venue
  Staff, Event Coordinator, or Event Operations Manager only. A single day is `start_date == end_date`.
  200 with one entry per day in range, each carrying all three of `OPERATING_SLOTS` (AM, PM, NIGHT),
  each slot with a `status` and a `reasons` list. 400 if `end_date` is before `start_date`, if the
  range exceeds 31 days, or if either date is missing or malformed. 404 for an unknown venue. 403 for
  any role but the three above; 401 with no session.
- Per-slot response: `{"slot": "AM", "status": "blocked" | "booked" | "requested" | "preparation" |
  "available" | "not_operated", "reasons": [{"key": "block" | "booking" | "preparation", "label": ...,
  "detail": ...}]}` — the `reasons` list is empty for `available` and `not_operated`, and follows the
  same `{key, label, detail}` shape `profile_suitability_checks` (SPL-71/75) already established, for
  consistency rather than a new ad hoc format.
- Read-only throughout: the route only selects existing rows from `venue_booking_occupancy`,
  `venue_bookings` and `venue_operational_blocks`. No migration.

## Schema

None — read-only story, as declared in the Jira ticket's Out of scope.

## Integration

Additive only. Reuses `operational_block_for_slot` (SPL-89) unchanged, `Venue.operating_slots`
(catalogue) unchanged, and follows `profile_suitability_checks`' `{key, label, detail}` shape
(SPL-71/75) for its own reason objects. No existing route, serializer or test is touched.

## Test cases

| ID | AC | Level | Location |
| --- | --- | --- | --- |
| TC-SPL-88-01 to -20 | 1–8 | Server | `backend/tests/test_venue_occupancy_calendar.py` |
| TC-SPL-88-21 | 3, 4 | PostgreSQL | `backend/tests/test_venue_occupancy_calendar_postgres.py` |
| TC-SPL-88-22, -23 | 1, 2, 5, 8 | Component | `frontend/src/VenueOccupancyCalendar.test.tsx` |
| TC-SPL-88-24 | 1–3, 5, 7; cross-cutting | Browser | `e2e/venue-occupancy-calendar.spec.ts` |

```sh
rg -n "TC-SPL-88" docs backend/tests frontend/src e2e
uv run --frozen pytest backend/tests/test_venue_occupancy_calendar.py -v
pnpm --dir frontend exec vitest run src/VenueOccupancyCalendar.test.tsx
npm run integration        # TC-SPL-88-21, on disposable PostgreSQL
npm run check:e2e          # TC-SPL-88-24, with npm start running
```

## Out of scope

Creating, approving, rejecting, or withdrawing a booking from the calendar; editing venue operating
slots; a formal precedence-override control; exposing occupant identity; notifications.
