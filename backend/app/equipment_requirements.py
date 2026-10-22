"""Assigned Event Coordinator equipment-requirement planning routes (SPL-90, extended by SPL-91).

SPL-90 lets the assigned coordinator add, change and remove requirement lines that hold no stock.
SPL-91 extends the same change and removal routes to lines that *do* hold stock — Reserved,
Partially Reserved and Review Required — under one rule:

    A change to any field Technical Support reserved against releases every unit the line still
    holds, and sends the line back to Technical Support as Review Required.

Why release everything rather than adjust the reservation (AC2, AC4)
--------------------------------------------------------------------
AC4 says a change must "never leave a stale reservation". A reservation is Technical Support's
judgement that *these* units suit *this* need on *these* days. If the coordinator changes the
quantity, the dates, the equipment type or the technical notes, that judgement no longer holds,
and only Technical Support can make it again. Releasing every held unit is the one action that
guarantees no reservation is left describing values the line no longer has. This is "option A" of
the open question on AC2, built as the criterion is written; the question passed its stand-up
fallback unanswered.

One release path
----------------
Units are released only through SPL-98's ``_release_from_requirement``, so the release history
has a single owner across SPL-91, SPL-98 and any later story. That function expects the equipment
type and then the requirement line to be row-locked already, in that order; every stock-changing
route in the codebase takes locks in that order so they can never deadlock one another.
"""

from datetime import date, datetime, timedelta
from typing import Any

from flask import Flask, abort, g, jsonify, request
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.authorization import require_roles
from app.coordinator_assignment import is_assigned_coordinator
from app.equipment_releases import _held_quantity, _release_from_requirement
from app.equipment_requirement_unavailability import serialize_record
from app.event_requests import SINGAPORE
from app.models import (
    Account,
    AccountRole,
    EquipmentRequirement,
    EquipmentRequirementChange,
    EquipmentRequirementUnavailabilityRecord,
    EquipmentType,
    EventRequest,
    Role,
)

PLANNING = "planning"
UNMAPPED = "unmapped"
REQUESTED = "requested"
REMOVED = "removed"
RESERVED = "reserved"
PARTIALLY_RESERVED = "partially_reserved"
REVIEW_REQUIRED = "review_required"

# SPL-91: the statuses a line may hold stock in. A Review Required line counts because SPL-96
# flags a line *without* releasing its units, so it can still be holding them.
HOLDING_STATUSES = frozenset({RESERVED, PARTIALLY_RESERVED, REVIEW_REQUIRED})

# Lines the coordinator may change or remove: SPL-90's unreserved lines plus SPL-91's held ones.
# Removed lines are history, and Unavailable is left to the story that defines it (SPL-93).
EDITABLE_STATUSES = frozenset({UNMAPPED, REQUESTED}) | HOLDING_STATUSES

# AC1's fields. A change to any of these on a line holding stock releases it (AC2). Essentiality
# is deliberately absent: recording whether equipment is essential is SPL-90's, and it does not
# alter what Technical Support reserved.
REVIEWED_FIELDS = (
    "equipment_type_id",
    "quantity",
    "required_start_date",
    "required_end_date",
    "notes",
)
FIELD_LABELS = {
    "equipment_type_id": "equipment type",
    "quantity": "quantity",
    "required_start_date": "required start date",
    "required_end_date": "required end date",
    "notes": "technical notes",
}
# Stored on the SPL-98 release row, so Technical Support can see why the units came back.
REMOVAL_RELEASE_REASON = "Released because the assigned coordinator removed this requirement."
MAX_REQUIREMENT_ID = 2**31 - 1
ESSENTIALITY_VALUES = frozenset({"undecided", "essential", "non_essential"})
MAX_EVENT_REQUEST_ID = 2**31 - 1
MAX_NOTE_LENGTH = 2_000


def _now() -> datetime:
    """The single clock for this module's audit times, so tests can freeze it (SPL-91 AC4)."""

    return datetime.now(SINGAPORE)


