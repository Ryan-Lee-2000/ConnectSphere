"""Venue Staff's queue of pending venue-booking requests for SPL-80 (CS-E10-S2).

Read-only throughout: SPL-80 adds no table, no column and no migration. Every value it returns is
already stored by SPL-77 (the request), SPL-83/SPL-87 (the preparation slots recorded on the
booking when its occupancy was claimed) and SPL-89 (the review marker).

Two rules from the story shape this module, both recorded in docs/tasks/SPL-80.md:

* **AC1's "organisation-wide" is the venue operator's whole estate**, not one client organisation.
  Venue Staff hold no ``organisation_id`` — they work for the operator — so the queue is filtered
  by booking status alone and never by the caller's organisation.
* **AC4 is served by an allowlist, not a blocklist.** ``decision_event_details`` names the event
  fields a venue decision needs; anything else, including the attendee-facing registration fields,
  is absent by construction. A column added to ``event_requests`` later therefore cannot leak here
  without someone choosing to add it.
"""

from datetime import time
from typing import Any

from flask import Flask, jsonify
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.authorization import require_roles
from app.models import Account, EventRequest, Organisation, Role, Venue, VenueBooking
from app.venue_booking_requests import _date, _slot, _timestamp

REQUESTED = "requested"
EMPTY_QUEUE = "No venue-booking requests are awaiting review."


def register_venue_booking_queue_routes(app: Flask) -> None:
    @app.get("/api/venue-bookings/pending")
    @require_roles(Role.VENUE_STAFF)
    def list_pending_venue_bookings():
        with Session(app.extensions["engine"]) as session:
            # The event is joined rather than fetched per row: AC2 requires every item to name its
            # event, so it is always needed.
            rows = session.execute(
                select(VenueBooking, EventRequest)
                .join(EventRequest, EventRequest.id == VenueBooking.event_request_id)
                # AC5: Requested only. Testing for "not withdrawn" or "still active" would leave
                # approved bookings in the review queue for ever (TC-SPL-80-06).
                .where(VenueBooking.status == REQUESTED)
                # Oldest request first, so the longest-waiting request is at the top of the queue.
                # Bookings stored without a request time (SPL-83 and SPL-89 fixtures) sort last by
                # id rather than first, because NULL ordering differs between PostgreSQL and
                # SQLite and the order must not depend on the database (TC-SPL-80-09).
                .order_by(
                    VenueBooking.requested_at.is_(None),
                    VenueBooking.requested_at,
                    VenueBooking.id,
                )
            ).all()
            requests = [_queue_item(session, booking, event) for booking, event in rows]
            body: dict[str, Any] = {"requests": requests, "count": len(requests)}
            if not requests:
                # AC6: an empty queue is a normal outcome with a sentence the interface can show,
                # not a 404 the caller has to interpret.
                body["message"] = EMPTY_QUEUE
            return jsonify(body)


def decision_event_details(session: Session, event: EventRequest) -> dict[str, Any]:
    """The event as Venue Staff need it to decide on a booking (AC3), and no more (AC4).

    This is the single place the allowlist lives, so the queue and SPL-81's review view cannot
    drift apart. Deliberately absent: ``registration_required`` and ``registration_notes``, which
    describe how attendees sign up rather than whether the venue fits, and the organiser's account
    identity — the requesting coordinator is the person Venue Staff would contact, and AC2 already
    names them.
    """

    organisation = session.get(Organisation, event.organisation_id)
    return {
        # SPL-81 already returned these three and its approval screen depends on them; widening
        # the payload must stay additive (TC-SPL-80-11).
        "id": event.id,
        "name": event.name,
        "status": event.status,
        "organisation": (
            {"id": organisation.id, "name": organisation.name} if organisation else None
        ),
        "purpose": event.purpose,
        "description": event.description,
        "proposed_date": _date(event.proposed_date),
        "start_time": _clock(event.start_time),
        "end_time": _clock(event.end_time),
        "expected_attendance": event.expected_attendance,
        # What the event needs of a venue: the checks SPL-75 makes automatically are shown here so
        # a human can weigh the ones it cannot, such as the free-text notes.
        "preferred_room_layout": event.preferred_room_layout,
        "required_facilities": event.required_facilities or [],
        "accessibility_needs": event.accessibility_needs or [],
        "facilities_notes": event.facilities_notes,
        "location_preference": event.location_preference,
        "venue_notes": event.venue_notes,
    }


def _queue_item(session: Session, booking: VenueBooking, event: EventRequest) -> dict[str, Any]:
    """One pending request, carrying exactly the fields AC2 lists.

    Built here rather than from SPL-77's ``serialize_venue_booking`` because that payload also
    carries the withdrawal and approval records, which are null for every Requested booking by
    definition and would only be noise in a review queue.
    """

    venue = session.get(Venue, booking.venue_id)
    requester = (
        session.get(Account, booking.requested_by_account_id)
        if booking.requested_by_account_id
        else None
    )
    return {
        "id": booking.id,
        "event": {"id": event.id, "name": event.name},
        "venue": {"id": venue.id, "name": venue.name},
        "date": _date(booking.booking_date),
        "event_slots": booking.event_slots or [],
        # SPL-87 derived these when SPL-77 claimed the occupancy, and they are read back rather
        # than re-derived: a venue's buffers may have changed since the request was made, and the
        # queue must show the slots actually held (the same rule SPL-81 approves against).
        "setup": _slot(booking.setup_date, booking.setup_slot),
        "turnaround": _slot(booking.turnaround_date, booking.turnaround_slot),
        "layout": booking.layout,
        "expected_attendance": booking.expected_attendance,
        "requested_by": (
            {"id": requester.id, "name": requester.display_name} if requester else None
        ),
        "requested_at": _timestamp(booking.requested_at),
        # SPL-89's stored marker, so a request an operational block has invalidated is visible as
        # such in the queue rather than only after opening it (Q120).
        "requires_review": booking.requires_review,
    }


def _clock(value: time | None) -> str | None:
    """A wall-clock time as ``HH:MM``; seconds carry no meaning for an event's start or end."""

    return value.isoformat(timespec="minutes") if value else None
