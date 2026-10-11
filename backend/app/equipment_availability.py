"""Read-only equipment availability routes and calculations for SPL-95.

SPL-95 deliberately owns the calculation, not reservation or maintenance records.  The later
SPL-96 and SPL-97 stories supply persisted unavailable-unit and reservation inputs to this
module; until then, the calculation accepts empty inputs rather than fabricating commitments.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from flask import Flask, abort, g, jsonify, request
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.authorization import require_roles
from app.models import (
    EquipmentRequirement,
    EquipmentReservation,
    EquipmentType,
    EventRequest,
    Role,
)

ACTIVE_REQUIREMENT_STATUSES = (
    "requested",
    "partially_reserved",
    "reserved",
    "review_required",
    "unavailable",
)
RESERVABLE_REQUIREMENT_STATUSES = ("requested", "partially_reserved", "review_required")

# Technical Support assesses requirements while an event is being planned. Confirmed events stop
# appearing as actionable work here, but their future reservations still consume shared stock.
ASSESSABLE_EVENT_STATUSES = ("planning",)


@dataclass(frozen=True)
class AvailabilityAssessment:
    """The immutable outcome shown to Technical Support for one requirement line."""

    commitment_start: date
    commitment_end: date
    busiest_day: date
    total_stock: int
    unavailable_units: int
    active_reservations: int
    available_to_reserve: int
    reserved_quantity: int
    shortfall: int
    overcommitted_units: int


def commitment_days(collection_date: date, return_date: date) -> tuple[date, ...]:
    """Return every inclusive Singapore calendar day occupied by one equipment commitment."""

    return tuple(
        collection_date + timedelta(days=offset)
        for offset in range((return_date - collection_date).days + 1)
    )


def calculate_availability(
    *,
    total_stock: int,
    required_quantity: int,
    collection_date: date,
    return_date: date,
    reserved_quantity: int = 0,
    unavailable_by_day: Mapping[date, int] | None = None,
    reservations_by_day: Mapping[date, int] | None = None,
) -> AvailabilityAssessment:
    """Calculate the safest availability across the whole commitment period.

    The worst (busiest) day determines the units that can be promised. ``reservations_by_day``
    contains every active reservation on that day, including this line's retained quantity. The
    retained quantity is therefore removed once from physical stock and once from this line's
    remaining need. This is pure domain logic so SPL-97 can reuse it in its reservation transaction.
    """

    unavailable_by_day = unavailable_by_day or {}
    reservations_by_day = reservations_by_day or {}
    days = commitment_days(collection_date, return_date)
    daily_usage = [
        (day, max(0, unavailable_by_day.get(day, 0)), max(0, reservations_by_day.get(day, 0)))
        for day in days
    ]
    busiest_day, unavailable_units, active_reservations = max(
        daily_usage, key=lambda item: item[1] + item[2]
    )
    remaining_stock = total_stock - unavailable_units - active_reservations
    available_to_reserve = max(0, remaining_stock)
    overcommitted_units = max(0, -remaining_stock)
    shortfall = max(0, required_quantity - reserved_quantity - available_to_reserve)
    return AvailabilityAssessment(
        commitment_start=collection_date,
        commitment_end=return_date,
        busiest_day=busiest_day,
        total_stock=total_stock,
        unavailable_units=unavailable_units,
        active_reservations=active_reservations,
        available_to_reserve=available_to_reserve,
        reserved_quantity=reserved_quantity,
        shortfall=shortfall,
        overcommitted_units=overcommitted_units,
    )


def register_equipment_availability_routes(app: Flask) -> None:
    """Register the Technical Support availability and SPL-97 reservation APIs."""

    @app.get("/api/equipment-availability")
    @require_roles(Role.TECHNICAL_SUPPORT_STAFF)
    def list_equipment_availability():
        with Session(app.extensions["engine"]) as session:
            requirements = (
                session.scalars(
                    select(EquipmentRequirement)
                    .join(EventRequest)
                    .options(
                        joinedload(EquipmentRequirement.catalogue_type),
                        joinedload(EquipmentRequirement.event_request),
                    )
                    .where(
                        EventRequest.status.in_(ASSESSABLE_EVENT_STATUSES),
                        EquipmentRequirement.status.in_(ACTIVE_REQUIREMENT_STATUSES),
                        EquipmentRequirement.equipment_type_id.is_not(None),
                        EquipmentRequirement.required_start_date.is_not(None),
                        EquipmentRequirement.required_end_date.is_not(None),
                    )
                    .order_by(
                        EventRequest.proposed_date, EventRequest.name, EquipmentRequirement.id
                    )
                )
                .unique()
                .all()
            )
            return jsonify(
                assessments=[
                    _serialize_requirement(session, requirement) for requirement in requirements
                ],
                # Both inputs this calculation was built to take are now supplied: SPL-97's
                # reservations and SPL-96's unavailable units.
                input_notice=(
                    "Availability includes reservations held across each equipment type's full "
                    "commitment period, and units Technical Support has recorded as unavailable. "
                    "Reserving units does not confirm the event."
                ),
            )

    @app.post("/api/equipment-requirements/<int:requirement_id>/reservations")
    @require_roles(Role.TECHNICAL_SUPPORT_STAFF)
    def reserve_equipment(requirement_id: int):
        """Reserve a positive feasible quantity after locking the shared equipment pool."""

        quantity = _reservation_quantity(request.get_json(silent=True))
        with Session(app.extensions["engine"]) as session, session.begin():
            requirement, equipment_type = _locked_reservable_requirement(session, requirement_id)
            assessment = _assessment_for(session, requirement, equipment_type)
            remaining_need = requirement.quantity - assessment.reserved_quantity
            if quantity > remaining_need:
                abort(
                    409,
                    "The requested quantity exceeds this requirement's unfulfilled quantity.",
                )
            if quantity > assessment.available_to_reserve:
                abort(
                    409,
                    "The requested quantity is not available for the full commitment period.",
                )

            reservation = EquipmentReservation(
                event_request_id=requirement.event_request_id,
                equipment_requirement_id=requirement.id,
                equipment_type_id=equipment_type.id,
                commitment_start_date=assessment.commitment_start,
                commitment_end_date=assessment.commitment_end,
                quantity=quantity,
                reserved_by_account_id=g.user_id,
                reserved_at=datetime.now(timezone.utc),
            )
            session.add(reservation)
            session.flush()
            total_reserved = assessment.reserved_quantity + quantity
            requirement.status = _quantity_status(requirement.quantity, total_reserved)
            result = {
                "reservation": _serialize_reservation(reservation),
                "assessment": _serialize_requirement(session, requirement),
            }
        return jsonify(result), 201

    @app.post("/api/equipment-requirements/<int:requirement_id>/revalidate-reservation")
    @require_roles(Role.TECHNICAL_SUPPORT_STAFF)
    def revalidate_equipment_reservation(requirement_id: int):
        """Clear Review Required only when retained stock still fits the shared pool."""

        if request.get_json(silent=True) not in (None, {}):
            abort(400, "Revalidation does not accept request data.")
        with Session(app.extensions["engine"]) as session, session.begin():
            requirement, equipment_type = _locked_reservable_requirement(session, requirement_id)
            if requirement.status != "review_required":
                abort(409, "Only a Review Required equipment requirement can be revalidated.")
            assessment = _assessment_for(session, requirement, equipment_type)
            if (
                assessment.overcommitted_units > 0
                or assessment.reserved_quantity > requirement.quantity
            ):
                abort(
                    409,
                    "Retained reservations are no longer feasible for the commitment period.",
                )
            requirement.status = _quantity_status(
                requirement.quantity, assessment.reserved_quantity
            )
            # SPL-96 AC3/AC4 added the explanation behind the flag. It is cleared with the flag,
            # so a stale reason can never outlive the Review Required state it explains.
            requirement.review_reason = None
            requirement.review_flagged_at = None
            result = {"assessment": _serialize_requirement(session, requirement)}
        return jsonify(result)


def _reservation_quantity(data: object) -> int:
    """Accept only one positive whole-number reserve request from the browser."""

    if not isinstance(data, dict) or set(data) != {"quantity"}:
        abort(400, "Provide only a positive whole-number quantity.")
    quantity = data["quantity"]
    if type(quantity) is not int or quantity <= 0:  # bool is intentionally not a quantity.
        abort(400, "Quantity must be a positive whole number.")
    return quantity


def _locked_reservable_requirement(
    session: Session, requirement_id: int
) -> tuple[EquipmentRequirement, EquipmentType]:
    """Lock one line and its stock pool before the transaction-time availability recheck."""

    requirement = session.scalar(
        select(EquipmentRequirement)
        .where(EquipmentRequirement.id == requirement_id)
        .with_for_update()
    )
    if requirement is None:
        abort(404, "Equipment requirement not found.")
    if requirement.event_request.status not in ASSESSABLE_EVENT_STATUSES:
        abort(409, "Equipment can only be reserved while the event is in Planning.")
    if requirement.status not in RESERVABLE_REQUIREMENT_STATUSES:
        abort(409, "This equipment requirement cannot receive another reservation.")
    if (
        requirement.equipment_type_id is None
        or requirement.required_start_date is None
        or requirement.required_end_date is None
    ):
        abort(409, "Map and date the equipment requirement before reserving it.")

    # Every reservation of this type takes this same row lock. A competing transaction waits,
    # then recalculates after the first commitment is visible instead of overallocating stock.
    equipment_type = session.scalar(
        select(EquipmentType)
        .where(EquipmentType.id == requirement.equipment_type_id)
        .with_for_update()
    )
    if equipment_type is None:
        abort(409, "The mapped equipment type is no longer available.")
    return requirement, equipment_type


def _assessment_for(
    session: Session, requirement: EquipmentRequirement, equipment_type: EquipmentType
) -> AvailabilityAssessment:
    """Calculate one line's view from all overlapping persisted reservations of its type."""

    assert requirement.required_start_date is not None
    assert requirement.required_end_date is not None
    collection_date = requirement.required_start_date - timedelta(days=1)
    reservations = session.scalars(
        select(EquipmentReservation).where(
            EquipmentReservation.equipment_type_id == equipment_type.id,
            EquipmentReservation.commitment_start_date <= requirement.required_end_date,
            EquipmentReservation.commitment_end_date >= collection_date,
        )
    ).all()
    reservations_by_day: dict[date, int] = {}
    reserved_quantity = 0
    for reservation in reservations:
        if reservation.equipment_requirement_id == requirement.id:
            reserved_quantity += reservation.quantity
        overlap_start = max(collection_date, reservation.commitment_start_date)
        overlap_end = min(requirement.required_end_date, reservation.commitment_end_date)
        for day in commitment_days(overlap_start, overlap_end):
            reservations_by_day[day] = reservations_by_day.get(day, 0) + reservation.quantity
    # SPL-96 AC2. Unavailability is current state with no end date (the story rules out a
    # maintenance schedule), so the same figure applies to every day of this commitment. Supplying
    # it here, rather than at the route, means the reserve and revalidate transactions above honour
    # it too — which is the "and reservation" half of AC2.
    unavailable_by_day = {
        day: equipment_type.unavailable_units
        for day in commitment_days(collection_date, requirement.required_end_date)
    }
    return calculate_availability(
        total_stock=equipment_type.total_stock,
        required_quantity=requirement.quantity,
        collection_date=collection_date,
        return_date=requirement.required_end_date,
        reserved_quantity=reserved_quantity,
        unavailable_by_day=unavailable_by_day,
        reservations_by_day=reservations_by_day,
    )