def register_equipment_requirement_routes(app: Flask) -> None:
    """Register the coordinator-only planning API for one event's equipment needs.

    This story records what the event needs. It deliberately does not reserve stock;
    later equipment-reservation stories use the saved status and catalogue reference.
    """

    @app.get("/api/event-requests/<int:event_request_id>/equipment-requirements")
    @require_roles(Role.EVENT_COORDINATOR)
    def get_equipment_requirements(event_request_id: int):
        with Session(app.extensions["engine"]) as session:
            event = _assigned_planning_event(session, event_request_id, allow_confirmed=True)
            catalogue = session.scalars(
                select(EquipmentType).order_by(EquipmentType.name, EquipmentType.id)
            ).all()
            technical_support = _technical_support_accounts(session)
            active = [line for line in event.equipment_requirements if line.status != REMOVED]
            removed = [line for line in event.equipment_requirements if line.status == REMOVED]
            return jsonify(
                event=_serialize_event(event),
                requirements=[_serialize_requirement(line) for line in active],
                removed_requirements=[_serialize_requirement(line) for line in removed],
                equipment_types=[_serialize_equipment_type(item) for item in catalogue],
                technical_support_staff=[
                    _serialize_account(account) for account in technical_support
                ],
            )

    @app.post("/api/event-requests/<int:event_request_id>/equipment-requirements")
    @require_roles(Role.EVENT_COORDINATOR)
    def add_equipment_requirement(event_request_id: int):
        data = _request_data()
        with Session(app.extensions["engine"]) as session:
            event = _assigned_planning_event(session, event_request_id, lock=True)
            attributes = _new_attributes(session, event, data)
            line = EquipmentRequirement(**attributes)
            session.add(line)
            session.commit()
            session.refresh(line)
            return jsonify(requirement=_serialize_requirement(line)), 201

    @app.patch(
        "/api/event-requests/<int:event_request_id>/equipment-requirements/<int:requirement_id>"
    )
    @require_roles(Role.EVENT_COORDINATOR)
    def update_equipment_requirement(event_request_id: int, requirement_id: int):
        """Change a line, releasing its stock if the change invalidates the reservation.

        Step 1. Lock the equipment type, then the line (the codebase-wide stock lock order).
        Step 2. Validate every field *before* anything is released, so a bad request can never
                cost a line its reservation (TC-SPL-91-05). An abort here rolls back the whole
                transaction.
        Step 3. Work out what actually changed. Saving the values the line already has releases
                nothing and records nothing (AC2, "saving without changing anything").
        Step 4. If a reviewed field changed on a line holding stock, release every held unit
                through SPL-98 and mark the line Review Required with a reason (AC2).
        Step 5. Record the change with its old and new values, who and when (AC4).
        """

        data = _request_data()
        with Session(app.extensions["engine"]) as session, session.begin():
            event = _assigned_planning_event(session, event_request_id, lock=True)
            line, equipment_type = _locked_editable_requirement(session, event, requirement_id)
            attributes = _update_attributes(session, event, line, data)
            changed = _changed_values(line, attributes)
            released = 0
            if changed:
                released = _apply_change(session, line, equipment_type, attributes, changed)
            session.flush()
            session.refresh(line)
            result = {"requirement": _serialize_requirement(line), "released_quantity": released}
        return jsonify(result)

    @app.delete(
        "/api/event-requests/<int:event_request_id>/equipment-requirements/<int:requirement_id>"
    )
    @require_roles(Role.EVENT_COORDINATOR)
    def remove_equipment_requirement(event_request_id: int, requirement_id: int):
        """Remove a line, releasing whatever it still holds exactly once (AC3).

        "Released once" comes from the locks: a second removal waits on the same rows, then
        re-reads the line, finds it Removed and is refused, so it never reaches the release.
        """

        _require_empty_body()
        with Session(app.extensions["engine"]) as session, session.begin():
            event = _assigned_planning_event(session, event_request_id, lock=True)
            line, equipment_type = _locked_editable_requirement(session, event, requirement_id)
            previous_status = line.status
            now = _now()
            released = 0
            if equipment_type is not None:
                held = _held_quantity(session, line.id)
                if held:
                    _release_from_requirement(
                        session,
                        line,
                        equipment_type,
                        quantity=held,
                        reason=REMOVAL_RELEASE_REASON,
                        actor_id=g.user_id,
                        now=now,
                    )
                    released = held
            line.status = REMOVED
            line.removed_by_account_id = g.user_id
            line.removed_at = now
            _record_change(
                session,
                line,
                action="removed",
                old_values={"status": previous_status},
                new_values={"status": REMOVED},
                released=released,
                now=now,
            )
            result = dict(
                message="Equipment requirement removed.",
                requirement=_serialize_requirement(line),
                released_quantity=released,
            )
        return jsonify(result)

    @app.get(
        "/api/event-requests/<int:event_request_id>/equipment-requirements/"
        "<int:requirement_id>/history"
    )
    @require_roles(Role.EVENT_COORDINATOR)
    def get_equipment_requirement_history(event_request_id: int, requirement_id: int):
        """Every change and removal of one line, newest first (AC4).

        Unlike changing a line, reading its history does not require the event to be In
        planning: an audit trail is still worth reading after the event is Confirmed. It does
        require the caller to be the assigned coordinator, and anyone else gets the same 404 as
        an unknown line, so ids reveal nothing about other people's events.
        """

        with Session(app.extensions["engine"]) as session:
            if event_request_id > MAX_EVENT_REQUEST_ID or requirement_id > MAX_REQUIREMENT_ID:
                abort(404, "Equipment requirement not found.")
            event = session.get(EventRequest, event_request_id)
            if event is None or not is_assigned_coordinator(session, event.id, g.user_id):
                abort(404, "Equipment requirement not found.")
            line = session.scalar(
                select(EquipmentRequirement).where(
                    EquipmentRequirement.id == requirement_id,
                    EquipmentRequirement.event_request_id == event.id,
                )
            )
            if line is None:
                abort(404, "Equipment requirement not found.")
            entries = session.scalars(
                select(EquipmentRequirementChange)
                .where(EquipmentRequirementChange.equipment_requirement_id == line.id)
                .order_by(
                    EquipmentRequirementChange.changed_at.desc(),
                    EquipmentRequirementChange.id.desc(),
                )
            ).all()
            return jsonify(history=[_serialize_change(entry) for entry in entries])


