"""Technical Support equipment-release workflow for SPL-98.

Reservations and releases are both append-only. This preserves the original commitment and its
release history while the shared availability calculation counts only the units still held.
"""

from datetime import datetime
from typing import Any

from flask import Flask, abort, g, jsonify, request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.authorization import require_roles
from app.equipment_availability import _quantity_status, _serialize_requirement
from app.equipment_reservation_state import remaining_quantity
from app.event_requests import SINGAPORE
from app.models import (
    EquipmentRequirement,
    EquipmentReservation,
    EquipmentReservationRelease,
    EquipmentType,
    EventRequest,
    Role,
)

PLANNING = "planning"
REVIEW_REQUIRED = "review_required"
RELEASABLE_REQUIREMENT_STATUSES = frozenset(
    {"requested", "partially_reserved", "reserved", REVIEW_REQUIRED}
)
MAX_EVENT_REQUEST_ID = 2**31 - 1
MAX_REQUIREMENT_ID = 2**31 - 1
ALLOWED_FIELDS = {"quantity", "reason"}


def _now() -> datetime:
    """The release clock is injectable so audit assertions remain deterministic."""

    return datetime.now(SINGAPORE)


def register_equipment_release_routes(app: Flask) -> None:
    """Register the manual partial and whole-event release operations."""

    @app.post("/api/equipment-requirements/<int:requirement_id>/releases")
    @require_roles(Role.TECHNICAL_SUPPORT_STAFF)
    def release_equipment_requirement(requirement_id: int):
        """Release part of one active requirement without deleting its reservation history."""

        quantity, reason = _release_request(require_quantity=True)
        assert quantity is not None
        with Session(app.extensions["engine"]) as session, session.begin():
            requirement, equipment_type = _locked_requirement(session, requirement_id)
            releases = _release_from_requirement(
                session,
                requirement,
                equipment_type,
                quantity=quantity,
                reason=reason,
                actor_id=g.user_id,
                now=_now(),
            )
            result = {
                "releases": [_serialize_release(item) for item in releases],
                "assessment": _serialize_requirement(session, requirement),
            }
        return jsonify(result), 201

    @app.post("/api/event-requests/<int:event_request_id>/equipment-releases")
    @require_roles(Role.TECHNICAL_SUPPORT_STAFF)
    def release_event_equipment(event_request_id: int):
        """Release every still-held line for one Planning event in one transaction (AC3)."""

        _, reason = _release_request(require_quantity=False)
        with Session(app.extensions["engine"]) as session, session.begin():
            event = _locked_planning_event(session, event_request_id)
            # Every workflow which changes a stock pool locks its EquipmentType before the
            # affected requirement rows.  Keep that order here and in the single-line release
            # path: SPL-96 may flag a requirement after it has locked the same stock pool.
            # Reversing the order can otherwise form a PostgreSQL deadlock cycle.
            requirement_preview = session.scalars(
                select(EquipmentRequirement)
                .where(EquipmentRequirement.event_request_id == event.id)
                .order_by(EquipmentRequirement.id)
            ).all()
            types = _locked_types_for(session, requirement_preview)
            requirements = session.scalars(
                select(EquipmentRequirement)
                .where(EquipmentRequirement.event_request_id == event.id)
                .order_by(EquipmentRequirement.id)
                .with_for_update()
            ).all()
            releases: list[EquipmentReservationRelease] = []
            released_requirements: list[EquipmentRequirement] = []
            for requirement in requirements:
                equipment_type = types.get(requirement.equipment_type_id)
                if (
                    equipment_type is None
                    or requirement.status not in RELEASABLE_REQUIREMENT_STATUSES
                ):
                    continue
                held = _held_quantity(session, requirement.id)
                if held:
                    releases.extend(
                        _release_from_requirement(
                            session,
                            requirement,
                            equipment_type,
                            quantity=held,
                            reason=reason,
                            actor_id=g.user_id,
                            now=_now(),
                        )
                    )
                    released_requirements.append(requirement)
            if not releases:
                abort(409, "This event has no held equipment to release.")
            result = {
                "event_id": event.id,
                "releases": [_serialize_release(item) for item in releases],
                # An event may contain unmapped request lines. They never hold a catalogue
                # reservation, so return assessments only for the lines this operation changed.
                "assessments": [
                    _serialize_requirement(session, item) for item in released_requirements
                ],
            }
        return jsonify(result), 201


def _release_request(*, require_quantity: bool) -> tuple[int | None, str]:
    """Accept an exact, reasoned release request and reject browser-supplied extras."""

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        abort(400, "A JSON object is required.")
    allowed = ALLOWED_FIELDS if require_quantity else {"reason"}
    unexpected = set(data) - allowed
    if unexpected:
        abort(400, f"Unexpected field: {sorted(unexpected)[0]}.")
    reason = data.get("reason")
    if not isinstance(reason, str) or not reason.strip():
        abort(400, "A release reason is required.")
    if not require_quantity:
        return None, reason.strip()
    quantity = data.get("quantity")
    if type(quantity) is not int or quantity <= 0:
        abort(400, "Quantity must be a positive whole number.")
    return quantity, reason.strip()


