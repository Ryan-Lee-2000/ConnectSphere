"""Assigned-coordinator venue-booking requests for SPL-77 (CS-E09-S3).

The route consumes the shared foundations rather than restating them: SPL-75 profile
suitability checks, SPL-87 preparation derivation and SPL-83/SPL-89 atomic occupancy claims
(see docs/development/SPL-77-integration-contract.md).

SPL-131 lets an event hold several bookings, one per space it needs. Each request is checked on
its own attendee count, layout and facilities (``app.venue_arrangements``); only a second hold on
the same venue at an overlapping time is refused.
"""

from datetime import date, datetime
from typing import Any

from flask import Flask, abort, current_app, g, jsonify, request
from sqlalchemy.orm import Session

from app.authorization import require_roles
from app.coordinator_assignment import MAX_EVENT_REQUEST_ID, is_assigned_coordinator
from app.event_requests import SINGAPORE
from app.models import (
    Account,
    EventRequest,
    Role,
    Venue,
    VenueBooking,
)
from app.slots import OccupancyKind, derive_venue_occupancy, slots_for_range
from app.venue_arrangements import (
    ARRANGEMENT_FIELDS,
    arrangement_checks,
    arrangement_fields,
    arrangement_layout,
    resolve_arrangement,
    same_event_overlap,
    within_event,
)
from app.venue_booking_history import record_booking_transition
from app.venue_conflicts import VenueOccupancyConflict, claim_venue_occupancy

PLANNING = "planning"
REQUESTED = "requested"
TIMING_CHECK = "Timing and preparation"
MAX_LAYOUT_LENGTH = 100
NOT_FOUND = "Assigned event not found."


def register_venue_booking_request_routes(app: Flask) -> None:
    @app.post("/api/event-requests/<int:event_request_id>/venue-bookings")
    @require_roles(Role.EVENT_COORDINATOR)
    def request_venue_booking(event_request_id: int):
        venue_id, layout_name, attendee_count, facilities = _booking_request_body()
        if event_request_id > MAX_EVENT_REQUEST_ID:
            abort(404, NOT_FOUND)
        with Session(app.extensions["engine"]) as session:
            if not is_assigned_coordinator(session, event_request_id, g.user_id):
                abort(404, NOT_FOUND)
            # Row locks: concurrent requests for one event queue on the event, and for one venue on
            # the venue, so the same-venue check below sees the other request's booking (SPL-131).
            from app.exact_venue_bookings import lock_event, lock_venue

            event = lock_event(session, event_request_id, g.user_id)
            if event is None:
                abort(404, NOT_FOUND)
            if event.status != PLANNING:
                abort(409, "A venue booking can be requested only while the event is in Planning.")
            venue = lock_venue(session, venue_id)
            if venue is None:
                abort(404, "Venue not found.")
            # SPL-131 AC2: the booking's own share of the event's attendance and facilities.
            attendee_count, facilities = resolve_arrangement(event, attendee_count, facilities)

            if app.config["EXACT_VENUE_TIMING_ENABLED"]:
                return _request_exact(
                    session, event, venue, layout_name, attendee_count, facilities
                )
            # SPL-131 AC5: with slot timing every booking uses the event's saved slots, so any
            # active booking of this event at this venue overlaps.
            if same_event_overlap(session, event.id, venue.id, None):
                abort(409, _already_held(venue))
            event_slots = _event_slots(event)
            selected_layout = arrangement_layout(venue.layouts, layout_name, attendee_count)
            failed = _failed_checks(
                venue, event, event_slots, layout_name, attendee_count, facilities
            )
            if failed:
                return jsonify(
                    error="This venue does not meet the event's requirements: "
                    + ", ".join(failed)
                    + ".",
                    failed_checks=failed,
                ), 409

            booking = VenueBooking(
                event_request_id=event.id,
                venue_id=venue.id,
                status=REQUESTED,
                layout=selected_layout.layout,
                expected_attendance=attendee_count,
                required_facilities=facilities,
                booking_date=event.proposed_date,
                event_slots=event_slots,
                requested_by_account_id=g.user_id,
                requested_at=datetime.now(SINGAPORE),
            )
            session.add(booking)
            session.flush()
            try:
                claimed = claim_venue_occupancy(
                    session,
                    booking,
                    event_slots=[(event.proposed_date, slot) for slot in event_slots],
                )
            except VenueOccupancyConflict as conflict:
                session.rollback()
                return jsonify(
                    error=str(conflict),
                    conflict={"date": conflict.day.isoformat(), "slot": conflict.slot},
                ), 409
            for occupied in claimed:
                if occupied.kind is OccupancyKind.SETUP:
                    booking.setup_date, booking.setup_slot = occupied.date, occupied.slot
                elif occupied.kind is OccupancyKind.TURNAROUND:
                    booking.turnaround_date, booking.turnaround_slot = occupied.date, occupied.slot
            # SPL-79: the request is the booking's first recorded status change.
            record_booking_transition(
                session,
                booking.id,
                action="request",
                previous_status=None,
                resulting_status=REQUESTED,
                actor_account_id=g.user_id,
                changed_at=booking.requested_at,
            )
            session.commit()
            return jsonify(booking=serialize_venue_booking(session, booking)), 201


