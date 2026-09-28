# SPL-79 — CS-E10-S1: Track the status of an event's venue-booking request

**Epic:** CS-E10 Venue Booking Request (SPL-10)

**Priority:** High · **Estimate:** 5 story points

**QA report:** Confluence QS space, `QA-SPL-79` (test cases written before the code).

## User story

As an assigned Event Coordinator, I want to view the current status and recorded history of an
event's venue-booking request so that I understand its present outcome and the actions that produced
it.

## Acceptance criteria

1. The assigned Event Coordinator can retrieve the event's venue-booking request: venue, Singapore
   date, event slot(s), setup and turnaround slots, selected layout, and current status
   (`Requested`, `Approved`, `Rejected` or `Withdrawn`).
2. The response includes a history of every status change in the order it occurred. Each entry
   holds the resulting status, the acting user, the action time, and any reason or note recorded
   with that action.
3. The response gives the current status separately from the history entries.
4. Retrieving booking information leaves the request's status, history and occupancy unchanged.
5. The system refuses the request for any user other than the event's assigned Event Coordinator.
6. If the event has no venue-booking request, the system returns an explicit "no venue-booking
   request" result rather than an error.
7. The response states whether the request is marked for review and, if it is, the operational
   block that triggered the review and the time it was marked (Q120, Q122).

**Assumptions (recorded on the Jira story):** an append-only venue-booking status history that
SPL-77/SPL-78 write to and that existing bookings are backfilled into, and that SPL-81/SPL-82 append
to; the latest request is shown with its history and earlier requests are listed; the view appears
on the event page and in the Venue search panel.

## Interface

`GET /api/event-requests/{event_id}/venue-booking-status` — Event Coordinator, current coordinator
of the event only (401/403/404 otherwise, 404 bodies identical).

```json
{
  "venue_booking_request": { "...": "the latest booking, as SPL-77/SPL-78 serialise it" },
  "current_status": { "status": "withdrawn", "label": "Withdrawn" },
  "history": [
    { "action": "request", "status": "requested", "status_label": "Requested",
      "actor": { "id": "…", "name": "Casey Lim" }, "changed_at": "…+08:00", "note": null }
  ],
  "review": { "requires_review": false, "marked_at": null, "trigger_block": null },
  "earlier_requests": [
    { "id": 40, "venue": { "id": 2, "name": "…" }, "date": "2026-10-14",
      "status": "withdrawn", "status_label": "Withdrawn" }
  ]
}
```

With no request: every field null/empty and `message` "No venue-booking request has been made for
this event yet." (HTTP 200).

**Recording.** `app.venue_booking_history.record_booking_transition(session, booking_id, action=…,
previous_status=…, resulting_status=…, actor_account_id=…, changed_at=…, note=…)` appends one row in
the caller's transaction. SPL-77 records `request`, SPL-78 records `withdraw`. **SPL-81 should record
`approve` with the approval note, and SPL-82 `reject` with the rejection reason, as `note`.**

**Interface.** SPL-78's "Venue booking request" panel now shows the history, a review warning and
earlier requests. The panel also appears on the assigned event page for events loaded in Planning or
later, where it says so explicitly when nothing has been requested.

## Schema

Migration `s2_venue_booking_history` (parent `s2_venue_booking_withdrawal`) creates
`venue_booking_status_history` (booking, action, previous status, resulting status, actor, time,
note) with RLS enabled and browser grants revoked, and backfills request and withdrawal entries from
the columns SPL-77 and SPL-78 already store.

## Test cases

| ID | AC | Level | Location |
| --- | --- | --- | --- |
| TC-SPL-79-01 to -05, -06(b), -07, -09 to -14, -16 to -18 | 1–7 | Server | `backend/tests/test_venue_booking_status.py` |
| TC-SPL-79-06(a) | 2 | PostgreSQL | `backend/tests/test_venue_booking_status_postgres.py` |
| TC-SPL-79-08, -15, -19, -20 | 2, 3, 6, 7 | Component | `frontend/src/VenueBookingStatus.test.tsx` |
| TC-SPL-79-21, -22 | 1–3, 6; cross-cutting | Browser | `e2e/venue-booking-status.spec.ts` |

```sh
rg -n "TC-SPL-79" docs backend/tests frontend/src e2e
uv run --frozen pytest backend/tests/test_venue_booking_status.py -v
pnpm --dir frontend exec vitest run src/VenueBookingStatus.test.tsx
npm run integration        # TC-SPL-79-06(a), RLS on the new table
npm run check:e2e          # TC-SPL-79-21/-22, with npm start running
```

## Out of scope

Performing approval, rejection or withdrawal (SPL-81, SPL-82, SPL-78); Venue Staff and Organiser
views of booking status; notifications.
