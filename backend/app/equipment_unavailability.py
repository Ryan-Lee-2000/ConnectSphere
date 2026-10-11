"""Technical Support records units of equipment as unavailable, and restores them (SPL-96).

What this story owns
--------------------
All six acceptance criteria: record and restore within bounds (AC1), every later availability
check *and reservation* using the reduced stock (AC2), flagging the reservations that no longer
fit (AC3), showing that flag and its reason where the story says (AC4), leaving flags alone on a
restore (AC5), and Technical Support only (AC6).

This module reads SPL-97's reservations in order to flag them, but never alters one: no
reservation's quantity is changed and none is deleted. The only rows it writes are its own
history, the equipment type's running total, and the flag plus reason on a requirement line.

Why a running total plus a history, rather than a ledger alone
--------------------------------------------------------------
AC1 states a bound ("never above total stock or below zero"). A bound is only trustworthy if the
database enforces it, and a database can only check a bound against a stored number, so the
current total lives on ``EquipmentType.unavailable_units`` behind a CHECK constraint. AC1 also
asks for the reason, who and when on every change, so each change is additionally written to
``equipment_unavailability_records``. The total is the answer; the records are the audit trail.

Why unavailability has no dates
-------------------------------
The story's own assumption: units stay unavailable from when they are recorded until they are
restored, with no maintenance schedule. So one figure applies to every day SPL-95 assesses, which
is why ``unavailable_by_day`` is filled with the same number for each day of a commitment.
"""

from datetime import date, datetime
from typing import Any

from flask import Flask, abort, g, jsonify, request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.authorization import require_roles
from app.equipment_availability import commitment_days
from app.event_requests import SINGAPORE
from app.models import (
    EquipmentRequirement,
    EquipmentReservation,
    EquipmentType,
    EquipmentUnavailabilityRecord,
    Role,
)

MARKED = "marked_unavailable"
RESTORED = "restored"

# SPL-96 AC3. The status a line takes when its reservations no longer fit the usable pool. SPL-97
# owns clearing it again (revalidate-reservation); until this story, nothing ever set it.
REVIEW_REQUIRED = "review_required"
REMOVED = "removed"

NOT_FOUND = "Equipment type not found."
ALLOWED_FIELDS = {"quantity", "reason"}


def _now() -> datetime:
    """The single clock for this module, so tests can freeze it."""

    return datetime.now(SINGAPORE)


def register_equipment_unavailability_routes(app: Flask) -> None:
    """Register the SPL-96 unavailable-unit routes, all Technical Support only (AC6)."""

    @app.post("/api/equipment-types/<int:equipment_type_id>/unavailable-units")
    @require_roles(Role.TECHNICAL_SUPPORT_STAFF)
    def mark_units_unavailable(equipment_type_id: int):
        """Take units out of service (AC1)."""

        return _apply_change(app, equipment_type_id, action=MARKED)

    @app.post("/api/equipment-types/<int:equipment_type_id>/restored-units")
    @require_roles(Role.TECHNICAL_SUPPORT_STAFF)
    def restore_units(equipment_type_id: int):
        """Put units back into service (AC1). This clears no SPL-97 flag by itself (AC5)."""

        return _apply_change(app, equipment_type_id, action=RESTORED)

    @app.get("/api/equipment-types/<int:equipment_type_id>/unavailability")
    @require_roles(Role.TECHNICAL_SUPPORT_STAFF)
    def show_unavailability(equipment_type_id: int):
        """The current total and the history behind it, newest first (AC1)."""

        with Session(app.extensions["engine"]) as session:
            equipment_type = session.get(EquipmentType, equipment_type_id)
            if equipment_type is None:
                abort(404, NOT_FOUND)
            entries = session.scalars(
                select(EquipmentUnavailabilityRecord)
                .where(EquipmentUnavailabilityRecord.equipment_type_id == equipment_type_id)
                .order_by(EquipmentUnavailabilityRecord.id.desc())
            ).all()
            return jsonify(
                equipment_type=serialize_stock(equipment_type),
                history=[_serialize_record(entry) for entry in entries],
            )


def _apply_change(app: Flask, equipment_type_id: int, *, action: str) -> tuple | Any:
    """Move the unavailable total by a validated amount, and record why.

    Step 1. Validate the request before touching the database, so a bad request never opens a
            transaction.
    Step 2. Lock the equipment type's row. Two members of Technical Support recording at the same
            moment must not be able to read the same total and both add to it; the second waits
            here and then reads the first one's result (the invariant half of TC-SPL-96-07).
    Step 3. Check the AC1 bounds against the locked figures and refuse with a message naming the
            real room left, rather than letting the CHECK constraint surface as a 500.
    Step 4. Write the new total and the history entry in the same transaction, so the audit trail
            can never disagree with the number it explains.
    """

    # Checked before anything else: below, an unrecognised action would silently be treated as a
    # restore, which is the one wrong answer that would look like a working route.
    if action not in (MARKED, RESTORED):  # pragma: no cover - defensive
        raise ValueError(f"Unknown unavailability action: {action}")

    quantity, reason = _change_request()

    with Session(app.extensions["engine"]) as session:
        equipment_type = session.scalar(
            select(EquipmentType).where(EquipmentType.id == equipment_type_id).with_for_update()
        )
        if equipment_type is None:
            abort(404, NOT_FOUND)

        signed = quantity if action == MARKED else -quantity
        new_total = equipment_type.unavailable_units + signed
        _require_within_bounds(equipment_type, new_total, quantity=quantity)

        equipment_type.unavailable_units = new_total

        # Step 5 (AC3, AC5). Taking units out of service can leave less usable stock than is
        # already promised; putting units back never can, so only a marking flags anything. A
        # restore deliberately clears nothing: AC5 says Technical Support revalidates each
        # flagged line through SPL-97's route rather than a restore doing it silently.
        flagged = (
            _flag_shortfall_lines(session, equipment_type, reason, _now())
            if action == MARKED
            else []
        )

        record = EquipmentUnavailabilityRecord(
            equipment_type_id=equipment_type.id,
            action=action,
            quantity=quantity,
            reason=reason,
            recorded_by_account_id=g.user_id,
            recorded_at=_now(),
        )
        session.add(record)
        session.commit()
        session.refresh(record)
        return (
            jsonify(
                equipment_type=serialize_stock(equipment_type),
                record=_serialize_record(record),
                # AC3: which lines this change put in front of Technical Support, so the caller
                # learns the consequence of what they just did rather than having to go looking.
                flagged_requirement_ids=flagged,
            ),
            201,
        )


