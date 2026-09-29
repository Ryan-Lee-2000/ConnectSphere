"""Assigned-coordinator venue-booking requests for SPL-77 (CS-E09-S3).

The route consumes the shared foundations rather than restating them: SPL-75 profile
suitability checks, SPL-87 preparation derivation and SPL-83/SPL-89 atomic occupancy claims
(see docs/development/SPL-77-integration-contract.md).
"""

from datetime import date, datetime
from typing import Any

from flask import Flask, abort, g, jsonify, request
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.authorization import require_roles
from app.coordinator_assignment import MAX_EVENT_REQUEST_ID, is_assigned_coordinator
from app.event_requests import SINGAPORE
from app.models import (
    ACTIVE_BOOKING_STATUSES,
    Account,
    EventRequest,
    Role,
    Venue,
    VenueBooking,
    VenueLayout,
)
from app.slots import OccupancyKind, derive_venue_occupancy, slots_for_range
from app.venue_availability import profile_suitability_checks
from app.venue_booking_history import record_booking_transition
from app.venue_conflicts import VenueOccupancyConflict, claim_venue_occupancy

PLANNING = "planning"
REQUESTED = "requested"
TIMING_CHECK = "Timing and preparation"
LAYOUT_CHECK = "Layout and capacity"
MAX_LAYOUT_LENGTH = 100
NOT_FOUND = "Assigned event not found."


def register_venue_booking_request_routes(app: Flask) -> None:
    @app.post("/api/event-requests/<int:event_request_id>/venue-bookings")
    @require_roles(Role.EVENT_COORDINATOR)
    def request_venue_booking(event_request_id: int):
        venue_id, layout_name = _booking_request_body()
        if event_request_id > MAX_EVENT_REQUEST_ID:
            abort(404, NOT_FOUND)
        with Session(app.extensions["engine"]) as session:
            if not is_assigned_coordinator(session, event_request_id, g.user_id):
                abort(404, NOT_FOUND)
            # Row lock: concurrent requests for one event queue here, so the one-active-booking
            # check below always sees the other request's committed booking (AC4).
            event = session.scalar(
                select(EventRequest).where(EventRequest.id == event_request_id).with_for_update()
            )
            if event is None:
                abort(404, NOT_FOUND)
            if event.status != PLANNING:
                abort(409, "A venue booking can be requested only while the event is in Planning.")
            venue = session.scalar(
                select(Venue).options(selectinload(Venue.layouts)).where(Venue.id == venue_id)
            )
            if venue is None:
                abort(404, "Venue not found.")
            if session.scalar(
                select(VenueBooking.id).where(
                    VenueBooking.event_request_id == event.id,
                    VenueBooking.status.in_(ACTIVE_BOOKING_STATUSES),
                )
            ):
                abort(409, "This event already has an active venue-booking request.")

            event_slots = _event_slots(event)
            selected_layout = _selected_layout(venue.layouts, layout_name, event)
            failed = _failed_checks(venue, event, event_slots, selected_layout)
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
                expected_attendance=event.expected_attendance,
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
        "setup": _slot(booking.setup_date, booking.setup_slot),
        "turnaround": _slot(booking.turnaround_date, booking.turnaround_slot),
        "layout": booking.layout,
        "expected_attendance": booking.expected_attendance,
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


def _booking_request_body() -> tuple[int, str]:
    """Exactly a venue and a layout; everything else is server-owned (AC3, AC6)."""

    data = request.get_json(silent=True)
    if not isinstance(data, dict) or set(data) != {"venue_id", "layout"}:
        abort(400, "Send only the venue and the selected layout.")
    venue_id, layout = data["venue_id"], data["layout"]
    if isinstance(venue_id, bool) or not isinstance(venue_id, int) or venue_id <= 0:
        abort(400, "Choose a venue from the catalogue.")
    if not isinstance(layout, str) or not layout.strip():
        abort(400, "Choose a layout for the booking.")
    if len(layout.strip()) > MAX_LAYOUT_LENGTH:
        abort(400, f"Keep the layout to {MAX_LAYOUT_LENGTH} characters or fewer.")
    return venue_id, layout.strip()


def _event_slots(event: EventRequest) -> list[str]:
    if event.proposed_date is None or not event.start_time or not event.end_time:
        return []
    return slots_for_range(event.start_time, event.end_time)


def _selected_layout(
    layouts: list[VenueLayout], layout_name: str, event: EventRequest
) -> VenueLayout | None:
    """The venue's layout of that name, if it holds the event's expected attendance (AC2)."""

    wanted = layout_name.casefold()
    for layout in layouts:
        if (
            layout.layout.casefold() == wanted
            and event.expected_attendance is not None
            and layout.capacity >= event.expected_attendance
        ):
            return layout
    return None


def _failed_checks(
    venue: Venue,
    event: EventRequest,
    event_slots: list[str],
    selected_layout: VenueLayout | None,
) -> list[str]:
    """Labels of every unmet suitability check, in SPL-75's check order.

    Timing is split from SPL-75's combined check on purpose: whether the venue can host the
    event and preparation slots at all is a suitability failure, while those slots being
    occupied is an AC5 conflict that must name the date and slot, so it is left to the claim.
    """

    failed = [] if _venue_can_host(venue, event, event_slots) else [TIMING_CHECK]
    failed += [
        check["label"] for check in profile_suitability_checks(venue, event) if not check["passed"]
    ]
    if selected_layout is None and LAYOUT_CHECK not in failed:
        failed.insert(1 if failed[:1] == [TIMING_CHECK] else 0, LAYOUT_CHECK)
    return failed


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
