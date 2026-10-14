"""Read-only equipment readiness for the assigned Event Coordinator (SPL-99).

The readiness rule lives in the backend so the coordinator view and SPL-85 event confirmation
can consume one result.  It is derived from retained reservations rather than trusting the line's
status: SPL-98 releases are append-only, so a reservation row may no longer hold its full original
quantity.  Removed lines stay in audit history but do not participate in current readiness.
"""

from typing import Any

from app.equipment_reservation_state import released_quantity, remaining_quantity
from app.models import (
    EquipmentRequirement,
    EquipmentRequirementUnavailabilityRecord,
    EquipmentReservation,
    EquipmentReviewNote,
)

REMOVED = "removed"
ESSENTIAL = "essential"
REVIEW_REQUIRED = "review_required"


def serialize_equipment_requirement(line: EquipmentRequirement) -> dict[str, Any]:
    """Return the complete, read-only state of one requirement line."""

    active_reservations = [
        reservation for reservation in line.reservations if remaining_quantity(reservation) > 0
    ]
    reserved_quantity = sum(remaining_quantity(item) for item in active_reservations)
    latest_return = max((item.commitment_end_date for item in active_reservations), default=None)
    return {
        "id": line.id,
        # Keep the original three keys used by the existing submitted-request summary.
        "equipment_type": line.catalogue_type.name if line.catalogue_type else line.equipment_type,
        "quantity": line.quantity,
        "notes": line.notes,
        "required_quantity": line.quantity,
        "reserved_quantity": reserved_quantity,
        "status": line.status,
        "essentiality": line.essentiality,
        "needs_mapping": line.equipment_type_id is None,
        # Several partial reservations may have different dates.  The line is not completely
        # returned until the latest retained reservation ends, so that is the line-level date.
        "planned_return_date": latest_return.isoformat() if latest_return else None,
        "active_reservations": [_serialize_reservation(item) for item in active_reservations],
        "technical_support_notes": [_serialize_note(note) for note in line.review_notes],
        "unavailability_history": [
            _serialize_unavailability_record(record) for record in line.unavailability_records
        ],
        "outstanding_review_reasons": [line.review_reason] if line.review_reason else [],
    }


def derive_equipment_readiness(
    requirements: list[EquipmentRequirement],
) -> dict[str, Any]:
    """Return a reusable readiness result and every reason that currently blocks it.

    A blocker identifies the affected line and carries a stable code for later server consumers.
    Messages are included for the coordinator UI, but later workflows should branch on ``code``.
    """

    active = [line for line in requirements if line.status != REMOVED]
    blockers: list[dict[str, Any]] = []
    for line in active:
        reserved = sum(remaining_quantity(item) for item in line.reservations)
        display_name = line.catalogue_type.name if line.catalogue_type else line.equipment_type
        if line.essentiality not in {ESSENTIAL, "non_essential"}:
            blockers.append(
                _blocker(
                    line,
                    "essentiality_undecided",
                    f"Decide whether {display_name} is essential.",
                )
            )
        if line.equipment_type_id is None:
            blockers.append(
                _blocker(
                    line,
                    "legacy_requirement_unmapped",
                    f"Map {display_name} to the equipment catalogue.",
                )
            )
        if line.essentiality == ESSENTIAL:
            if reserved < line.quantity:
                shortfall = line.quantity - reserved
                blockers.append(
                    _blocker(
                        line,
                        "essential_not_fully_reserved",
                        f"Reserve {shortfall} more unit(s) of {display_name}.",
                    )
                )
            if line.status == REVIEW_REQUIRED or line.review_reason:
                blockers.append(
                    _blocker(
                        line,
                        "essential_review_outstanding",
                        line.review_reason or f"Resolve the outstanding review for {display_name}.",
                    )
                )
    return {
        "ready": not blockers,
        "has_equipment_blocker": bool(blockers),
        "active_requirement_count": len(active),
        "blockers": blockers,
    }


def _blocker(line: EquipmentRequirement, code: str, message: str) -> dict[str, Any]:
    return {"code": code, "requirement_id": line.id, "message": message}


def _serialize_reservation(reservation: EquipmentReservation) -> dict[str, Any]:
    return {
        "id": reservation.id,
        "reserved_quantity": reservation.quantity,
        "released_quantity": released_quantity(reservation),
        "remaining_quantity": remaining_quantity(reservation),
        "planned_return_date": reservation.commitment_end_date.isoformat(),
    }


def _serialize_note(note: EquipmentReviewNote) -> dict[str, Any]:
    return {
        "id": note.id,
        "note": note.note,
        "author": {
            "id": note.author.id,
            "name": note.author.display_name,
        },
        "created_at": note.created_at.isoformat(),
    }


def _serialize_unavailability_record(
    record: EquipmentRequirementUnavailabilityRecord,
) -> dict[str, Any]:
    return {
        "id": record.id,
        "action": record.action,
        "reason": record.reason,
        "alternative_suggestion": record.alternative_suggestion,
        "recorded_by": {
            "id": record.recorded_by_account_id,
            "name": record.recorded_by.display_name if record.recorded_by else None,
        },
        "recorded_at": record.recorded_at.isoformat(),
    }
