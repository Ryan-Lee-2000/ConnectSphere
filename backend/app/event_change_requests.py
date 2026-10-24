"""An organiser asks to change an event they already submitted (SPL-111, CS-E18-S1).

What this module does
---------------------
The Event Organiser who owns a submitted event can send a change request: one or more items, each
naming a field, the new value they want and why. The request is stored as Pending and the event's
assigned coordinator can read it and is notified (SPL-103). Item decisions are handled by
SPL-112 in event_change_decisions.py.

How a submission is checked (``POST /api/event-requests/<id>/change-requests``), in order
-----------------------------------------------------------------------------------------
1. Role: Event Organiser only -> 403; no session -> 401.
2. Own event: someone else's event, a draft or an unknown id all get the same 404, so ids cannot
   be probed. The organiser is always the signed-in account, never a submitted value.
3. Body: only ``items``; at least one item; each item exactly field, requested_value and reason;
   the field one the organiser may ask to change, named once; the value valid for that field and
   the reason not blank -> otherwise 400, and nothing is saved (AC2).
4. Status: the event is Under review, In planning or Confirmed -> otherwise 409 (AC1).
5. No Pending request already exists for the event -> otherwise 409 (AC4).
6. Save the request as Pending with all its items in one transaction (AC2, AC3).

Steps 2 and 4-6 run while holding a lock on the event's row, so two simultaneous submissions are
handled one after the other and the second sees the first one Pending. The database's partial
unique index is the backstop if that ever fails.

``GET /api/event-requests/<id>/change-requests`` returns the event's change requests with all of
their items to the owning organiser (AC5) and to the event's assigned coordinator (AC3).
"""

from typing import Any

from flask import Flask, abort, g, jsonify
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app import registration_settings as settings
from app.authorization import require_roles
from app.coordinator_assignment import MAX_EVENT_REQUEST_ID, is_assigned_coordinator
from app.event_requests import _iso_date, _iso_time, _positive_integer, _string_list
from app.models import (
    EquipmentRequirement,
    EquipmentType,
    EventChangeRequest,
    EventChangeRequestItem,
    EventRequest,
    Role,
)
from app.notifications import add_change_request_submitted_notice
from app.validation import request_json, required_text

PENDING = "pending"
# AC1. [PROPOSE] by the team, not customer-confirmed (see the story's notes).
CHANGEABLE_STATUSES = frozenset({"under_review", "planning", "confirmed"})
NOT_FOUND = "Event not found."
NOT_AVAILABLE = (
    "A change request can only be made while the event is under review, in planning or confirmed."
)
ALREADY_PENDING = "This event already has a pending change request. Wait until it is Closed."
ONLY_ITEMS = "A change request accepts only items."
ONLY_ITEM_KEYS = "Each item accepts only field, requested_value and reason."
MAX_TEXT_LENGTH = 2_000
MAX_REASON_LENGTH = 1_000
MAX_ITEMS = 100

# The event details an organiser may ask to change, with the label used in error messages.
# Status, ownership, registration settings, venue and equipment have their own workflows.
FIELDS = {
    "name": "Event name",
    "purpose": "Purpose",
    "description": "Description",
    "proposed_date": "Proposed date",
    "start_time": "Start time",
    "end_time": "End time",
    "expected_attendance": "Expected attendance",
    "preferred_room_layout": "Preferred room layout",
    "required_facilities": "Required facilities",
    "accessibility_needs": "Accessibility needs",
    "venue_notes": "Venue notes",
}
_TEXT_FIELDS = {"name", "purpose", "description", "preferred_room_layout", "venue_notes"}
_LIST_FIELDS = {"required_facilities", "accessibility_needs"}


