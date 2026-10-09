"""Read-only status and history of an event's venue-booking request (SPL-79, CS-E10-S1).

The event's current Event Coordinator sees the latest request with its current status, its full
history, its stored SPL-89 review marker and the event's earlier requests. Reading changes nothing.
"""

from typing import Any

from flask import Flask, abort, g, jsonify
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.authorization import require_roles
from app.coordinator_assignment import MAX_EVENT_REQUEST_ID, is_assigned_coordinator
from app.models import (
    Account,
    Role,
    Venue,
    VenueBooking,
    VenueBookingStatusHistory,
    VenueOperationalBlock,
)
from app.venue_booking_history import booking_status_label
from app.venue_booking_requests import NOT_FOUND, _timestamp, serialize_venue_booking

NO_REQUEST = "No venue-booking request has been made for this event yet."


def register_venue_booking_status_routes(app: Flask) -> None:
    @app.get("/api/event-requests/<int:event_request_id>/venue-booking-status")
    @require_roles(Role.EVENT_COORDINATOR)
    def venue_booking_status(event_request_id: int):
        with Session(app.extensions["engine"]) as session:
            if event_request_id > MAX_EVENT_REQUEST_ID or not is_assigned_coordinator(
                session, event_request_id, g.user_id
            ):
                abort(404, NOT_FOUND)
            bookings = session.scalars(
                select(VenueBooking)
                .where(VenueBooking.event_request_id == event_request_id)
                .order_by(VenueBooking.id.desc())
            ).all()
            if not bookings:
                return jsonify(
                    venue_booking_request=None,
                    current_status=None,
                    history=[],
                    review=None,
                    earlier_requests=[],
                    message=NO_REQUEST,
                )
            latest, earlier = bookings[0], bookings[1:]
            return jsonify(
                venue_booking_request=serialize_venue_booking(session, latest),
                current_status={
                    "status": latest.status,
                    "label": booking_status_label(latest.status),
                },
                history=_history(session, latest.id),
                review=_review(session, latest),
                earlier_requests=[_summary(session, booking) for booking in earlier],
            )


def _history(session: Session, booking_id: int) -> list[dict[str, Any]]:
    entries = session.scalars(
        select(VenueBookingStatusHistory)
        .where(VenueBookingStatusHistory.booking_id == booking_id)
        .order_by(VenueBookingStatusHistory.changed_at, VenueBookingStatusHistory.id)
    ).all()
    history = []
    for entry in entries:
        actor = session.get(Account, entry.actor_account_id)
        history.append(
            {
                "action": entry.action,
                "status": entry.resulting_status,
                "status_label": booking_status_label(entry.resulting_status),
                "actor": {"id": actor.id, "name": actor.display_name},
                "changed_at": _timestamp(entry.changed_at),
                "note": entry.note,
            }
        )
    return history


def _review(session: Session, booking: VenueBooking) -> dict[str, Any]:
    """The stored SPL-89 marker, never recomputed from the blocks active now."""

    block = (
        session.get(VenueOperationalBlock, booking.review_trigger_block_id)
        if booking.review_trigger_block_id
        else None
    )
    from app.exact_venue_bookings import exact_review_reasons
    from app.venue_operational_blocks import exact_block_interval

    reasons = exact_review_reasons(session, booking)
    return {
        "requires_review": booking.requires_review or bool(reasons),
        "marked_at": _timestamp(booking.review_marked_at),
        "trigger_block": (
            {
                "id": block.id,
                "start_date": block.start_date.isoformat(),
                "end_date": block.end_date.isoformat(),
                "slots": block.slots,
                **(
                    {"timing": exact_block_interval(block).serialize()} if block.exact_start else {}
                ),
                "reason": block.reason,
            }
            if block
            else None
        ),
    }


def _summary(session: Session, booking: VenueBooking) -> dict[str, Any]:
    venue = session.get(Venue, booking.venue_id)
    return {
        "id": booking.id,
        "venue": {"id": venue.id, "name": venue.name},
        "date": booking.booking_date.isoformat() if booking.booking_date else None,
        "status": booking.status,
        "status_label": booking_status_label(booking.status),
    }