def _assigned_planning_event(
    session: Session, event_request_id: int, *, lock: bool = False, allow_confirmed: bool = False
) -> EventRequest:
    """Return the caller's assigned Planning event, or fail without leaking another event.

    ``lock=True`` is for the coordinator's add, change and remove routes. It takes the event and
    assignment row locks first, the boundary SPL-85 confirmation and venue booking also use, so a
    write and a confirmation cannot both pass their Planning check: the second waits, then this
    function re-reads the event and refuses if it is no longer Planning or no longer assigned.
    Lock order stays event, then equipment type, then requirement line.
    """
    if event_request_id > MAX_EVENT_REQUEST_ID:
        abort(404, "Assigned event not found.")
    if lock:
        from app.exact_venue_bookings import lock_event

        lock_event(session, event_request_id, g.user_id)
    event = session.scalar(
        select(EventRequest)
        .where(EventRequest.id == event_request_id)
        .options(
            selectinload(EventRequest.equipment_requirements).joinedload(
                EquipmentRequirement.catalogue_type
            ),
            selectinload(EventRequest.equipment_requirements).joinedload(
                EquipmentRequirement.consulted_technical_support
            ),
            selectinload(EventRequest.equipment_requirements).joinedload(
                EquipmentRequirement.essentiality_decider
            ),
            selectinload(EventRequest.equipment_requirements)
            .selectinload(EquipmentRequirement.unavailability_records)
            .joinedload(EquipmentRequirementUnavailabilityRecord.recorded_by),
        )
    )
    if event is None or not is_assigned_coordinator(session, event_request_id, g.user_id):
        abort(404, "Assigned event not found.")
    if event.status != PLANNING and not (allow_confirmed and event.status == "confirmed"):
        abort(409, "Equipment requirements can only be planned for an event in Planning.")
    if event.proposed_date is None:
        abort(409, "Record the event date before planning equipment requirements.")
    return event