def register_event_change_request_routes(app: Flask) -> None:
    @app.get("/api/event-requests/<int:event_request_id>/change-requests/equipment-options")
    @require_roles(Role.EVENT_ORGANISER)
    def equipment_change_options(event_request_id: int):
        with Session(app.extensions["engine"]) as session:
            event = _own_event(session, event_request_id)
            if event.status not in CHANGEABLE_STATUSES:
                abort(409, NOT_AVAILABLE)
            lines = session.scalars(
                select(EquipmentRequirement)
                .where(
                    EquipmentRequirement.event_request_id == event.id,
                    EquipmentRequirement.status != "removed",
                )
                .order_by(EquipmentRequirement.id)
            ).all()
            types = session.scalars(select(EquipmentType).order_by(EquipmentType.name)).all()
            return jsonify(
                equipment_requirements=[_equipment_snapshot(line) for line in lines],
                equipment_types=[{"id": item.id, "name": item.name} for item in types],
            )

    @app.post("/api/event-requests/<int:event_request_id>/change-requests")
    @require_roles(Role.EVENT_ORGANISER)
    def submit_change_request(event_request_id: int):
        """SPL-111: the owning organiser submits a change request for their event."""

        # Step 3 runs before the database is touched, so a malformed request never takes a lock.
        items = _items()
        with Session(app.extensions["engine"]) as session:
            # Steps 2 and 4-5. The row lock makes a second simultaneous submission wait here.
            event = _own_event(session, event_request_id, lock=True)
            if event.status not in CHANGEABLE_STATUSES:
                abort(409, NOT_AVAILABLE)
            if _pending_request(session, event.id) is not None:
                abort(409, ALREADY_PENDING)

            _equipment_snapshots(session, event, items)

            # Step 6. The request and its items are one write, so no request exists without items.
            change_request = EventChangeRequest(
                event_request_id=event.id,
                status=PENDING,
                submitted_by_account_id=g.user_id,
                submitted_at=settings._now(),
                items=[
                    EventChangeRequestItem(
                        field=item["field"],
                        current_value=(
                            item["current_value"]
                            if "current_value" in item
                            else _current_value(event, item["field"])
                        ),
                        requested_value=item["requested_value"],
                        reason=item["reason"],
                    )
                    for item in items
                ],
            )
            session.add(change_request)
            try:
                # SPL-103. Saved with the request, so a refused submission leaves no notice. The
                # flush gives the request its id and surfaces the AC4 backstop before the notice.
                session.flush()
                add_change_request_submitted_notice(
                    session,
                    event,
                    change_request_id=change_request.id,
                    field_labels=[_field_label(item["field"]) for item in items],
                )
                session.commit()
            except IntegrityError:
                # Backstop for AC4: the partial unique index refuses a second Pending request.
                session.rollback()
                abort(409, ALREADY_PENDING)
            return jsonify(change_request=serialize_change_request(change_request)), 201

    @app.get("/api/event-requests/<int:event_request_id>/change-requests")
    @require_roles(Role.EVENT_ORGANISER, Role.EVENT_COORDINATOR)
    def list_change_requests(event_request_id: int):
        """SPL-111: the owning organiser or assigned coordinator reads the change requests."""

        if event_request_id > MAX_EVENT_REQUEST_ID:
            abort(404, NOT_FOUND)
        with Session(app.extensions["engine"]) as session:
            event = session.get(EventRequest, event_request_id)
            # A missing event, a draft and an event the caller has no part in all answer the same.
            if event is None or event.status == "draft" or not _may_read(session, event):
                abort(404, NOT_FOUND)
            rows = session.scalars(
                select(EventChangeRequest)
                .where(EventChangeRequest.event_request_id == event.id)
                .options(selectinload(EventChangeRequest.items))
                .order_by(EventChangeRequest.submitted_at.desc(), EventChangeRequest.id.desc())
            ).all()
            return jsonify(change_requests=[serialize_change_request(row) for row in rows])


def serialize_change_request(change_request: EventChangeRequest) -> dict[str, Any]:
    return {
        "id": change_request.id,
        "event_request_id": change_request.event_request_id,
        "status": change_request.status,
        "submitted_at": settings._timestamp(change_request.submitted_at),
        "items": [
            {
                "id": item.id,
                "field": item.field,
                "field_label": _field_label(item.field),
                "current_value": item.current_value,
                "requested_value": item.requested_value,
                "reason": item.reason,
                "decision": item.decision or "pending",
                "decline_reason": item.decline_reason,
                "decided_by": (
                    {"id": item.decided_by_account_id, "display_name": item.decided_by.display_name}
                    if item.decided_by
                    else None
                ),
                "decided_at": settings._timestamp(item.decided_at),
            }
            for item in change_request.items
        ],
    }


def _items() -> list[dict[str, Any]]:
    """The submitted items, cleaned, or a 400 naming what is wrong (AC2)."""

    data = request_json()
    if set(data) != {"items"}:
        abort(400, ONLY_ITEMS)
    submitted = data["items"]
    if not isinstance(submitted, list) or not submitted:
        abort(400, "Add at least one item to the change request.")
    if len(submitted) > MAX_ITEMS:
        abort(400, f"A change request accepts at most {MAX_ITEMS} items.")
    if len(submitted) > len(FIELDS) and not any(
        isinstance(item, dict) and item.get("field") == "equipment" for item in submitted
    ):
        abort(400, "A change request can change each field only once.")
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, raw in enumerate(submitted, start=1):
        if not isinstance(raw, dict) or set(raw) != {"field", "requested_value", "reason"}:
            abort(400, ONLY_ITEM_KEYS)
        field = raw["field"]
        if not isinstance(field, str) or field not in {*FIELDS, "equipment"}:
            abort(400, f"Item {index}: choose a field that can be changed.")
        value = (
            _equipment_value(raw["requested_value"])
            if field == "equipment"
            else _requested_value(field, raw["requested_value"])
        )
        if field == "equipment":
            field = (
                f"equipment:add:{index}"
                if value["operation"] == "add"
                else f"equipment:line:{value['requirement_id']}"
            )
        if field in seen:
            abort(400, f"{_field_label(field)} is in this change request more than once.")
        seen.add(field)
        reason = required_text(raw["reason"], f"Item {index} reason")
        if len(reason) > MAX_REASON_LENGTH:
            abort(400, f"Item {index} reason must be {MAX_REASON_LENGTH} characters or fewer.")
        items.append(
            {
                "field": field,
                "requested_value": value,
                "reason": reason,
            }
        )
    return items