def serialize_venue_booking(session: Session, booking: VenueBooking) -> dict[str, Any]:
    """The booking as SPL-77 records it, plus SPL-89's stored review marker."""

    venue = session.get(Venue, booking.venue_id)
    requester = (
        session.get(Account, booking.requested_by_account_id)
        if booking.requested_by_account_id
        else None
    )
    withdrawer = (
        session.get(Account, booking.withdrawn_by_account_id)
        if booking.withdrawn_by_account_id
        else None
    )
    approver = (
        session.get(Account, booking.approved_by_account_id)
        if booking.approved_by_account_id
        else None
    )
    rejecter = (
        session.get(Account, booking.rejected_by_account_id)
        if booking.rejected_by_account_id
        else None
    )
    return {
        "id": booking.id,
        "event_request_id": booking.event_request_id,
        "venue": {"id": venue.id, "name": venue.name},
        "date": _date(booking.booking_date),
        "event_slots": booking.event_slots or [],
        "timing": booking.exact_timing,
        "reviewed_requirements": booking.reviewed_requirements,
        "review_reasons": _exact_reasons(session, booking),
        "setup": _slot(booking.setup_date, booking.setup_slot),
        "turnaround": _slot(booking.turnaround_date, booking.turnaround_slot),
        "layout": booking.layout,
        "expected_attendance": booking.expected_attendance,
        # SPL-131: the facilities this booking was checked against (the event's when it recorded
        # none of its own).
        "required_facilities": _facilities(session, booking),
        "status": booking.status,
        "requested_by": (
            {"id": requester.id, "name": requester.display_name} if requester else None
        ),
        "requested_at": _timestamp(booking.requested_at),
        "requires_review": booking.requires_review,
        "review_trigger_block_id": booking.review_trigger_block_id,
        "review_marked_at": _timestamp(booking.review_marked_at),
        # SPL-78: the withdrawal record, null unless the request was withdrawn.
        "withdrawn_by": (
            {"id": withdrawer.id, "name": withdrawer.display_name} if withdrawer else None
        ),
        "withdrawn_at": _timestamp(booking.withdrawn_at),
        # SPL-81: the approval record, null unless the request was approved.
        "approved_by": {"id": approver.id, "name": approver.display_name} if approver else None,
        "approved_at": _timestamp(booking.approved_at),
        "approval_note": booking.approval_note,
        # SPL-82: the rejection record, null unless the request was rejected.
        "rejected_by": {"id": rejecter.id, "name": rejecter.display_name} if rejecter else None,
        "rejected_at": _timestamp(booking.rejected_at),
        "rejection_reason": booking.rejection_reason,
        "rejection_alternative_suggestion": booking.rejection_alternative_suggestion,
    }


def _booking_request_body() -> tuple[int, str, int | None, list[str] | None]:
    """Allow only reviewed inputs; identity, requirements and status remain server-owned.

    SPL-131 adds two optional fields, the booking's attendee count and facilities; omitted, the
    event's values apply.
    """

    data = request.get_json(silent=True)
    allowed = {"venue_id", "layout"}
    if current_app.config["EXACT_VENUE_TIMING_ENABLED"]:
        allowed |= {"date", "start_time", "end_time", "venue_revision"}
    if not isinstance(data, dict) or not allowed <= set(data) <= allowed | ARRANGEMENT_FIELDS:
        if current_app.config["EXACT_VENUE_TIMING_ENABLED"]:
            abort(400, "Send venue, layout, date, start/end times and the reviewed venue revision.")
        abort(400, "Send only the venue and the selected layout.")
    venue_id, layout = data["venue_id"], data["layout"]
    if isinstance(venue_id, bool) or not isinstance(venue_id, int) or venue_id <= 0:
        abort(400, "Choose a venue from the catalogue.")
    if not isinstance(layout, str) or not layout.strip():
        abort(400, "Choose a layout for the booking.")
    if len(layout.strip()) > MAX_LAYOUT_LENGTH:
        abort(400, f"Keep the layout to {MAX_LAYOUT_LENGTH} characters or fewer.")
    return venue_id, layout.strip(), *arrangement_fields(data)


def _event_slots(event: EventRequest) -> list[str]:
    if event.proposed_date is None or not event.start_time or not event.end_time:
        return []
    return slots_for_range(event.start_time, event.end_time)


