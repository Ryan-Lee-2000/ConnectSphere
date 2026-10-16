"""Event confirmation (SPL-85, CS-E07-S3): the gate, its locks and what the organiser sees.

An event can be confirmed once its essential arrangements are complete (Q80, Q98). For Release 1
those are the venue and the essential equipment:

* AC2 - at least one Approved venue booking. Team interpretation: no booking may still be
  Requested, because a pending venue request is an unfinished arrangement. With one booking per
  event today this changes nothing; it keeps the rule correct once SPL-131 allows several.
* AC3 - SPL-99's ``derive_equipment_readiness`` decides the equipment side, so the coordinator's
  readiness panel and this gate can never disagree. It also blocks an undecided or unmapped line,
  which could still turn out to be essential (Q106).
* AC4 - any active booking or equipment line under review blocks, essential or not. SPL-99 already
  reports reviews on Essential lines; this module adds the remaining lines and the bookings.

Every blocker is returned at once, each with a stable ``code`` so callers never parse messages.
"""

from datetime import datetime
from typing import Any

from flask import Flask, abort, g, jsonify
from sqlalchemy import select, update
from sqlalchemy.orm import Session, object_session

from app.authorization import require_roles
from app.equipment_readiness import ESSENTIAL, REMOVED, REVIEW_REQUIRED, derive_equipment_readiness
from app.equipment_reservation_state import remaining_quantity
from app.models import (
    ACTIVE_BOOKING_STATUSES,
    Account,
    EquipmentRequirement,
    EventRequest,
    Role,
    VenueBooking,
)

APPROVED = "approved"
REQUESTED = "requested"
PLANNING = "planning"
NOT_PLANNING_FOR_CONFIRMATION = "Only an event in Planning can be confirmed."
CONFIRMATION_BLOCKED = "This event cannot be confirmed yet."


def register_event_confirmation_routes(app: Flask) -> None:
    # Imported here: event_review imports coordinator_assignment, which imports this module.
    from app.coordinator_assignment import MAX_EVENT_REQUEST_ID
    from app.event_requests import SINGAPORE
    from app.event_review import (
        CONFIRM,
        _require_action_without_parameters,
        _serialize_event,
        _serialize_transition,
        transition_event_status,
    )

    @app.post("/api/event-requests/<int:event_request_id>/confirm")
    @require_roles(Role.EVENT_COORDINATOR)
    def confirm_event(event_request_id: int):
        """The assigned coordinator confirms a Planning event once its arrangements are done."""

        _require_action_without_parameters("Confirmation")
        if event_request_id > MAX_EVENT_REQUEST_ID:
            abort(404, "Assigned event not found.")
        with Session(app.extensions["engine"]) as session:
            # The gate is evaluated on locked rows, so a booking, review flag or equipment release
            # that commits concurrently is either seen here or waits for this transaction (AC3/AC4).
            event, bookings, lines = lock_for_confirmation(session, event_request_id, g.user_id)
            if event.status != PLANNING:
                abort(409, NOT_PLANNING_FOR_CONFIRMATION)
            readiness = derive_confirmation_readiness(session, bookings, lines)
            if not readiness["ready"]:
                session.rollback()
                return jsonify(error=CONFIRMATION_BLOCKED, blockers=readiness["blockers"]), 409
            now = datetime.now(SINGAPORE)
            # The locked Planning row guarantees the shared rule accepts this transition.
            audit = transition_event_status(
                session,
                event_request_id=event_request_id,
                action=CONFIRM,
                actor_account_id=g.user_id,
                changed_at=now,
            )
            session.execute(
                update(EventRequest)
                .where(EventRequest.id == event_request_id)
                .values(confirmed_by_account_id=g.user_id, confirmed_at=now)
                .execution_options(synchronize_session=False)
            )
            session.commit()
            actor = session.get(Account, g.user_id)
            session.expire_all()
            event = session.get(EventRequest, event_request_id)
            return jsonify(
                event={**_serialize_event(event), **serialize_confirmation(event)},
                transition=_serialize_transition(audit, actor),
                message="Event confirmed. Everyone involved can now see it will go ahead.",
            )


