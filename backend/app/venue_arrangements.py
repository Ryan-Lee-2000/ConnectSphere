"""Several independent venue bookings for one event (SPL-131, Week 7 change 3).

An event that needs more than one space - a plenary and its breakout rooms - holds one venue
booking per space (Q109). Each booking is its own arrangement:

* AC2 - expected attendance stays one event-level value (Q119). A booking records how many of
  those attendees use its space (never more), its layout and the facilities it needs. The
  event's accessibility needs and location preference apply to every venue.
* AC3 - each booking is checked on its own details. Capacities are never added together.
* AC5 - the same event cannot hold the same venue twice at an overlapping occupied time; the
  shared venue lock makes two such requests queue, so the second sees the first.
* AC7 - the assigned coordinator cancels one Approved booking with a reason, through SPL-137's
  ``cancel_booking``, which releases only that booking's time and records the history entry.

Request validation lives in ``venue_booking_requests``; this module holds the per-booking rules
both timing modes share, and the cancellation route.
"""

from datetime import datetime
from typing import Any

from flask import Flask, abort, g, jsonify, request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.authorization import require_roles
from app.models import ACTIVE_BOOKING_STATUSES, EventRequest, Role, Venue, VenueBooking, VenueLayout

ARRANGEMENT_FIELDS = frozenset({"attendee_count", "required_facilities"})
MAX_FACILITIES = 30
MAX_FACILITY_LENGTH = 100
MAX_REASON_LENGTH = 1000
PLANNING = "planning"
LAYOUT_CHECK = "Layout and capacity"
ONLY_PLANNING_TO_CANCEL = "A venue booking can be cancelled only while the event is in Planning."
BOOKING_URL = "/api/event-requests/<int:event_request_id>/venue-bookings/<int:booking_id>"


def register_venue_arrangement_routes(app: Flask) -> None:
    from app.coordinator_assignment import MAX_EVENT_REQUEST_ID, is_assigned_coordinator
    from app.event_requests import SINGAPORE
    from app.exact_venue_bookings import cancel_booking, lock_booking
    from app.venue_booking_requests import NOT_FOUND, serialize_venue_booking

    @app.post(f"{BOOKING_URL}/cancel")
    @require_roles(Role.EVENT_COORDINATOR)
    def cancel_venue_booking(event_request_id: int, booking_id: int):
        """AC7: cancel one Approved booking; the event's other bookings are untouched (AC6)."""

        # Validate the body first, so an invalid cancellation never reaches the database.
        reason = _cancellation_reason()
        if event_request_id > MAX_EVENT_REQUEST_ID or booking_id > MAX_EVENT_REQUEST_ID:
            abort(404, NOT_FOUND)
        with Session(app.extensions["engine"]) as session:
            if not is_assigned_coordinator(session, event_request_id, g.user_id):
                abort(404, NOT_FOUND)
            # Lock order event, assignment, venue, booking (SPL-137). With the coordinator id,
            # a booking of an event someone else coordinates is refused with 404 here.
            booking = lock_booking(session, booking_id, g.user_id)
            if booking is None or booking.event_request_id != event_request_id:
                abort(404, NOT_FOUND)
            if session.get(EventRequest, event_request_id).status != PLANNING:
                abort(409, ONLY_PLANNING_TO_CANCEL)
            # Refuses anything but Approved with 409, before any change is made.
            cancel_booking(
                session,
                booking.id,
                coordinator_id=g.user_id,
                changed_at=datetime.now(SINGAPORE),
                note=reason,
            )
            session.commit()
            venue = session.get(Venue, booking.venue_id)
            return jsonify(
                booking=serialize_venue_booking(session, booking),
                message=f"Booking cancelled. {venue.name}'s time is available to other events.",
            )


def arrangement_fields(data: dict[str, Any]) -> tuple[int | None, list[str] | None]:
    """The optional per-booking attendee count and facilities, shape-checked (AC2).

    Omitted means the event's own value applies. Whether the count fits the event is checked
    later, against the locked event row.
    """

    attendee_count = data.get("attendee_count")
    if "attendee_count" in data and (type(attendee_count) is not int or attendee_count < 1):
        abort(400, "Enter how many attendees will use this venue as a whole number above zero.")
    facilities = data.get("required_facilities")
    if "required_facilities" in data:
        if not isinstance(facilities, list) or not all(
            isinstance(item, str) and item.strip() for item in facilities
        ):
            abort(400, "List each required facility by name.")
        facilities = _unique(item.strip() for item in facilities)
        if len(facilities) > MAX_FACILITIES or any(
            len(item) > MAX_FACILITY_LENGTH for item in facilities
        ):
            abort(
                400,
                f"Keep to {MAX_FACILITIES} facilities, each "
                f"{MAX_FACILITY_LENGTH} characters or fewer.",
            )
    return attendee_count, facilities