def _failed_checks(
    venue: Venue,
    event: EventRequest,
    event_slots: list[str],
    layout_name: str,
    attendee_count: int | None,
    facilities: list[str],
) -> list[str]:
    """Labels of every unmet suitability check, in SPL-75's check order.

    Timing is split from SPL-75's combined check on purpose: whether the venue can host the
    event and preparation slots at all is a suitability failure, while those slots being
    occupied is an AC5 conflict that must name the date and slot, so it is left to the claim.
    The other checks are this booking's own (SPL-131 AC3).
    """

    failed = [] if _venue_can_host(venue, event, event_slots) else [TIMING_CHECK]
    return failed + [
        check["label"]
        for check in arrangement_checks(
            venue,
            event,
            layout_name=layout_name,
            attendee_count=attendee_count,
            facilities=facilities,
        )
        if not check["passed"]
    ]


def _venue_can_host(venue: Venue, event: EventRequest, event_slots: list[str]) -> bool:
    if not event_slots:
        return False
    required = derive_venue_occupancy(
        ((event.proposed_date, slot) for slot in event_slots),
        setup_buffer_slots=venue.setup_buffer_slots,
        turnaround_buffer_slots=venue.turnaround_buffer_slots,
    )
    return all(occupied.slot in venue.operating_slots for occupied in required)


def _slot(day: date | None, slot: str | None) -> dict[str, str] | None:
    return {"date": day.isoformat(), "slot": slot} if day and slot else None


def _date(value: date | None) -> str | None:
    return value.isoformat() if value else None


def _timestamp(value: datetime | None) -> str | None:
    if value is None:
        return None
    # SQLite drops the offset; every stored time is Singapore time (Q36).
    aware = value if value.tzinfo else value.replace(tzinfo=SINGAPORE)
    return aware.astimezone(SINGAPORE).isoformat()


def _exact_reasons(session, booking):
    from app.exact_venue_bookings import exact_review_reasons

    return exact_review_reasons(session, booking)


def _facilities(session: Session, booking: VenueBooking) -> list[str]:
    from app.venue_arrangements import booking_facilities

    return booking_facilities(booking, session.get(EventRequest, booking.event_request_id))


def _already_held(venue: Venue) -> str:
    return (
        f"This event already holds {venue.name} at an overlapping time. "
        "Choose another venue or time."
    )


def _request_exact(session, event, venue, layout_name, attendee_count, facilities):
    from app.exact_venue_availability import exact_availability, timing_for
    from app.exact_venue_bookings import requirements, saved_event_interval
    from app.venue_timing import parse_event_interval

    data = request.get_json()
    if type(data["venue_revision"]) is not int:
        abort(400, "Send the reviewed venue revision.")
    if data["venue_revision"] != venue.timing_revision:
        abort(409, "Venue timing changed. Search again and review the updated interval.")
    try:
        interval = parse_event_interval(data["date"], data["start_time"], data["end_time"])
    except ValueError as exc:
        abort(400, str(exc))
    try:
        saved_interval = saved_event_interval(event)
    except ValueError as exc:
        abort(409, str(exc))
    # SPL-131 AC2: each booking has its own times, inside the saved event's start and end.
    if not within_event(interval, saved_interval):
        abort(
            409,
            "Requested date and times must fall within the saved event. "
            "Search again within its recorded schedule.",
        )
    selected = arrangement_layout(venue.layouts, layout_name, attendee_count)
    failed = [
        check["label"]
        for check in arrangement_checks(
            venue,
            event,
            layout_name=layout_name,
            attendee_count=attendee_count,
            facilities=facilities,
        )
        if not check["passed"]
    ]
    # SPL-131 AC5: refuse a second hold on this venue for this event at an overlapping time.
    try:
        occupied = timing_for(venue, interval)[0]
    except (TypeError, ValueError):
        occupied = None
    if occupied is not None and same_event_overlap(session, event.id, venue.id, occupied):
        abort(409, _already_held(venue))
    available, detail, timing = exact_availability(session, venue, interval)
    if failed or not available:
        abort(409, "; ".join(failed + ([] if available else [detail])))
    timing["venue_revision"] = venue.timing_revision
    booking = VenueBooking(
        event_request_id=event.id,
        venue_id=venue.id,
        status=REQUESTED,
        layout=selected.layout,
        expected_attendance=attendee_count,
        required_facilities=facilities,
        booking_date=interval.start.date(),
        event_slots=[],
        exact_timing=timing,
        reviewed_requirements=requirements(event),
        requested_by_account_id=g.user_id,
        requested_at=datetime.now(SINGAPORE),
    )
    session.add(booking)
    session.flush()
    record_booking_transition(
        session,
        booking.id,
        action="request",
        previous_status=None,
        resulting_status=REQUESTED,
        actor_account_id=g.user_id,
        changed_at=booking.requested_at,
    )
    session.commit()
    return jsonify(booking=serialize_venue_booking(session, booking)), 201