def _locked_editable_requirement(
    session: Session, event: EventRequest, requirement_id: int
) -> tuple[EquipmentRequirement, EquipmentType | None]:
    """Lock an editable line on the same boundary used by Technical Support reservations.

    A coordinator edit and stock-mutation workflow must never validate an old quantity. All of
    them acquire a mapped catalogue type before its requirement line, then re-read the line after
    any wait. This avoids a cycle with release/unavailability while retaining the edit guard.

    Returns the locked type as well, because SPL-91 hands it to SPL-98's release operation, which
    requires the caller to hold that lock already. An unmapped line has no type and holds no stock.
    """

    if requirement_id > MAX_REQUIREMENT_ID:
        abort(404, "Equipment requirement not found.")
    equipment_type: EquipmentType | None = None
    equipment_type_id = session.scalar(
        select(EquipmentRequirement.equipment_type_id).where(
            EquipmentRequirement.id == requirement_id,
            EquipmentRequirement.event_request_id == event.id,
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
        .where(
            EquipmentRequirement.id == requirement_id,
            EquipmentRequirement.event_request_id == event.id,
        )
        # ``event.equipment_requirements`` was preloaded for ownership checks.  If this query
        # waited behind a reservation, overwrite that cached line with PostgreSQL's current
        # status before deciding whether the coordinator may still edit it.
        .execution_options(populate_existing=True)
        .with_for_update()
    )
    if line is None:
        abort(404, "Equipment requirement not found.")
    if line.status not in EDITABLE_STATUSES:
        # Reached by a second removal after the first, or a change racing a removal: the waiting
        # request re-reads the line here, finds it gone, and stops before any release (AC3, AC4).
        abort(409, "This equipment requirement can no longer be changed or removed.")
    if line.equipment_type_id != equipment_type_id:
        abort(409, "This equipment requirement changed while its edit was being prepared.")
    return line, equipment_type


def _changed_values(
    line: EquipmentRequirement, attributes: dict[str, Any]
) -> dict[str, tuple[Any, Any]]:
    """The fields whose value actually differs, as (old, new).

    AC2 says "saving without changing anything releases nothing". That is about the values, not
    about the request: resending a line's current quantity is not a change, so it must not cost
    the line its reservation or leave a history entry.
    """

    return {
        field: (getattr(line, field), value)
        for field, value in attributes.items()
        if getattr(line, field) != value
    }


def _apply_change(
    session: Session,
    line: EquipmentRequirement,
    equipment_type: EquipmentType | None,
    attributes: dict[str, Any],
    changed: dict[str, tuple[Any, Any]],
) -> int:
    """Apply a validated change, releasing held stock if a reviewed field moved (AC2, AC4).

    Returns how many units were released, which the response reports and the history records.
    """

    now = _now()
    previous_status = line.status
    reviewed = [field for field in REVIEWED_FIELDS if field in changed]
    held = _held_quantity(session, line.id) if reviewed and equipment_type is not None else 0
    # A line goes back to Technical Support when a reviewed field changes and either it still
    # holds units, or it was already reserved or flagged (so a reviewer's earlier judgement on it
    # no longer stands). A Requested line with nothing held keeps SPL-90's behaviour exactly.
    needs_review = bool(reviewed) and (held > 0 or previous_status in HOLDING_STATUSES)
    description = _describe_change(session, reviewed, changed) if needs_review else ""

    released = 0
    if needs_review and held:
        _release_from_requirement(
            session,
            line,
            equipment_type,
            quantity=held,
            reason=f"Released because the assigned coordinator changed the {description}.",
            actor_id=g.user_id,
            now=now,
        )
        released = held

    old_values = {field: _json_value(old) for field, (old, _new) in changed.items()}
    new_values = {field: _json_value(new) for field, (_old, new) in changed.items()}
    for field, value in attributes.items():
        setattr(line, field, value)

    if needs_review:
        line.status = REVIEW_REQUIRED
        line.review_reason = f"The assigned coordinator changed the {description}. " + (
            f"The {released} reserved unit(s) were released for Technical Support to review."
            if released
            else "Technical Support must review this line again."
        )
        line.review_flagged_at = now
        if previous_status != REVIEW_REQUIRED:
            old_values["status"] = previous_status
            new_values["status"] = REVIEW_REQUIRED

    _record_change(
        session,
        line,
        action="changed",
        old_values=old_values,
        new_values=new_values,
        released=released,
        now=now,
    )
    return released


def _describe_change(
    session: Session, reviewed: list[str], changed: dict[str, tuple[Any, Any]]
) -> str:
    """A short, human description of the reviewed fields that moved, for the reviewer.

    Notes are named but not quoted, because a note can be long and the full text is in the
    history; every other field shows its old and new value.
    """

    parts = []
    for field in reviewed:
        old, new = changed[field]
        label = FIELD_LABELS[field]
        if field == "notes":
            parts.append(label)
        elif field == "equipment_type_id":
            parts.append(f"{label} ({_type_name(session, old)} → {_type_name(session, new)})")
        else:
            parts.append(f"{label} ({_json_value(old)} → {_json_value(new)})")
    if len(parts) == 1:
        return parts[0]
    return ", ".join(parts[:-1]) + " and " + parts[-1]


def _type_name(session: Session, equipment_type_id: int | None) -> str:
    if equipment_type_id is None:
        return "no catalogue type"
    item = session.get(EquipmentType, equipment_type_id)
    return item.name if item else f"type {equipment_type_id}"


def _record_change(
    session: Session,
    line: EquipmentRequirement,
    *,
    action: str,
    old_values: dict[str, Any],
    new_values: dict[str, Any],
    released: int,
    now: datetime,
) -> None:
    """Write one history row: what changed, from what to what, who, when, and what it released."""

    session.add(
        EquipmentRequirementChange(
            equipment_requirement_id=line.id,
            action=action,
            old_values=old_values,
            new_values=new_values,
            released_quantity=released,
            changed_by_account_id=g.user_id,
            changed_at=now,
        )
    )


def _json_value(value: Any) -> Any:
    """Make a model value safe to store in the JSON history and to show in a reason."""

    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def _serialize_change(entry: EquipmentRequirementChange) -> dict[str, Any]:
    return {
        "id": entry.id,
        "action": entry.action,
        "old_values": entry.old_values,
        "new_values": entry.new_values,
        "released_quantity": entry.released_quantity,
        "changed_by": _serialize_account(entry.changed_by) if entry.changed_by else None,
        "changed_at": entry.changed_at.isoformat() if entry.changed_at else None,
    }


def _new_attributes(session: Session, event: EventRequest, data: dict[str, Any]) -> dict[str, Any]:
    """Build a new coordinator-added catalogue requirement from validated request data."""
    allowed = {
        "equipment_type_id",
        "quantity",
        "notes",
        "required_start_date",
        "required_end_date",
        "essentiality",
        "consulted_technical_support_account_id",
        "essentiality_decision_note",
    }
    _reject_unexpected(data, allowed)
    equipment_type = _catalogue_type(session, data.get("equipment_type_id"))
    attributes = {
        "event_request_id": event.id,
        # For a coordinator-added line, the captured wording is the selected catalogue label.
        "equipment_type": equipment_type.name,
        "equipment_type_id": equipment_type.id,
        "quantity": _positive_quantity(data.get("quantity")),
        "notes": _optional_text(data.get("notes"), "Technical notes"),
        "required_start_date": _required_event_date(
            event, data.get("required_start_date"), "start"
        ),
        "required_end_date": _required_event_date(event, data.get("required_end_date"), "end"),
        "status": REQUESTED,
        "essentiality": "undecided",
    }
    _validate_date_order(attributes["required_start_date"], attributes["required_end_date"])
    attributes.update(_essentiality_attributes(session, "undecided", data))
    return attributes


def _update_attributes(
    session: Session, event: EventRequest, line: EquipmentRequirement, data: dict[str, Any]
) -> dict[str, Any]:
    """Validate an edit or map an organiser's retained free-text request to the catalogue."""
    allowed = {
        "equipment_type_id",
        "quantity",
        "notes",
        "required_start_date",
        "required_end_date",
        "essentiality",
        "consulted_technical_support_account_id",
        "essentiality_decision_note",
    }
    _reject_unexpected(data, allowed)
    if not data:
        abort(400, "Provide at least one equipment requirement field.")
    attributes: dict[str, Any] = {}
    if "equipment_type_id" in data:
        equipment_type = _catalogue_type(session, data["equipment_type_id"])
        attributes["equipment_type_id"] = equipment_type.id
        # Mapping retains ``equipment_type`` as the original organiser wording.
        if line.status == UNMAPPED:
            attributes["status"] = REQUESTED
    if "quantity" in data:
        attributes["quantity"] = _positive_quantity(data["quantity"])
    if "notes" in data:
        attributes["notes"] = _optional_text(data["notes"], "Technical notes")
    start = (
        _required_event_date(event, data["required_start_date"], "start")
        if "required_start_date" in data
        else line.required_start_date
    )
    end = (
        _required_event_date(event, data["required_end_date"], "end")
        if "required_end_date" in data
        else line.required_end_date
    )
    if start is None or end is None:
        abort(400, "Required start and end dates are required.")
    _validate_date_order(start, end)
    if "required_start_date" in data:
        attributes["required_start_date"] = start
    if "required_end_date" in data:
        attributes["required_end_date"] = end
    if "essentiality" in data:
        attributes.update(_essentiality_attributes(session, line.essentiality, data))
    elif {"consulted_technical_support_account_id", "essentiality_decision_note"} & set(data):
        abort(400, "Choose Essential or Non-essential before recording the consultation.")
    return attributes


def _essentiality_attributes(
    session: Session, current: str, data: dict[str, Any]
) -> dict[str, Any]:
    """Record a decision only after Technical Support consultation is supplied.

    The browser may name a staff account, but this function verifies the account has the
    trusted Technical Support role before it becomes part of the audit record.
    """
    selected = data.get("essentiality", "undecided")
    if selected not in ESSENTIALITY_VALUES:
        abort(400, "Choose Essential, Non-essential, or Undecided.")
    if selected == current:
        return {"essentiality": selected}
    if current != "undecided":
        abort(409, "A recorded essentiality decision cannot be changed in this workflow.")
    if selected == "undecided":
        return {"essentiality": selected}
    account = _technical_support_account(
        session, data.get("consulted_technical_support_account_id")
    )
    note = _required_text(data.get("essentiality_decision_note"), "Decision note")
    return {
        "essentiality": selected,
        "consulted_technical_support_account_id": account.id,
        "essentiality_decision_note": note,
        "essentiality_decided_by_account_id": g.user_id,
        "essentiality_decided_at": datetime.now(SINGAPORE),
    }


def _catalogue_type(session: Session, value: Any) -> EquipmentType:
    """Load an existing shared catalogue item; free-text values cannot create inventory."""
    if isinstance(value, bool) or not isinstance(value, int):
        abort(400, "Choose an equipment type from the catalogue.")
    item = session.get(EquipmentType, value)
    if item is None:
        abort(400, "Choose an equipment type from the catalogue.")
    return item


def _technical_support_account(session: Session, value: Any) -> Account:
    """Load an active Technical Support account for an essentiality consultation record."""
    if not isinstance(value, str):
        abort(400, "Choose the consulted Technical Support Staff member.")
    account = session.scalar(
        select(Account)
        .join(AccountRole, AccountRole.account_id == Account.id)
        .where(
            Account.id == value,
            AccountRole.role == Role.TECHNICAL_SUPPORT_STAFF.value,
            Account.is_active.is_(True),
        )
    )
    if account is None:
        abort(400, "Choose the consulted Technical Support Staff member.")
    return account


def _technical_support_accounts(session: Session) -> list[Account]:
    """List valid consultation choices from server-owned role assignments."""
    return list(
        session.scalars(
            select(Account)
            .join(AccountRole, AccountRole.account_id == Account.id)
            .where(
                AccountRole.role == Role.TECHNICAL_SUPPORT_STAFF.value,
                Account.is_active.is_(True),
            )
            .order_by(Account.display_name, Account.id)
        )
    )


def _required_event_date(event: EventRequest, value: Any, label: str) -> date:
    """Require a valid date inside the event period.

    The current event model has one recorded date, so both boundaries must equal that date.
    This keeps the stored contract ready for a later multi-day event model.
    """
    if not isinstance(value, str):
        abort(400, f"Required {label} date is required.")
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        abort(400, f"Required {label} date must be a valid date.")
    if parsed != event.proposed_date:
        abort(400, "Equipment requirement dates must fall within this event's recorded date.")
    return parsed


def _validate_date_order(start: date, end: date) -> None:
    if end < start:
        abort(400, "Required end date cannot be before the required start date.")


def _positive_quantity(value: Any) -> int:
    """Accept only positive whole units; booleans and numeric-looking text are invalid."""
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        abort(400, "Quantity must be a positive whole number.")
    return value


def _request_data() -> dict[str, Any]:
    """Read one JSON object and reject other request shapes early."""
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        abort(400, "A JSON object is required.")
    return data


def _require_empty_body() -> None:
    """Keep remove actions server-owned; the client cannot choose audit fields or status."""
    if request.content_length in (None, 0):
        return
    if not request.is_json or request.get_json(silent=True) != {}:
        abort(400, "This action does not accept request fields.")


def _reject_unexpected(data: dict[str, Any], allowed: set[str]) -> None:
    """Reject undeclared fields so the browser cannot smuggle future workflow state."""
    unexpected = set(data) - allowed
    if unexpected:
        abort(400, f"Unexpected equipment requirement field: {sorted(unexpected)[0]}.")


def _required_text(value: Any, label: str) -> str:
    """Return a short required text value after trimming surrounding whitespace."""
    if not isinstance(value, str) or not value.strip():
        abort(400, f"{label} is required.")
    cleaned = value.strip()
    if len(cleaned) > MAX_NOTE_LENGTH:
        abort(400, f"Keep {label.lower()} to {MAX_NOTE_LENGTH} characters or fewer.")
    return cleaned


def _optional_text(value: Any, label: str) -> str | None:
    """Return optional text as clean content or None, with a shared length limit."""
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        abort(400, f"{label} must be text.")
    cleaned = value.strip()
    if len(cleaned) > MAX_NOTE_LENGTH:
        abort(400, f"Keep {label.lower()} to {MAX_NOTE_LENGTH} characters or fewer.")
    return cleaned or None


def _serialize_event(event: EventRequest) -> dict[str, Any]:
    """Produce the small event summary the planning page needs."""
    return {
        "id": event.id,
        "name": event.name,
        "proposed_date": event.proposed_date.isoformat() if event.proposed_date else None,
        "status": event.status,
    }


def _serialize_requirement(line: EquipmentRequirement) -> dict[str, Any]:
    """Produce one planning-card payload including operational dates and decision audit data."""
    collection_date = (
        line.required_start_date - timedelta(days=1) if line.required_start_date else None
    )
    return {
        "id": line.id,
        "organiser_equipment_text": line.equipment_type,
        "equipment_type": _serialize_equipment_type(line.catalogue_type)
        if line.catalogue_type
        else None,
        "quantity": line.quantity,
        "notes": line.notes,
        "required_start_date": (
            line.required_start_date.isoformat() if line.required_start_date else None
        ),
        "required_end_date": line.required_end_date.isoformat() if line.required_end_date else None,
        "collection_date": collection_date.isoformat() if collection_date else None,
        "planned_return_date": (
            line.required_end_date.isoformat() if line.required_end_date else None
        ),
        "status": line.status,
        "essentiality": line.essentiality,
        "consulted_technical_support": _serialize_account(line.consulted_technical_support)
        if line.consulted_technical_support
        else None,
        "essentiality_decision_note": line.essentiality_decision_note,
        "essentiality_decided_at": line.essentiality_decided_at.isoformat()
        if line.essentiality_decided_at
        else None,
        "essentiality_decided_by": _serialize_account(line.essentiality_decider)
        if line.essentiality_decider
        else None,
        "removed_at": line.removed_at.isoformat() if line.removed_at else None,
        # SPL-96 AC4: the assigned coordinator sees the Review Required flag and its reason on
        # their own event's affected line. The flag itself is ``status``; these explain it.
        # Null on any line that is not flagged.
        "review_reason": line.review_reason,
        "review_flagged_at": (
            line.review_flagged_at.isoformat() if line.review_flagged_at else None
        ),
        # SPL-93 AC2/AC3: the assigned coordinator sees the current status together with the
        # original reason, optional suggestion and immutable actor/time history on this line.
        "unavailability_history": [
            serialize_record(record) for record in line.unavailability_records
        ],
    }


def _serialize_equipment_type(item: EquipmentType) -> dict[str, Any]:
    """Expose a read-only catalogue choice without granting stock-management authority."""
    return {
        "id": item.id,
        "name": item.name,
        "description": item.description,
        "location": item.location,
        "total_stock": item.total_stock,
    }


def _serialize_account(account: Account) -> dict[str, str]:
    """Expose only the identifier and display name needed for a visible audit/selector."""
    return {"id": account.id, "name": account.display_name}
