"""Assigned-coordinator withdrawal of a Requested venue booking for SPL-78 (CS-E09-S4).

Withdrawal reuses SPL-83's ``transition_booking_status`` so occupancy is released by the shared
lifecycle rule. Authority follows the event's current coordinator assignment, and only the
booking's own status gates the action, so a cancelled event can still release its venue (Q60).
"""

from datetime import datetime

from flask import Flask, abort, g, jsonify, request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.authorization import require_roles
from app.coordinator_assignment import MAX_EVENT_REQUEST_ID, is_assigned_coordinator
from app.event_requests import SINGAPORE
from app.models import Role, VenueBooking
from app.venue_booking_requests import NOT_FOUND, serialize_venue_booking
from app.venue_conflicts import transition_booking_status

REQUESTED = "requested"
WITHDRAWN = "withdrawn"
ONLY_REQUESTED = "Only a Requested venue-booking request can be withdrawn."
NO_AMENDMENT = (
    "A submitted venue-booking request cannot be amended. "
    "Withdraw it and submit a new request instead."
)
BOOKING_URL = "/api/event-requests/<int:event_request_id>/venue-bookings/<int:booking_id>"


def register_venue_booking_withdrawal_routes(app: Flask) -> None:
    @app.get("/api/event-requests/<int:event_request_id>/venue-bookings/latest")
    @require_roles(Role.EVENT_COORDINATOR)
    def latest_venue_booking(event_request_id: int):
        with Session(app.extensions["engine"]) as session:
            _require_assignment(session, event_request_id)
            booking = session.scalar(
                select(VenueBooking)
                .where(VenueBooking.event_request_id == event_request_id)
                .order_by(VenueBooking.id.desc())
                .limit(1)
            )
            return jsonify(booking=serialize_venue_booking(session, booking) if booking else None)

    @app.get(BOOKING_URL)
    @require_roles(Role.EVENT_COORDINATOR)
    def read_venue_booking(event_request_id: int, booking_id: int):
        with Session(app.extensions["engine"]) as session:
            booking = _event_booking(session, event_request_id, booking_id)
            return jsonify(booking=serialize_venue_booking(session, booking))

    @app.route(BOOKING_URL, methods=["PUT", "PATCH"])
    @require_roles(Role.EVENT_COORDINATOR)
    def amend_venue_booking(event_request_id: int, booking_id: int):
        # AC7 / Q110: changes go through withdraw and a new, fully re-checked request.
        return jsonify(error=NO_AMENDMENT), 405

    @app.post(f"{BOOKING_URL}/withdraw")
    @require_roles(Role.EVENT_COORDINATOR)
    def withdraw_venue_booking(event_request_id: int, booking_id: int):
        _require_no_parameters()
        with Session(app.extensions["engine"]) as session:
            # Row lock: a concurrent withdrawal waits here and then sees Withdrawn (AC6).
            booking = _event_booking(session, event_request_id, booking_id, lock=True)
            if booking.status != REQUESTED:
                abort(409, ONLY_REQUESTED)
            transition_booking_status(session, booking, WITHDRAWN)
            booking.withdrawn_by_account_id = g.user_id
            booking.withdrawn_at = datetime.now(SINGAPORE)
            session.commit()
            return jsonify(booking=serialize_venue_booking(session, booking))


def _require_assignment(session: Session, event_request_id: int) -> None:
    if event_request_id > MAX_EVENT_REQUEST_ID or not is_assigned_coordinator(
        session, event_request_id, g.user_id
    ):
        abort(404, NOT_FOUND)


def _event_booking(
    session: Session, event_request_id: int, booking_id: int, *, lock: bool = False
) -> VenueBooking:
    """The booking, only if it belongs to an event the caller currently coordinates."""

    _require_assignment(session, event_request_id)
    if booking_id > MAX_EVENT_REQUEST_ID:
        abort(404, NOT_FOUND)
    query = select(VenueBooking).where(
        VenueBooking.id == booking_id, VenueBooking.event_request_id == event_request_id
    )
    booking = session.scalar(query.with_for_update() if lock else query)
    if booking is None:
        abort(404, NOT_FOUND)
    return booking


def _require_no_parameters() -> None:
    """Keep the resulting status, withdrawer and time server-owned."""

    if request.content_length in (None, 0):
        return
    if not request.is_json or request.get_json(silent=True) != {}:
        abort(400, "Withdrawal does not accept a status or any other parameters.")
