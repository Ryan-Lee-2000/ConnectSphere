"""Technical Support's unavailable/restored decision for one event requirement (SPL-93)."""

from datetime import datetime
from typing import Any

from flask import Flask, abort, g, jsonify, request
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.authorization import require_roles
from app.equipment_reservation_state import remaining_quantity
from app.equipment_review_queue import ACTIVE_EVENT_STATUSES
from app.event_requests import SINGAPORE
from app.models import (
    EquipmentRequirement,
    EquipmentRequirementUnavailabilityRecord,
    EquipmentReservation,
    EquipmentType,
    EventRequest,
    Role,
)

REQUESTED = "requested"
UNAVAILABLE = "unavailable"
MARKED = "marked_unavailable"
RESTORED = "restored_to_requested"
MAX_TEXT_LENGTH = 2_000
NOT_FOUND = "Equipment requirement not found."


def _now() -> datetime:
    """Use one clock so the audit fields can be tested deterministically."""

    return datetime.now(SINGAPORE)


def register_equipment_requirement_unavailability_routes(app: Flask) -> None:
    """Register the narrow Technical Support workflow for SPL-93."""

    @app.post("/api/equipment-requirements/<int:requirement_id>/mark-unavailable")
    @require_roles(Role.TECHNICAL_SUPPORT_STAFF)
    def mark_requirement_unavailable(requirement_id: int):
        """Move an unheld Requested line to Unavailable, with a required explanation (AC1)."""

        reason, suggestion = _mark_request(request.get_json(silent=True))
        with Session(app.extensions["engine"]) as session, session.begin():
            line = _locked_requirement(session, requirement_id)
            if line.status != REQUESTED:
                abort(409, "Only a Requested equipment requirement can be marked unavailable.")
            if _reserved_quantity(session, line.id) != 0:
                abort(
                    409,
                    "Reserved equipment must be released before this requirement is unavailable.",
                )

            line.status = UNAVAILABLE
            record = EquipmentRequirementUnavailabilityRecord(
                equipment_requirement_id=line.id,
                action=MARKED,
                reason=reason,
                alternative_suggestion=suggestion,
                recorded_by_account_id=g.user_id,
                recorded_at=_now(),
            )
            session.add(record)
            session.flush()
            result = {
                "requirement": _serialize_requirement(line),
                "record": _serialize_record(record),
            }
        return jsonify(result), 201

    @app.post("/api/equipment-requirements/<int:requirement_id>/restore-requested")
    @require_roles(Role.TECHNICAL_SUPPORT_STAFF)
    def restore_requirement_requested(requirement_id: int):
        """Restore an unavailable line without removing its original explanation (AC3)."""

        if request.get_json(silent=True) not in (None, {}):
            abort(400, "Restoring a requirement does not accept request data.")
        with Session(app.extensions["engine"]) as session, session.begin():
            line = _locked_requirement(session, requirement_id)
            if line.status != UNAVAILABLE:
                abort(409, "Only an Unavailable equipment requirement can be restored.")
            # A requirement marked unavailable is unheld by AC1. Repeat the check after taking
            # the shared stock-pool lock so a concurrent reserve cannot bypass that invariant.
            if _reserved_quantity(session, line.id) != 0:
                abort(
                    409, "Reserved equipment must be released before this requirement is restored."
                )

            line.status = REQUESTED
            record = EquipmentRequirementUnavailabilityRecord(
                equipment_requirement_id=line.id,
                action=RESTORED,
                recorded_by_account_id=g.user_id,
                recorded_at=_now(),
            )
            session.add(record)
            session.flush()
            result = {
                "requirement": _serialize_requirement(line),
                "record": _serialize_record(record),
            }
        return jsonify(result)


def _locked_requirement(session: Session, requirement_id: int) -> EquipmentRequirement:
    """Lock the event, then stock pool and requirement, before validating a decision.

    Event-wide release locks the event before its pools, so use that order here too. The event
    row lock serializes lifecycle updates with both decisions: after any wait, re-read its
    current status, and hold the lock until the requirement and audit entry commit together.
    """

    event_id = session.scalar(
        select(EquipmentRequirement.event_request_id).where(
            EquipmentRequirement.id == requirement_id
        )
    )
    if event_id is None:
        abort(404, NOT_FOUND)
    event = session.scalar(
        select(EventRequest)
        .where(EventRequest.id == event_id)
        .execution_options(populate_existing=True)
        .with_for_update()
    )
    if event is None:
        abort(404, NOT_FOUND)
    if event.status not in ACTIVE_EVENT_STATUSES:
        abort(409, "Equipment availability can only change on an active event.")

    equipment_type_id = session.scalar(
        select(EquipmentRequirement.equipment_type_id).where(
            EquipmentRequirement.id == requirement_id
        )
    )
    if equipment_type_id is not None:
        equipment_type = session.scalar(
            select(EquipmentType).where(EquipmentType.id == equipment_type_id).with_for_update()
        )
        if equipment_type is None:
            abort(409, "The mapped equipment type is no longer available.")
    line = session.scalar(
        select(EquipmentRequirement)
        .where(EquipmentRequirement.id == requirement_id)
        .execution_options(populate_existing=True)
        .with_for_update()
    )
    if line is None:
        abort(404, NOT_FOUND)
    return line


def _reserved_quantity(session: Session, requirement_id: int) -> int:
    """Return currently held units, not historical reservation quantities."""

    return sum(
        remaining_quantity(reservation)
        for reservation in session.scalars(
            select(EquipmentReservation).where(
                EquipmentReservation.equipment_requirement_id == requirement_id
            )
        )
    )


def _mark_request(data: object) -> tuple[str, str | None]:
    """Accept only the required reason and optional alternative suggestion (AC1)."""

    if not isinstance(data, dict) or set(data) - {"reason", "alternative_suggestion"}:
        abort(400, "Provide a reason and an optional alternative suggestion only.")
    reason = _text(data.get("reason"), "Reason", required=True)
    suggestion = _text(data.get("alternative_suggestion"), "Alternative suggestion", required=False)
    assert reason is not None  # _text has already raised a 400 for a missing required reason.
    return reason, suggestion


def _text(value: object, label: str, *, required: bool) -> str | None:
    if value is None and not required:
        return None
    if not isinstance(value, str):
        abort(400, f"{label} must be text.")
    cleaned = value.strip()
    if required and not cleaned:
        abort(400, f"{label} is required.")
    if len(cleaned) > MAX_TEXT_LENGTH:
        abort(400, f"Keep {label.lower()} to {MAX_TEXT_LENGTH} characters or fewer.")
    return cleaned or None


def serialize_record(record: EquipmentRequirementUnavailabilityRecord) -> dict[str, Any]:
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


# Private spelling retained at the route call sites; other read models use the public serializer.
_serialize_record = serialize_record


def _serialize_requirement(line: EquipmentRequirement) -> dict[str, Any]:
    return {"id": line.id, "status": line.status}


def history_for(
    session: Session, requirement_id: int
) -> list[EquipmentRequirementUnavailabilityRecord]:
    """Read audit history oldest first for the coordinator and Technical Support views."""

    return list(
        session.scalars(
            select(EquipmentRequirementUnavailabilityRecord)
            .options(joinedload(EquipmentRequirementUnavailabilityRecord.recorded_by))
            .where(
                EquipmentRequirementUnavailabilityRecord.equipment_requirement_id == requirement_id
            )
            .order_by(EquipmentRequirementUnavailabilityRecord.id)
        )
    )