def _requested_value(field: str, value: Any) -> Any:
    """The requested value, valid for its field, in the form the event stores it."""

    label = FIELDS[field]
    if field in _TEXT_FIELDS:
        text = required_text(value, label)
        if len(text) > MAX_TEXT_LENGTH:
            abort(400, f"{label} must be {MAX_TEXT_LENGTH} characters or fewer.")
        return text
    if field == "proposed_date":
        return _iso_date(value).isoformat()
    if field in ("start_time", "end_time"):
        return _iso_time(value, label).isoformat(timespec="minutes")
    if field == "expected_attendance":
        return _positive_integer(value, label)
    if field in _LIST_FIELDS:
        return _string_list(value, label)
    abort(400, f"{label} cannot be changed.")  # pragma: no cover - FIELDS is exhaustive above


def _current_value(event: EventRequest, field: str) -> Any:
    value = getattr(event, field)
    if field == "proposed_date":
        return value.isoformat() if value else None
    if field in ("start_time", "end_time"):
        return value.isoformat(timespec="minutes") if value else None
    return value


def _own_event(session: Session, event_request_id: int, *, lock: bool = False) -> EventRequest:
    """The caller's own submitted event; anything else gets the same 404 as an unknown id."""

    if event_request_id > MAX_EVENT_REQUEST_ID:
        abort(404, NOT_FOUND)
    query = select(EventRequest).where(
        EventRequest.id == event_request_id,
        EventRequest.organiser_account_id == g.user_id,
        EventRequest.status != "draft",
    )
    event = session.scalar(query.with_for_update() if lock else query)
    if event is None:
        abort(404, NOT_FOUND)
    return event


def _may_read(session: Session, event: EventRequest) -> bool:
    if Role.EVENT_ORGANISER.value in g.account_roles and event.organiser_account_id == g.user_id:
        return True
    return Role.EVENT_COORDINATOR.value in g.account_roles and is_assigned_coordinator(
        session, event.id, g.user_id
    )


def _pending_request(session: Session, event_request_id: int) -> int | None:
    return session.scalar(
        select(EventChangeRequest.id).where(
            EventChangeRequest.event_request_id == event_request_id,
            EventChangeRequest.status == PENDING,
        )
    )


def _field_label(field: str) -> str:
    if field.startswith("equipment:add:"):
        return "Add equipment requirement"
    if field.startswith("equipment:line:"):
        return "Equipment requirement"
    return FIELDS.get(field, field)


def _equipment_value(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or value.get("operation") not in ("add", "update", "remove"):
        abort(400, "Choose add, update or remove for the equipment proposal.")
    operation = value["operation"]
    identity = "equipment_type_id" if operation == "add" else "requirement_id"
    expected = {"operation", identity}
    if operation != "remove":
        expected |= {"quantity", "notes"}
    if set(value) != expected:
        abort(400, "Provide only the equipment action, selected type or line, quantity and notes.")
    target = value[identity]
    if type(target) is not int or not 0 < target <= MAX_EVENT_REQUEST_ID:
        abort(400, "Choose a valid equipment type or requirement line.")
    cleaned = {"operation": operation, identity: target}
    if operation != "remove":
        quantity = value["quantity"]
        if type(quantity) is not int or not 0 < quantity <= 2_147_483_647:
            abort(400, "Equipment quantity must be a positive whole number up to 2147483647.")
        notes = value["notes"]
        if notes is not None and (not isinstance(notes, str) or len(notes) > MAX_TEXT_LENGTH):
            abort(400, f"Technical notes must be text of {MAX_TEXT_LENGTH} characters or fewer.")
        cleaned.update(quantity=quantity, notes=notes.strip() or None if notes else None)
    return cleaned


def _equipment_snapshot(line: EquipmentRequirement) -> dict[str, Any]:
    return {
        "requirement_id": line.id,
        "equipment_type_id": line.equipment_type_id,
        "equipment_type": line.equipment_type,
        "quantity": line.quantity,
        "notes": line.notes,
    }


def _equipment_snapshots(
    session: Session, event: EventRequest, items: list[dict[str, Any]]
) -> None:
    # AC2/AC5: capture server-owned values under the event lock; never edit actual arrangements.
    for item in items:
        if not item["field"].startswith("equipment:"):
            continue
        proposal = item["requested_value"]
        if proposal["operation"] == "add":
            equipment_type = session.get(EquipmentType, proposal["equipment_type_id"])
            if equipment_type is None:
                abort(400, "Choose an equipment type from the catalogue.")
            item["current_value"] = None
            proposal["equipment_type"] = equipment_type.name
        else:
            line = session.scalar(
                select(EquipmentRequirement).where(
                    EquipmentRequirement.id == proposal["requirement_id"],
                    EquipmentRequirement.event_request_id == event.id,
                    EquipmentRequirement.status != "removed",
                )
            )
            if line is None:
                abort(400, "Choose a current equipment requirement from this event.")
            item["current_value"] = _equipment_snapshot(line)
            if proposal["operation"] == "update":
                item["requested_value"] = {**item["current_value"], **proposal}
