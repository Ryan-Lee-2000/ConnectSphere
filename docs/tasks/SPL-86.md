# SPL-86 — CS-E07-S5: Cancel an event

**Epic:** CS-E07 Event Status Management (SPL-7)

**QA report:** Confluence QS space, `QA-SPL-86`.
**DevOps report:** Confluence QS space, `DEVOPS-SPL-86`.

## User story

As the assigned Event Coordinator, I want to cancel an event that will no longer go ahead so that
its venues and equipment are freed for other events while its records are kept.

## Acceptance criteria (Jira, 16 October 2026)

1. The event's currently assigned coordinator can cancel it at any stage from assignment onwards
   (Q68): Submitted, Under review, Returned for clarification, Approved, Planning, Confirmed or
   Postponed, by giving a non-blank reason. There is no cancellation deadline (Q60).
2. Cancellation is refused and nothing changes for: an event already in a final state (Rejected,
   Withdrawn, Completed or Cancelled); a Draft, which has no assigned coordinator; a blank reason;
   or anyone other than the event's currently assigned coordinator, including the Event
   Coordinator Lead (Q132).
3. Given an event with several venue bookings and equipment reservations, when it is cancelled,
   the event becomes Cancelled; each Requested or Approved venue booking becomes Cancelled and its
   occupied time becomes available; Rejected, Withdrawn or already Cancelled bookings stay as they
   were; and every still-held reserved equipment unit is released through the shared SPL-98
   release, including partly reserved and Review-required lines, with the release recorded in the
   equipment history.
4. The event, its venue bookings and its equipment releases change in one transaction: if any part
   of the cancellation fails, they all stay exactly as they were.
5. Cancelling an already cancelled event is refused as already cancelled, and nothing is released a
   second time, including when two cancellations are made at the same moment.
6. The event, its venue bookings, its equipment history and any registration records stay viewable
   (Q20) to exactly the users who could view them before; cancellation grants no new access. They
   show Cancelled with the reason, who cancelled it and when.
7. The cancelled event's venue requests no longer appear in the Venue Staff booking review queue,
   and its equipment requirements no longer appear as actionable items in the Technical Support
   equipment review queue or availability list.

Not in this story: cancelling a single venue booking (SPL-131); notifying attendees (SPL-124);
registration withdrawal arising from cancellation (Q115); reopening a cancelled event.

## Decisions (recorded on the Jira card, 16 October 2026)

The Discussions settle the authority (Q68, Q132), the absence of a deadline (Q60) and record
retention (Q20). Where they are silent the team recommendation was adopted:

- Who, when and why are stored on the event (`cancelled_by_account_id`, `cancelled_at`,
  `cancellation_reason`, a paired check constraint), plus a `cancel` row in the status history.
- The reason is required, trimmed, and at most 2,000 characters.
- Equipment lines recalculate status as SPL-98 already does (Review Required is kept). Cancelled
  events are already excluded from both Technical Support lists by event status.
- Booking-history notes and equipment-release reasons read `Event cancelled: <reason>`.
- Postponed is cancellable, as AC1 states, although no transition into it exists yet.

## What was built

- `POST /api/event-requests/<id>/cancel` with `{"reason": "..."}` (`app/event_cancellation.py`).
  Assigned Event Coordinator only. 400 bad body · 401 no session · 403 other roles, including the
  Lead · 404 unassigned, unknown or Draft · 409 already cancelled or a final state.
- One transaction, locking in the shared order: event and assignment → active bookings' venues →
  bookings → equipment types → equipment lines. Requested/Approved bookings are cancelled through
  SPL-83's `transition_booking_status` with a history row each; held units are released through
  SPL-98's `_release_from_requirement`. The `cancel` rule joins the shared `TRANSITION_RULES`.
- `serialize_cancellation` adds `cancelled_by`, `cancelled_at` and `cancellation_reason` to the
  organiser's request list, the coordinator's assigned-event detail and the Lead's supervision and
  basic-information views.
- Interface: a two-step "Cancel this event" panel with a required reason on the coordinator's
  event page for cancellable statuses; "Cancelled by … on …" and the reason on the organiser's
  list; the reason in the Lead's supervision table.

## Migration

`s3_event_cancellation` (after `s3_venue_arrangements`): three nullable columns on
`event_requests` and `ck_event_requests_cancellation_complete`. Purely additive; existing rows keep
nulls and the previous release keeps working while it deploys.