def lock_for_confirmation(
    session: Session, event_request_id: int, coordinator_id: str
) -> tuple[EventRequest, list[VenueBooking], list[EquipmentRequirement]]:
    """Lock everything the gate reads, in the shared order, and return fresh copies.

    Order: event (and its assignment), each active booking's venue, the bookings, then the
    equipment lines. Booking writers take event, venue, booking (SPL-137); venue-only writers such
    as operational blocks take venue then booking; equipment writers take the stock pool then the
    line. Following the same order means no cycle, so no deadlock, and a concurrent change either
    commits before this read or waits until the confirmation has committed.
    """

    from app.exact_venue_bookings import lock_event, lock_venue

    # With a coordinator id, lock_event refuses with 404 unless the event exists and is assigned to
    # that coordinator, so a missing or someone else's event never reaches the code below.
    event = lock_event(session, event_request_id, coordinator_id)
    venue_ids = session.scalars(
        select(VenueBooking.venue_id)
        .where(
            VenueBooking.event_request_id == event_request_id,
            VenueBooking.status.in_(ACTIVE_BOOKING_STATUSES),
        )
        .distinct()
    ).all()
    for venue_id in sorted(venue_ids):
        lock_venue(session, venue_id)
    bookings = session.scalars(
        select(VenueBooking)
        .where(VenueBooking.event_request_id == event_request_id)
        .order_by(VenueBooking.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).all()
    lines = session.scalars(
        select(EquipmentRequirement)
        .where(EquipmentRequirement.event_request_id == event_request_id)
        .order_by(EquipmentRequirement.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).all()
    return event, list(bookings), list(lines)


def derive_confirmation_readiness(
    session: Session,
    bookings: list[VenueBooking],
    lines: list[EquipmentRequirement],
) -> dict[str, Any]:
    """Whether the event may be confirmed now, and every reason it may not."""

    blockers = _venue_blockers(session, bookings)
    blockers.extend(derive_equipment_readiness(lines)["blockers"])
    blockers.extend(_other_equipment_reviews(lines))
    return {"ready": not blockers, "blockers": blockers}


def confirmation_readiness_for(event: EventRequest) -> dict[str, Any]:
    """The same result for a read-only view, from the event's loaded relationships."""

    bookings = sorted(event.venue_bookings, key=lambda booking: booking.id)
    return derive_confirmation_readiness(
        object_session(event), bookings, list(event.equipment_requirements)
    )


def serialize_confirmation(event: EventRequest) -> dict[str, Any]:
    """Who confirmed the event and when (AC5); both null until it is confirmed."""

    from app.event_requests import _singapore_time

    return {
        "confirmed_by": (
            {"id": event.confirmer.id, "name": event.confirmer.display_name}
            if event.confirmer
            else None
        ),
        "confirmed_at": _singapore_time(event.confirmed_at) if event.confirmed_at else None,
    }


def serialize_confirmed_arrangements(event: EventRequest) -> dict[str, Any] | None:
    """The venue and equipment the organiser can rely on, once the event is Confirmed (AC5).

    Only Approved bookings appear: a rejected or cancelled booking is history, not an arrangement.
    Every active equipment line appears with what is actually held for it, so a Non-essential
    shortfall that did not block confirmation is still shown honestly.
    """

    if event.status != "confirmed":
        return None
    time_format = "%H:%M"
    venues = [
        {
            "booking_id": booking.id,
            "venue": booking.venue.name,
            "date": booking.booking_date.isoformat() if booking.booking_date else None,
            "start_time": event.start_time.strftime(time_format) if event.start_time else None,
            "end_time": event.end_time.strftime(time_format) if event.end_time else None,
            "layout": booking.layout,
        }
        for booking in sorted(event.venue_bookings, key=lambda booking: booking.id)
        if booking.status == APPROVED
    ]
    equipment = [
        {
            "requirement_id": line.id,
            "equipment": line.catalogue_type.name if line.catalogue_type else line.equipment_type,
            "quantity": line.quantity,
            "reserved_quantity": sum(remaining_quantity(item) for item in line.reservations),
            "essential": line.essentiality == ESSENTIAL,
        }
        for line in event.equipment_requirements
        if line.status != REMOVED
    ]
    return {"venues": venues, "equipment": equipment}


def _venue_blockers(session: Session, bookings: list[VenueBooking]) -> list[dict[str, Any]]:
    from app.exact_venue_bookings import exact_review_reasons

    active = [booking for booking in bookings if booking.status in ACTIVE_BOOKING_STATUSES]
    blockers = []
    if not any(booking.status == APPROVED for booking in active):
        blockers.append(
            {
                "code": "no_approved_venue_booking",
                "booking_id": None,
                "message": "Get a venue booking approved by Venue Staff.",
            }
        )
    for booking in active:
        name = booking.venue.name
        if booking.status == REQUESTED:
            blockers.append(
                {
                    "code": "venue_booking_pending",
                    "booking_id": booking.id,
                    "message": f"{name} is still waiting for a Venue Staff decision.",
                }
            )
        if booking.requires_review or exact_review_reasons(session, booking):
            blockers.append(
                {
                    "code": "venue_booking_review_required",
                    "booking_id": booking.id,
                    "message": f"Resolve the review flagged on the {name} booking.",
                }
            )
    return blockers


def _other_equipment_reviews(lines: list[EquipmentRequirement]) -> list[dict[str, Any]]:
    """Reviews on active lines that SPL-99 does not already report (it covers Essential lines)."""

    blockers = []
    for line in lines:
        if line.status == REMOVED or line.essentiality == ESSENTIAL:
            continue
        if line.status == REVIEW_REQUIRED or line.review_reason:
            name = line.catalogue_type.name if line.catalogue_type else line.equipment_type
            blockers.append(
                {
                    "code": "equipment_review_required",
                    "requirement_id": line.id,
                    "message": line.review_reason or f"Resolve the outstanding review for {name}.",
                }
            )
    return blockers
