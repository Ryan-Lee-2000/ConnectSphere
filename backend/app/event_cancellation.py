"""Whole-event cancellation (SPL-86, CS-E07-S5): one transaction that frees every commitment.

The assigned coordinator cancels an event that will not go ahead (Q68, Q132) with a reason. In
the same transaction:

* AC3 - every Requested or Approved venue booking becomes Cancelled, which releases its occupied
  time; Rejected, Withdrawn and Cancelled bookings are history and stay as they are.
* AC3 - every equipment unit still held is released through SPL-98's shared release helper, so the
  release is appended to the equipment history exactly as a Technical Support release would be.
* AC4 - any failure rolls back the event, its bookings and its releases together.
* AC5 - the event row lock makes a second, simultaneous cancellation wait and then see Cancelled,
  so nothing is ever released twice.

Records are kept (Q20): nothing is deleted, and no access rule changes (AC6). Queues already
exclude cancelled work by booking and event status (AC7).
"""

from datetime import datetime
from typing import Any

from flask import Flask, abort, g, jsonify, request
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.authorization import require_roles
from app.models import (
    ACTIVE_BOOKING_STATUSES,
    Account,
    EquipmentRequirement,
    EquipmentReservationRelease,
    EventRequest,
    Role,
    VenueBooking,
)

CANCELLED = "cancelled"
FINAL_STATUSES = frozenset({"rejected", "withdrawn", "completed"})
MAX_REASON_LENGTH = 2000
ALREADY_CANCELLED = "This event is already cancelled."


def register_event_cancellation_routes(app: Flask) -> None:
    # Imported here: event_review imports coordinator_assignment, which imports event_requests.
    from app.coordinator_assignment import MAX_EVENT_REQUEST_ID
    from app.event_requests import SINGAPORE
    from app.event_review import (
        CANCEL,
        InvalidStatusTransition,
        _serialize_event,
        _serialize_transition,
        transition_event_status,
    )
    from app.event_statuses import status_label

    @app.post("/api/event-requests/<int:event_request_id>/cancel")
    @require_roles(Role.EVENT_COORDINATOR)
    def cancel_event(event_request_id: int):
        """The assigned coordinator cancels an event and frees its venues and equipment."""

        # Validate the body first, so an invalid request never reaches the database (AC2).
        reason = _cancellation_reason()
        if event_request_id > MAX_EVENT_REQUEST_ID:
            abort(404, "Assigned event not found.")
        with Session(app.extensions["engine"]) as session:
            event, bookings = _lock_event_and_bookings(session, event_request_id, g.user_id)
            if event.status == CANCELLED:
                abort(409, ALREADY_CANCELLED)
            if event.status in FINAL_STATUSES:
                label = status_label(event.status).lower()
                abort(409, f"This event is {label} and cannot be cancelled.")
            now = datetime.now(SINGAPORE)
            note = f"Event cancelled: {reason}"
            try:
                audit = transition_event_status(
                    session,
                    event_request_id=event_request_id,
                    action=CANCEL,
                    actor_account_id=g.user_id,
                    changed_at=now,
                )
            except InvalidStatusTransition:
                session.rollback()
                abort(409, "This event cannot be cancelled in its current status.")
            session.execute(
                update(EventRequest)
                .where(EventRequest.id == event_request_id)
                .values(
                    cancelled_by_account_id=g.user_id,
                    cancelled_at=now,
                    cancellation_reason=reason,
                )
                .execution_options(synchronize_session=False)
            )
            released_bookings = _cancel_bookings(session, bookings, g.user_id, now, note)
            releases = _release_equipment(session, event_request_id, g.user_id, now, note)
            # Imported here: notifications imports event_requests, which imports this module.
            from app.notifications import (
                add_attendee_notices,
                add_organiser_notice,
                add_technical_support_notices,
            )

            # SPL-123 AC3: the organiser is told the reason.
            add_organiser_notice(
                session,
                event,
                actor_id=g.user_id,
                kind="event_cancelled",
                source=audit,
                message=f"{event.name} has been cancelled. Reason: {reason}",
            )
            # SPL-124 AC2: the reason is written for staff, so attendees are told only the outcome.
            add_attendee_notices(
                session,
                event,
                kind="event_cancelled",
                source_id=event_request_id,
                message=f"{event.name} has been cancelled.",
            )
            if releases:
                # SPL-122 AC2: only an event that was holding reserved units notifies.
                units = sum(item.quantity for item in releases)
                add_technical_support_notices(
                    session,
                    event,
                    kind="event_cancelled",
                    source_id=event_request_id,
                    message=f"{event.name} was cancelled. {units} reserved equipment unit(s) "
                    "were released.",
                )
            session.commit()
            actor = session.get(Account, g.user_id)
            session.expire_all()
            event = session.get(EventRequest, event_request_id)
            return jsonify(
                event={**_serialize_event(event), **serialize_cancellation(event)},
                transition=_serialize_transition(audit, actor),
                released={
                    "venue_bookings": released_bookings,
                    "equipment_units": sum(item.quantity for item in releases),
                },
                message="Event cancelled. Its venues and equipment are free for other events.",
            )