def _flag_shortfall_lines(
    session: Session, equipment_type: EquipmentType, reason: str, now: datetime
) -> list[int]:
    """AC3. Mark Review Required every line whose reservations now exceed usable stock.

    "Contributing to that shortfall" is read per day: a day is short when the units promised on
    it exceed what is usable, and every reservation that spans such a day is contributing, because
    any one of them could be the one released to resolve it. The story is explicit that the system
    does not choose a winner, so all of them are flagged and none is cancelled.

    Quantities and history are untouched (AC3): no reservation is altered or deleted. Only the
    requirement line's status and the explanation of it change.
    """

    usable = usable_stock(equipment_type)
    reservations = session.scalars(
        select(EquipmentReservation).where(
            EquipmentReservation.equipment_type_id == equipment_type.id
        )
    ).all()
    if not reservations:
        return []

    promised_by_day: dict[date, int] = {}
    for reservation in reservations:
        for day in commitment_days(
            reservation.commitment_start_date, reservation.commitment_end_date
        ):
            promised_by_day[day] = promised_by_day.get(day, 0) + reservation.quantity
    short_days = {day for day, promised in promised_by_day.items() if promised > usable}
    if not short_days:
        return []

    # Several reservations can belong to one requirement line, so the line is flagged once.
    flagged: dict[int, EquipmentRequirement] = {}
    for reservation in reservations:
        days = set(
            commitment_days(reservation.commitment_start_date, reservation.commitment_end_date)
        )
        if not days & short_days:
            continue
        line = session.get(EquipmentRequirement, reservation.equipment_requirement_id)
        if line is None or line.status == REMOVED:  # pragma: no cover - defensive
            continue
        flagged[line.id] = line

    for line in flagged.values():
        line.status = REVIEW_REQUIRED
        line.review_reason = reason
        line.review_flagged_at = now
    return sorted(flagged)


def _require_within_bounds(equipment_type: EquipmentType, new_total: int, *, quantity: int) -> None:
    """AC1: the unavailable total can never exceed total stock or fall below zero."""

    if new_total < 0:
        abort(
            400,
            f"Only {equipment_type.unavailable_units} unit(s) are marked unavailable, "
            f"so {quantity} cannot be restored.",
        )
    if new_total > equipment_type.total_stock:
        room = equipment_type.total_stock - equipment_type.unavailable_units
        abort(
            400,
            f"Only {room} of {equipment_type.total_stock} unit(s) are still usable, "
            f"so {quantity} cannot be marked unavailable.",
        )


def _change_request() -> tuple[int, str]:
    """Read and validate ``quantity`` and ``reason``, and nothing else (AC1)."""

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        abort(400, "A JSON object is required.")
    unexpected = set(data) - ALLOWED_FIELDS
    if unexpected:
        abort(400, f"Unexpected field: {sorted(unexpected)[0]}.")

    quantity = data.get("quantity")
    # ``isinstance(True, int)`` is True in Python, so booleans are excluded explicitly: True is
    # not a quantity of one.
    if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity < 1:
        abort(400, "Quantity must be a whole number of one or more.")

    reason = data.get("reason")
    if not isinstance(reason, str) or not reason.strip():
        abort(400, "A reason is required.")
    return quantity, reason.strip()


def serialize_stock(equipment_type: EquipmentType) -> dict[str, Any]:
    """The three stock figures, with the usable one worked out once and in one place.

    SPL-94's own response shape is deliberately left alone, so this story does not change what
    the catalogue routes return.
    """

    return {
        "id": equipment_type.id,
        "name": equipment_type.name,
        "total_stock": equipment_type.total_stock,
        "unavailable_units": equipment_type.unavailable_units,
        "usable_stock": usable_stock(equipment_type),
    }


def usable_stock(equipment_type: EquipmentType) -> int:
    """Physical stock less the units currently out of service (AC2)."""

    return max(0, equipment_type.total_stock - equipment_type.unavailable_units)


def _serialize_record(record: EquipmentUnavailabilityRecord) -> dict[str, Any]:
    return {
        "id": record.id,
        "action": record.action,
        "quantity": record.quantity,
        "reason": record.reason,
        "recorded_by": record.recorded_by_account_id,
        "recorded_at": record.recorded_at.isoformat() if record.recorded_at else None,
    }
