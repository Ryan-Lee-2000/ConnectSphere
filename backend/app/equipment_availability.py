"""Read-only equipment availability routes and calculations for SPL-95.

SPL-95 deliberately owns the calculation, not reservation or maintenance records.  The later
SPL-96 and SPL-97 stories supply persisted unavailable-unit and reservation inputs to this
module; until then, the calculation accepts empty inputs rather than fabricating commitments.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, timedelta

from flask import Flask, jsonify
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.authorization import require_roles
from app.models import EquipmentRequirement, EventRequest, Role

ACTIVE_REQUIREMENT_STATUSES = (
    "requested",
    "partially_reserved",
    "reserved",
    "review_required",
    "unavailable",
)

# Technical Support assesses requirements while an event is being planned. Confirmed events stop
# appearing as actionable work here, but their future reservations must still be supplied to the
# shared calculation when SPL-97 integrates persisted reservation records.
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
    """Register the Technical Support read-only availability workspace API."""

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
                assessments=[_serialize_requirement(requirement) for requirement in requirements],
                input_notice=(
                    "No unavailable-unit records or active reservation records are integrated yet. "
                    "Availability currently reflects each catalogue type's total stock baseline."
                ),
            )


def _serialize_requirement(requirement: EquipmentRequirement) -> dict:
    """Make the shared calculation readable without exposing database-only implementation data."""

    equipment_type = requirement.catalogue_type
    event = requirement.event_request
    assert equipment_type is not None
    assert requirement.required_start_date is not None
    assert requirement.required_end_date is not None
    collection_date = requirement.required_start_date - timedelta(days=1)
    planned_return_date = requirement.required_end_date
    assessment = calculate_availability(
        total_stock=equipment_type.total_stock,
        required_quantity=requirement.quantity,
        collection_date=collection_date,
        return_date=planned_return_date,
    )
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