def _locked_requirement(
    session: Session, requirement_id: int
) -> tuple[EquipmentRequirement, EquipmentType]:
    """Lock one requirement and its stock pool before calculating releasable units."""

    if requirement_id > MAX_REQUIREMENT_ID:
        abort(404, "Equipment requirement not found.")
    # This first read finds the pool only. It deliberately does not lock the requirement: the
    # global stock-mutation order is EquipmentType then EquipmentRequirement (SPL-96/SPL-98).
    equipment_type_id = session.scalar(
        select(EquipmentRequirement.equipment_type_id).where(
            EquipmentRequirement.id == requirement_id
        )
    )
    if equipment_type_id is None:
        requirement = session.get(EquipmentRequirement, requirement_id)
        if requirement is None:
            abort(404, "Equipment requirement not found.")
        abort(409, "This equipment requirement is not mapped to a catalogue type.")
    equipment_type = session.scalar(
        select(EquipmentType).where(EquipmentType.id == equipment_type_id).with_for_update()
    )
    if equipment_type is None:
        abort(409, "The mapped equipment type is no longer available.")
    requirement = session.scalar(
        select(EquipmentRequirement)
        .where(EquipmentRequirement.id == requirement_id)
        .with_for_update()
    )
    if requirement is None:
        abort(404, "Equipment requirement not found.")
    if requirement.event_request.status != PLANNING:
        abort(409, "Equipment can only be released while the event is in Planning.")
    if requirement.status not in RELEASABLE_REQUIREMENT_STATUSES:
        abort(409, "This equipment requirement has no active reservation to release.")
    if requirement.equipment_type_id != equipment_type_id:
        abort(409, "This equipment requirement changed while its release was being prepared.")
    return requirement, equipment_type


def _locked_planning_event(session: Session, event_request_id: int) -> EventRequest:
    if event_request_id > MAX_EVENT_REQUEST_ID:
        abort(404, "Event request not found.")
    event = session.scalar(
        select(EventRequest).where(EventRequest.id == event_request_id).with_for_update()
    )
    if event is None:
        abort(404, "Event request not found.")
    if event.status != PLANNING:
        abort(409, "Equipment can only be released while the event is in Planning.")
    return event


def _locked_types_for(
    session: Session, requirements: list[EquipmentRequirement]
) -> dict[int, EquipmentType]:
    """Lock all pools in ascending order so event-wide release has a stable lock order."""

    type_ids = sorted({item.equipment_type_id for item in requirements if item.equipment_type_id})
    if not type_ids:
        return {}
    types = session.scalars(
        select(EquipmentType)
        .where(EquipmentType.id.in_(type_ids))
        .order_by(EquipmentType.id)
        .with_for_update()
    ).all()
    return {item.id: item for item in types}


def _locked_reservations(session: Session, requirement_id: int) -> list[EquipmentReservation]:
    return session.scalars(
        select(EquipmentReservation)
        .where(EquipmentReservation.equipment_requirement_id == requirement_id)
        .order_by(EquipmentReservation.id)
        .with_for_update()
    ).all()


def _held_quantity(session: Session, requirement_id: int) -> int:
    return sum(remaining_quantity(item) for item in _locked_reservations(session, requirement_id))


def _release_from_requirement(
    session: Session,
    requirement: EquipmentRequirement,
    equipment_type: EquipmentType,
    *,
    quantity: int,
    reason: str,
    actor_id: str,
    now: datetime,
) -> list[EquipmentReservationRelease]:
    """Append releases for a line, leaving original reservation rows immutable.

    The requirement and its equipment type must already be row-locked by the caller. Reserving,
    releasing, and return-date edits all lock the same equipment type row before changing shared
    commitment state, so a competing request recalculates after this transaction commits.
    """

    del equipment_type  # The caller's type lock is the shared-stock concurrency boundary.
    reservations = _locked_reservations(session, requirement.id)
    held = sum(remaining_quantity(item) for item in reservations)
    if quantity > held:
        abort(409, f"Only {held} unit(s) are still reserved for this requirement.")

    remaining_to_release = quantity
    releases: list[EquipmentReservationRelease] = []
    for reservation in reservations:
        available = remaining_quantity(reservation)
        released = min(available, remaining_to_release)
        if not released:
            continue
        entry = EquipmentReservationRelease(
            reservation_id=reservation.id,
            quantity=released,
            reason=reason,
            released_by_account_id=actor_id,
            released_at=now,
        )
        session.add(entry)
        releases.append(entry)
        remaining_to_release -= released
        if not remaining_to_release:
            break
    session.flush()
    still_held = held - quantity
    # Review Required is an unresolved safety flag. Releasing stock may reduce the held amount,
    # but it must not silently clear the flag or its explanation.
    if requirement.status != REVIEW_REQUIRED:
        requirement.status = _quantity_status(requirement.quantity, still_held)
    return releases


def _serialize_release(entry: EquipmentReservationRelease) -> dict[str, Any]:
    return {
        "id": entry.id,
        "reservation_id": entry.reservation_id,
        "quantity": entry.quantity,
        "reason": entry.reason,
        "released_by_account_id": entry.released_by_account_id,
        "released_at": entry.released_at.isoformat(),
    }
