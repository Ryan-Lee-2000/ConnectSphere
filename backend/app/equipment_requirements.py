"""Assigned Event Coordinator equipment-requirement planning routes for SPL-90."""

from datetime import date, datetime, timedelta
from typing import Any

from flask import Flask, abort, g, jsonify, request
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.authorization import require_roles
from app.coordinator_assignment import is_assigned_coordinator
from app.event_requests import SINGAPORE
from app.models import Account, AccountRole, EquipmentRequirement, EquipmentType, EventRequest, Role

PLANNING = "planning"
UNMAPPED = "unmapped"
REQUESTED = "requested"
REMOVED = "removed"
EDITABLE_STATUSES = frozenset({UNMAPPED, REQUESTED})
ESSENTIALITY_VALUES = frozenset({"undecided", "essential", "non_essential"})
MAX_EVENT_REQUEST_ID = 2**31 - 1
MAX_NOTE_LENGTH = 2_000


def register_equipment_requirement_routes(app: Flask) -> None:
    """Register the coordinator-only planning API for one event's equipment needs.

    This story records what the event needs. It deliberately does not reserve stock;
    later equipment-reservation stories use the saved status and catalogue reference.
    """

    @app.get("/api/event-requests/<int:event_request_id>/equipment-requirements")
    @require_roles(Role.EVENT_COORDINATOR)
    def get_equipment_requirements(event_request_id: int):
        with Session(app.extensions["engine"]) as session:
            event = _assigned_planning_event(session, event_request_id)
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
            event = _assigned_planning_event(session, event_request_id)
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
        data = _request_data()
        with Session(app.extensions["engine"]) as session, session.begin():
            event = _assigned_planning_event(session, event_request_id)
            line = _locked_editable_requirement(session, event, requirement_id)
            attributes = _update_attributes(session, event, line, data)
            for field, value in attributes.items():
                setattr(line, field, value)
            session.flush()
            session.refresh(line)
            result = {"requirement": _serialize_requirement(line)}
        return jsonify(result)

    @app.delete(
        "/api/event-requests/<int:event_request_id>/equipment-requirements/<int:requirement_id>"
    )
    @require_roles(Role.EVENT_COORDINATOR)
    def remove_equipment_requirement(event_request_id: int, requirement_id: int):
        _require_empty_body()
        with Session(app.extensions["engine"]) as session, session.begin():
            event = _assigned_planning_event(session, event_request_id)
            line = _locked_editable_requirement(session, event, requirement_id)
            line.status = REMOVED
            line.removed_by_account_id = g.user_id
            line.removed_at = datetime.now(SINGAPORE)
            result = dict(
                message="Equipment requirement removed.",
                requirement=_serialize_requirement(line),
            )
        return jsonify(result)


def _assigned_planning_event(session: Session, event_request_id: int) -> EventRequest:
    """Return the caller's assigned Planning event, or fail without leaking another event."""
    if event_request_id > MAX_EVENT_REQUEST_ID:
        abort(404, "Assigned event not found.")
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
        )
    )
    if event is None or not is_assigned_coordinator(session, event_request_id, g.user_id):
        abort(404, "Assigned event not found.")
    if event.status != PLANNING:
        abort(409, "Equipment requirements can only be planned for an event in Planning.")
    if event.proposed_date is None:
        abort(409, "Record the event date before planning equipment requirements.")
    return event


def _locked_editable_requirement(
    session: Session, event: EventRequest, requirement_id: int
) -> EquipmentRequirement:
    """Lock an editable line on the same boundary used by Technical Support reservations.

    A coordinator edit and a reservation must never both validate an old quantity.  Locking the
    requirement row first serialises those actions; locking its mapped catalogue type as well
    shares the stock-pool boundary used by the reservation route.  Once waiting work resumes,
    this function rechecks that the line is still genuinely editable.
    """

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
        abort(409, "Only unreserved equipment requirements can be changed or removed.")
    if line.equipment_type_id is not None:
        # Reservation transactions lock this exact row after the requirement row.  Keep the
        # order identical to prevent deadlocks while making catalogue remapping atomic.
        equipment_type = session.scalar(
            select(EquipmentType)
            .where(EquipmentType.id == line.equipment_type_id)
            .with_for_update()
        )
        if equipment_type is None:
            abort(409, "The mapped equipment type is no longer available.")
    return line


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