def resolve_arrangement(
    event: EventRequest, attendee_count: int | None, facilities: list[str] | None
) -> tuple[int | None, list[str]]:
    """Fill omitted values from the event, and refuse a share larger than the event (Q119)."""

    count = attendee_count if attendee_count is not None else event.expected_attendance
    if (
        attendee_count is not None
        and event.expected_attendance is not None
        and attendee_count > event.expected_attendance
    ):
        abort(
            400,
            "A venue cannot hold more attendees than the event expects "
            f"({event.expected_attendance}).",
        )
    return count, facilities if facilities is not None else list(event.required_facilities or [])


def booking_attendee_count(booking: VenueBooking, event: EventRequest) -> int | None:
    return (
        booking.expected_attendance
        if booking.expected_attendance is not None
        else event.expected_attendance
    )


def booking_facilities(booking: VenueBooking, event: EventRequest) -> list[str]:
    """The booking's own facilities, or the event's for a booking that recorded none (AC9)."""

    if booking.required_facilities is not None:
        return list(booking.required_facilities)
    return list(event.required_facilities or [])


def arrangement_layout(
    layouts: list[VenueLayout], layout_name: str | None, attendee_count: int | None
) -> VenueLayout | None:
    """The venue's layout of that name, if it holds this booking's attendee count (AC3)."""

    wanted = (layout_name or "").casefold()
    for layout in layouts:
        if (
            layout.layout.casefold() == wanted
            and attendee_count is not None
            and layout.capacity >= attendee_count
        ):
            return layout
    return None


def arrangement_checks(
    venue: Venue,
    event: EventRequest,
    *,
    layout_name: str | None,
    attendee_count: int | None,
    facilities: list[str],
) -> list[dict[str, Any]]:
    """Suitability of one venue for one booking, in SPL-75's check order (AC3).

    Layout, capacity and facilities are the booking's own. Accessibility and location are the
    event's and apply to every venue, so SPL-75's own checks are reused for them unchanged.
    """

    from app.venue_availability import _missing_requirements, profile_suitability_checks

    layout = arrangement_layout(venue.layouts, layout_name, attendee_count)
    missing = _missing_requirements(facilities, venue.facilities)
    event_checks = {
        check["key"]: check
        for check in profile_suitability_checks(venue, event)
        if check["key"] in ("accessibility", "location")
    }
    return [
        {
            "key": "layout_capacity",
            "label": LAYOUT_CHECK,
            "passed": layout is not None,
            "detail": (
                f"The {layout_name} layout holds {attendee_count} guests."
                if layout is not None
                else f"No {layout_name} layout here holds "
                f"{attendee_count or 'the expected'} guests."
            ),
        },
        {
            "key": "facilities",
            "label": "Required facilities",
            "passed": not missing,
            "detail": (
                "No facility requirements are recorded for this booking."
                if not facilities
                else "All required facilities are recorded on this venue."
                if not missing
                else f"Missing required facilities: {', '.join(missing)}."
            ),
        },
        event_checks["accessibility"],
        event_checks["location"],
    ]


def same_event_overlap(
    session: Session, event_id: int, venue_id: int, occupied: Any | None
) -> VenueBooking | None:
    """An active booking of this event at this venue whose time overlaps (AC5).

    ``occupied`` is the requested exact occupied interval. ``None`` means slot timing, where every
    booking of an event uses the event's saved slots, so any active booking at the venue overlaps.
    The caller holds the venue lock, so a concurrent request for the same venue has either
    committed and is seen here, or waits until this one commits.
    """

    from app.exact_venue_bookings import interval_from_json

    bookings = session.scalars(
        select(VenueBooking)
        .where(
            VenueBooking.event_request_id == event_id,
            VenueBooking.venue_id == venue_id,
            VenueBooking.status.in_(ACTIVE_BOOKING_STATUSES),
        )
        .order_by(VenueBooking.id)
    ).all()
    for booking in bookings:
        if occupied is None or not booking.exact_timing:
            return booking
        try:
            if occupied.overlaps(interval_from_json(booking.exact_timing["occupied"])):
                return booking
        except (KeyError, TypeError, ValueError):
            return booking
    return None


def within_event(interval: Any, saved: Any) -> bool:
    """AC2: a booking's advertised time sits inside the saved event's own start and end."""

    return saved.start <= interval.start and interval.end <= saved.end


def _cancellation_reason() -> str:
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or set(data) != {"reason"}:
        abort(400, "Send only the reason for cancelling this venue booking.")
    reason = data["reason"]
    if not isinstance(reason, str) or not reason.strip():
        abort(400, "Give a reason for cancelling this venue booking.")
    if len(reason.strip()) > MAX_REASON_LENGTH:
        abort(400, f"Keep the reason to {MAX_REASON_LENGTH} characters or fewer.")
    return reason.strip()


def _unique(items: Any) -> list[str]:
    seen: set[str] = set()
    unique = []
    for item in items:
        if item.casefold() not in seen:
            seen.add(item.casefold())
            unique.append(item)
    return unique
