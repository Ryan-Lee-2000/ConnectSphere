"""The planned return date of a reserved piece of equipment (SPL-100).

What this story owns, and what it leaves alone
----------------------------------------------
SPL-97 already stores a reservation's commitment as ``commitment_start_date`` ..
``commitment_end_date``, and already defaults the end to the requirement's required end date.
AC1's *default* therefore needs no new code — only proving. This story owns the one thing SPL-97
left out: **changing** that date, under the two rules AC1 and AC3 state, and recording who did it.

The date is deliberately not a new column. A second field would mean two answers to "when does
this commitment end", and SPL-95's availability reads ``commitment_end_date``. Calling the same
column the "planned return date" in the interface keeps one answer.

Why only the added days are checked (AC3)
-----------------------------------------
AC3 refuses a later date "if the reserved units would overcommit stock on any added day". Days the
reservation already occupied are, by definition, already feasible — they were checked when the
units were reserved. Re-checking them would refuse a harmless extension whenever the pool was
already tight, so only the days between the old end and the new one are examined.

Shortening is never refused for stock reasons: giving days back cannot overcommit anything. The
floor is the requirement's required end date (AC1), not the current planned date, so a date that
was extended can be pulled back to the required end again.

KNOWN FOLLOW-UP: stock here is ``equipment_types.total_stock``. SPL-96 adds ``unavailable_units``
and the notion of *usable* stock, on a separate branch. **When SPL-96 merges, the comparison in
``_added_day_conflict`` must switch from total stock to usable stock**, or a day can look feasible
while the units are physically out of service. Flagged in docs/tasks/SPL-100.md and on the PR.
"""

from datetime import date, datetime, timedelta
from typing import Any

from flask import Flask, abort, g, jsonify, make_response, request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.authorization import require_roles
from app.equipment_availability import commitment_days
from app.event_requests import SINGAPORE
from app.models import (
    Account,
    EquipmentRequirement,
    EquipmentReservation,
    EquipmentType,
    Role,
)

NOT_FOUND = "Reservation not found."
FIELD = "planned_return_date"
MAX_RESERVATION_ID = 2**31 - 1


def _now() -> datetime:
    """The single clock for this module, so tests can freeze it."""

    return datetime.now(SINGAPORE)


def register_equipment_return_date_routes(app: Flask) -> None:
    """Register the Technical Support planned-return-date route (AC4: no other role)."""

    @app.patch("/api/equipment-reservations/<int:reservation_id>/planned-return-date")
    @require_roles(Role.TECHNICAL_SUPPORT_STAFF)
    def set_planned_return_date(reservation_id: int):
        """Move a reservation's planned return date (AC1, AC3).

        Step 1. Validate the date before touching the database, so a bad request never opens a
                transaction.
        Step 2. Lock the equipment type's row. Two people extending into the same last unit must
                not both read it as free; the second waits here and then sees the first's result.
        Step 3. Refuse anything earlier than the requirement's required end date (AC1).
        Step 4. For an extension, check every *added* day against stock (AC3). Nothing is written
                on refusal, so the date, the quantity and the line's status are untouched.
        Step 5. Save the date with who moved it and when (AC3).
        """

        new_date = _requested_date()

        with Session(app.extensions["engine"]) as session:
            reservation = _reservation(session, reservation_id)
            # Locking the type, not the reservation: the thing being competed for is the shared
            # pool, and two different reservations of one type can collide on a day.
            equipment_type = session.scalar(
                select(EquipmentType)
                .where(EquipmentType.id == reservation.equipment_type_id)
                .with_for_update()
            )
            requirement = session.get(EquipmentRequirement, reservation.equipment_requirement_id)

            floor = requirement.required_end_date
            if floor is not None and new_date < floor:
                _refuse(
                    "The planned return date cannot be before the requirement's required end "
                    f"date ({floor.isoformat()})."
                )

            conflict_day = _added_day_conflict(
                session, reservation, equipment_type, new_date=new_date
            )
            if conflict_day is not None:
                abort(
                    409,
                    f"Extending to {new_date.isoformat()} would overcommit stock on "
                    f"{conflict_day.isoformat()}.",
                )

            reservation.commitment_end_date = new_date
            reservation.return_date_changed_by_account_id = g.user_id
            reservation.return_date_changed_at = _now()
            session.commit()
            session.refresh(reservation)
            changed_by = session.get(Account, reservation.return_date_changed_by_account_id)
            return jsonify(reservation=_serialize(reservation, changed_by))


def _added_day_conflict(
    session: Session,
    reservation: EquipmentReservation,
    equipment_type: EquipmentType,
    *,
    new_date: date,
) -> date | None:
    """The first added day on which this reservation would not fit, or None (AC3).

    Only days after the current planned return are considered: see this module's docstring.
    """

    if new_date <= reservation.commitment_end_date:
        return None
    added = commitment_days(reservation.commitment_end_date + timedelta(days=1), new_date)

    others = session.scalars(
        select(EquipmentReservation).where(
            EquipmentReservation.equipment_type_id == equipment_type.id,
            EquipmentReservation.id != reservation.id,
        )
    ).all()
    promised_by_day: dict[date, int] = {}
    for other in others:
        for day in commitment_days(other.commitment_start_date, other.commitment_end_date):
            promised_by_day[day] = promised_by_day.get(day, 0) + other.quantity

    for day in added:
        # KNOWN FOLLOW-UP (see module docstring): this is total stock, not usable stock. SPL-96
        # introduces the difference.
        if promised_by_day.get(day, 0) + reservation.quantity > equipment_type.total_stock:
            return day
    return None


def _refuse(message: str) -> None:
    """Stop with 400 and name the field, the same shape SPL-114 and SPL-116 use.

    The app's error handler only returns ``{"error": ...}``, so the response is built here to add
    ``"field"`` and let the page show the message beside the date input (AC1, TC-SPL-100-08).
    """

    abort(make_response(jsonify(error=message, field=FIELD), 400))


def _reservation(session: Session, reservation_id: int) -> EquipmentReservation:
    if reservation_id > MAX_RESERVATION_ID:
        abort(404, NOT_FOUND)
    reservation = session.get(EquipmentReservation, reservation_id)
    if reservation is None:
        abort(404, NOT_FOUND)
    return reservation


def _requested_date() -> date:
    """AC1: one ISO date, and nothing else in the request."""

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        _refuse("A JSON object is required.")
    unexpected = set(data) - {FIELD}
    if unexpected:
        _refuse(f"Unexpected field: {sorted(unexpected)[0]}.")
    value = data.get(FIELD)
    if not isinstance(value, str):
        _refuse("A planned return date is required.")
    try:
        return date.fromisoformat(value)
    except ValueError:
        _refuse("Use a calendar date in YYYY-MM-DD form.")


def _serialize(reservation: EquipmentReservation, changed_by: Account | None) -> dict[str, Any]:
    """The reservation as Technical Support sees it, with the date under its interface name."""

    return {
        "id": reservation.id,
        "equipment_requirement_id": reservation.equipment_requirement_id,
        "quantity": reservation.quantity,
        "commitment_start_date": reservation.commitment_start_date.isoformat(),
        # One column, two names: ``commitment_end_date`` in the schema because that is what it
        # means to availability, "planned return date" in the interface because that is what
        # Technical Support is recording.
        "planned_return_date": reservation.commitment_end_date.isoformat(),
        "return_date_changed_by": (
            {"id": changed_by.id, "display_name": changed_by.display_name} if changed_by else None
        ),
        "return_date_changed_at": (
            reservation.return_date_changed_at.isoformat()
            if reservation.return_date_changed_at
            else None
        ),
    }
