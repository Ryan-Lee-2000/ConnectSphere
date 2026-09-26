"""Assigned-coordinator venue availability search for SPL-71."""

from datetime import date
from typing import Iterable

from flask import Flask, abort, g, jsonify, request
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.authorization import require_roles
from app.coordinator_assignment import is_assigned_coordinator
from app.models import EventRequest, Role, Venue, VenueBookingOccupancy, VenueLayout
from app.slots import OPERATING_SLOTS, derive_venue_occupancy
from app.venue_operational_blocks import operational_block_for_slot


class SearchParameterError(ValueError):
    """A client-provided availability-search value is outside the SPL-71 contract."""


def register_venue_availability_routes(app: Flask) -> None:
    @app.get("/api/event-requests/<int:event_request_id>/available-venues")
    @require_roles(Role.EVENT_COORDINATOR)
    def find_available_venues(event_request_id: int):
        """List catalogue venues available for all requested Singapore slots.

        The event identifier is an authorisation boundary, not a client-supplied organiser or
        coordinator selector.  A coordinator can only search for an event currently assigned to
        them.  The query itself carries only the prospective Singapore date and AM/PM/Night
        slots; it never creates a booking or reserves a candidate.
        """

        (
            day,
            event_slots,
            attendance_override,
            layout_override,
            attendance_supplied,
            layout_supplied,
        ) = _search_parameters()
        with Session(app.extensions["engine"]) as session:
            if not is_assigned_coordinator(session, event_request_id, g.user_id):
                abort(404, "Assigned event not found.")
            event = session.get(EventRequest, event_request_id)
            if event is None:
                abort(404, "Assigned event not found.")
            venues = session.scalars(
                select(Venue).options(selectinload(Venue.layouts)).order_by(Venue.name, Venue.id)
            ).all()
            expected_attendance = (
                attendance_override if attendance_supplied else event.expected_attendance
            )
            preferred_room_layout = (
                layout_override if layout_supplied else event.preferred_room_layout
            )
            available = [
                _serialize_venue(venue, expected_attendance, preferred_room_layout)
                for venue in venues
                if _is_available(session, venue, day, event_slots)
                and qualifying_layouts(venue.layouts, expected_attendance, preferred_room_layout)
            ]
            return jsonify(
                search={"date": day.isoformat(), "slots": event_slots},
                venues=available,
            )


def _search_parameters() -> tuple[date, list[str], int | None, str | None, bool, bool]:
    try:
        attendance_supplied = "expected_attendance" in request.args
        layout_supplied = "preferred_room_layout" in request.args
        return parse_search_parameters(
            request.args.get("date"),
            request.args.getlist("slot"),
            request.args.get("expected_attendance"),
            request.args.get("preferred_room_layout"),
            attendance_supplied,
            layout_supplied,
        ) + (attendance_supplied, layout_supplied)
    except SearchParameterError as exc:
        abort(400, str(exc))


def parse_search_parameters(
    raw_date: str | None,
    raw_slots: Iterable[str],
    raw_attendance: str | None = None,
    raw_layout: str | None = None,
    attendance_supplied: bool = False,
    layout_supplied: bool = False,
) -> tuple[date, list[str], int | None, str | None]:
    """Validate and normalise a read-only venue-catalogue search.

    Kept free of Flask and database collaborators so the user-story rules can be
    tested quickly as unit behaviour as well as through the protected endpoint.
    """

    if not raw_date:
        raise SearchParameterError("Search date is required.")
    try:
        day = date.fromisoformat(raw_date)
    except ValueError:
        raise SearchParameterError("Search date must use YYYY-MM-DD.") from None

    slots = list(raw_slots)
    if not slots:
        raise SearchParameterError("Select at least one operating slot.")
    if any(slot not in OPERATING_SLOTS for slot in slots):
        raise SearchParameterError("Search uses only AM, PM or NIGHT slots.")
    if len(slots) != len(set(slots)):
        raise SearchParameterError("Operating slots must not contain duplicates.")
    attendance: int | None = None
    if attendance_supplied:
        if not raw_attendance or not raw_attendance.isdecimal() or int(raw_attendance) < 1:
            raise SearchParameterError("Expected attendance must be a positive whole number.")
        attendance = int(raw_attendance)

    layout: str | None = None
    if layout_supplied:
        layout = (raw_layout or "").strip() or None
        if layout is not None and len(layout) > 100:
            raise SearchParameterError("Preferred room layout must be 100 characters or fewer.")

    return day, [slot for slot in OPERATING_SLOTS if slot in slots], attendance, layout


def _is_available(session: Session, venue: Venue, day: date, event_slots: Iterable[str]) -> bool:
    event_slots = list(event_slots)
    if not set(event_slots).issubset(venue.operating_slots):
        return False
    required = derive_venue_occupancy(
        ((day, slot) for slot in event_slots),
        setup_buffer_slots=venue.setup_buffer_slots,
        turnaround_buffer_slots=venue.turnaround_buffer_slots,
    )
    for occupied in required:
        if occupied.slot not in venue.operating_slots:
            return False
        if operational_block_for_slot(session, venue.id, occupied.date, occupied.slot):
            return False
        booking_occupancy = session.scalar(
            select(VenueBookingOccupancy.id).where(
                VenueBookingOccupancy.venue_id == venue.id,
                VenueBookingOccupancy.day == occupied.date,
                VenueBookingOccupancy.slot == occupied.slot,
            )
        )
        if booking_occupancy is not None:
            return False
    return True


def qualifying_layouts(
    layouts: Iterable[VenueLayout],
    expected_attendance: int | None,
    preferred_room_layout: str | None,
) -> list[VenueLayout]:
    """Return stored layouts that meet the event's capacity requirement.

    Expected attendance remains event-level (Q119). Capacities are persisted per supported
    layout and are never estimated (Q112). A saved preferred layout, when present, must match.
    """

    if expected_attendance is None:
        return []
    required_layout = preferred_room_layout.strip().casefold() if preferred_room_layout else None
    return [
        layout
        for layout in layouts
        if layout.capacity >= expected_attendance
        and (required_layout is None or layout.layout.casefold() == required_layout)
    ]


def _serialize_venue(
    venue: Venue, expected_attendance: int | None, preferred_room_layout: str | None
) -> dict[str, object]:
    matches = qualifying_layouts(venue.layouts, expected_attendance, preferred_room_layout)
    return {
        "id": venue.id,
        "name": venue.name,
        "location": venue.location,
        "maximum_layout_capacity": max((layout.capacity for layout in venue.layouts), default=None),
        "matching_layouts": [
            {"layout": layout.layout, "capacity": layout.capacity} for layout in matches
        ],
    }