def serialize_cancellation(event: EventRequest) -> dict[str, Any]:
    """Who cancelled the event, when and why (AC6); all null until it is cancelled."""

    from app.event_requests import _singapore_time

    return {
        "cancelled_by": (
            {"id": event.canceller.id, "name": event.canceller.display_name}
            if event.canceller
            else None
        ),
        "cancelled_at": _singapore_time(event.cancelled_at) if event.cancelled_at else None,
        "cancellation_reason": event.cancellation_reason,
    }


def _lock_event_and_bookings(
    session: Session, event_request_id: int, coordinator_id: str
) -> tuple[EventRequest, list[VenueBooking]]:
    """Lock the event (and assignment), its active bookings' venues, then the bookings.

    The same order as SPL-137's booking writers and SPL-85's confirmation, so no deadlock cycle.
    With the coordinator id, lock_event refuses with 404 unless the event is assigned to that
    coordinator, which also refuses a Draft (it has no assignment).
    """

    from app.exact_venue_bookings import lock_event, lock_venue

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
        .where(
            VenueBooking.event_request_id == event_request_id,
            VenueBooking.status.in_(ACTIVE_BOOKING_STATUSES),
        )
        .order_by(VenueBooking.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).all()
    return event, list(bookings)


def _cancel_bookings(
    session: Session, bookings: list[VenueBooking], actor_id: str, now: datetime, note: str
) -> list[int]:
    """Cancel every still-active booking, releasing only its own time, each with a history row."""

    from app.venue_booking_history import record_booking_transition
    from app.venue_conflicts import transition_booking_status

    cancelled = []
    for booking in bookings:
        previous = booking.status
        transition_booking_status(session, booking, CANCELLED)
        record_booking_transition(
            session,
            booking.id,
            action="cancel",
            previous_status=previous,
            resulting_status=CANCELLED,
            actor_account_id=actor_id,
            changed_at=now,
            note=note,
        )
        cancelled.append(booking.id)
    return cancelled


def _release_equipment(
    session: Session, event_request_id: int, actor_id: str, now: datetime, reason: str
) -> list[EquipmentReservationRelease]:
    """Release every held unit through SPL-98's helper: stock pools first, then the lines."""

    from app.equipment_releases import (
        RELEASABLE_REQUIREMENT_STATUSES,
        _held_quantity,
        _locked_types_for,
        _release_from_requirement,
    )

    # Scalar ids only before the pool locks, as SPL-98 does, so no stale line state is cached.
    type_ids = session.scalars(
        select(EquipmentRequirement.equipment_type_id)
        .where(EquipmentRequirement.event_request_id == event_request_id)
        .order_by(EquipmentRequirement.id)
    ).all()
    types = _locked_types_for(session, type_ids)
    lines = session.scalars(
        select(EquipmentRequirement)
        .where(EquipmentRequirement.event_request_id == event_request_id)
        .order_by(EquipmentRequirement.id)
        .execution_options(populate_existing=True)
        .with_for_update()
    ).all()
    releases: list[EquipmentReservationRelease] = []
    for line in lines:
        equipment_type = types.get(line.equipment_type_id)
        if equipment_type is None or line.status not in RELEASABLE_REQUIREMENT_STATUSES:
            continue
        held = _held_quantity(session, line.id)
        if held:
            releases.extend(
                _release_from_requirement(
                    session,
                    line,
                    equipment_type,
                    quantity=held,
                    reason=reason,
                    actor_id=actor_id,
                    now=now,
                )
            )
    return releases


def _cancellation_reason() -> str:
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or set(data) != {"reason"}:
        abort(400, "Send only the reason for cancelling this event.")
    reason = data["reason"]
    if not isinstance(reason, str) or not reason.strip():
        abort(400, "Give a reason for cancelling this event.")
    if len(reason.strip()) > MAX_REASON_LENGTH:
        abort(400, f"Keep the reason to {MAX_REASON_LENGTH} characters or fewer.")
    return reason.strip()