def _quantity_status(required_quantity: int, reserved_quantity: int) -> str:
    """Derive the normal state directly from the retained quantity on one line."""

    if reserved_quantity >= required_quantity:
        return "reserved"
    if reserved_quantity > 0:
        return "partially_reserved"
    return "requested"


def _serialize_requirement(session: Session, requirement: EquipmentRequirement) -> dict:
    """Make an availability decision readable without exposing database-only implementation data."""

    equipment_type = requirement.catalogue_type
    event = requirement.event_request
    assert equipment_type is not None
    assert requirement.required_start_date is not None
    assert requirement.required_end_date is not None
    # SPL-96's unavailable units are supplied inside _assessment_for, so the list, reserve and
    # revalidate paths all see the same reduced usable stock.
    assessment = _assessment_for(session, requirement, equipment_type)
    return {
        "requirement_id": requirement.id,
        "event": {
            "id": event.id,
            "name": event.name,
            "date": event.proposed_date.isoformat() if event.proposed_date else None,
        },
        "equipment_type": {
            "id": equipment_type.id,
            "name": equipment_type.name,
            "location": equipment_type.location,
        },
        "requirement_status": requirement.status,
        "required_quantity": requirement.quantity,
        "required_start_date": requirement.required_start_date.isoformat(),
        "required_end_date": requirement.required_end_date.isoformat(),
        "commitment_start": assessment.commitment_start.isoformat(),
        "commitment_end": assessment.commitment_end.isoformat(),
        "busiest_day": assessment.busiest_day.isoformat(),
        "total_stock": assessment.total_stock,
        "unavailable_units": assessment.unavailable_units,
        "active_reservations": assessment.active_reservations,
        "reserved_quantity": assessment.reserved_quantity,
        "available_to_reserve": assessment.available_to_reserve,
        "shortfall": assessment.shortfall,
        "overcommitted_units": assessment.overcommitted_units,
    }


def _serialize_reservation(reservation: EquipmentReservation) -> dict:
    """Return the minimal audit evidence that Technical Support just created."""

    return {
        "id": reservation.id,
        "quantity": reservation.quantity,
        "reserved_at": reservation.reserved_at.isoformat(),
    }
