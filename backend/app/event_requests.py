"""Event-request creation and read routes for Sprint 1."""

from datetime import date, time
from typing import Any

from flask import Flask, abort, g, jsonify, request
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.authorization import require_roles
from app.models import EquipmentRequirement, EventRequest, Role

SLOT_WINDOWS = (
    ("AM", 7 * 60, 12 * 60),
    ("PM", 13 * 60, 18 * 60),
    ("NIGHT", 19 * 60, 24 * 60),
)

_OPTIONAL_TEXT_FIELDS = (
    "description",
    "preferred_room_layout",
    "facilities_notes",
    "accessibility_needs",
    "location_preference",
    "venue_notes",
    "preferred_venue_name",
    "registration_notes",
)
_REQUEST_FIELDS = {
    "name",
    "purpose",
    "proposed_date",
    "start_time",
    "end_time",
    "expected_attendance",
    "required_facilities",
    "registration_required",
    "equipment_requirements",
    *_OPTIONAL_TEXT_FIELDS,
}


def register_event_request_routes(app: Flask) -> None:
    @app.post("/api/event-requests")
    @require_roles(Role.EVENT_ORGANISER)
    def create_event_request():
        data = _request_json()
        attributes, equipment_lines = _event_request_attributes(data)
        event_request = EventRequest(
            organiser_account_id=g.user_id,
            organisation_id=None,
            status="submitted",
            **attributes,
        )
        event_request.equipment_requirements = [
            EquipmentRequirement(**line) for line in equipment_lines
        ]
        with Session(app.extensions["engine"]) as session:
            session.add(event_request)
            session.commit()
            event_id = event_request.id
            created = _find_event_request(session, event_id)
            return jsonify(event_request=_serialize_event_request(created)), 201

    @app.get("/api/event-requests")
    @require_roles(Role.EVENT_ORGANISER, Role.EVENT_COORDINATOR)
    def list_event_requests():
        statement = (
            select(EventRequest)
            .options(selectinload(EventRequest.equipment_requirements))
            .order_by(EventRequest.proposed_date, EventRequest.start_time, EventRequest.id)
        )
        if Role.EVENT_COORDINATOR.value not in g.account_roles:
            statement = statement.where(EventRequest.organiser_account_id == g.user_id)
        with Session(app.extensions["engine"]) as session:
            events = session.scalars(statement).all()
            return jsonify(event_requests=[_serialize_event_request(event) for event in events])

    @app.get("/api/event-requests/<int:event_request_id>")
    @require_roles(Role.EVENT_ORGANISER, Role.EVENT_COORDINATOR)
    def get_event_request(event_request_id: int):
        with Session(app.extensions["engine"]) as session:
            event = _find_event_request(session, event_request_id)
            if (
                Role.EVENT_COORDINATOR.value not in g.account_roles
                and event.organiser_account_id != g.user_id
            ):
                abort(404, "Event request not found.")
            return jsonify(event_request=_serialize_event_request(event))


def _request_json() -> dict[str, Any]:
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        abort(400, "A JSON object is required.")
    return data


def _event_request_attributes(
    data: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    unexpected = set(data) - _REQUEST_FIELDS
    if unexpected:
        abort(400, f"Unexpected event request field: {sorted(unexpected)[0]}.")

    proposed_date = _iso_date(data.get("proposed_date"))
    if proposed_date < date.today():
        abort(400, "Proposed date cannot be in the past.")
    start_time = _iso_time(data.get("start_time"), "Start time")
    end_time = _iso_time(data.get("end_time"), "End time")
    if end_time <= start_time:
        abort(400, "End time must be after start time.")

    attributes: dict[str, Any] = {
        "name": _required_text(data.get("name"), "Event name"),
        "purpose": _required_text(data.get("purpose"), "Purpose"),
        "proposed_date": proposed_date,
        "start_time": start_time,
        "end_time": end_time,
        "expected_attendance": _positive_integer(
            data.get("expected_attendance"), "Expected attendance"
        ),
        "required_facilities": _string_list(
            data.get("required_facilities", []), "Required facilities"
        ),
        "registration_required": _boolean(
            data.get("registration_required", False), "Registration required"
        ),
    }
    for field in _OPTIONAL_TEXT_FIELDS:
        attributes[field] = _optional_text(data.get(field), field.replace("_", " ").title())
    return attributes, _equipment_lines(data.get("equipment_requirements", []))


def _required_text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        abort(400, f"{label} is required.")
    return value.strip()


def _optional_text(value: Any, label: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        abort(400, f"{label} must be text.")
    return value.strip() or None


def _iso_date(value: Any) -> date:
    if not isinstance(value, str):
        abort(400, "Proposed date must use YYYY-MM-DD.")
    try:
        return date.fromisoformat(value)
    except ValueError:
        abort(400, "Proposed date must use YYYY-MM-DD.")


def _iso_time(value: Any, label: str) -> time:
    if (
        not isinstance(value, str)
        or len(value) != 5
        or value[2] != ":"
        or not value[:2].isdigit()
        or not value[3:].isdigit()
    ):
        abort(400, f"{label} must use HH:MM.")
    try:
        parsed = time.fromisoformat(value)
    except ValueError:
        abort(400, f"{label} must use HH:MM.")
    if parsed.tzinfo is not None:
        abort(400, f"{label} must be a local time without a timezone.")
    return parsed


def _positive_integer(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        abort(400, f"{label} must be a positive whole number.")
    return value


def _boolean(value: Any, label: str) -> bool:
    if not isinstance(value, bool):
        abort(400, f"{label} must be true or false.")
    return value


def _string_list(value: Any, label: str) -> list[str]:
    if not isinstance(value, list):
        abort(400, f"{label} must be a list of text values.")
    result = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            abort(400, f"{label} must contain only non-empty text values.")
        result.append(item.strip())
    return result


def _equipment_lines(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        abort(400, "Equipment requirements must be a list.")
    lines = []
    allowed = {"equipment_type", "quantity", "notes"}
    for index, item in enumerate(value, start=1):
        if not isinstance(item, dict):
            abort(400, f"Equipment requirement {index} must be an object.")
        unexpected = set(item) - allowed
        if unexpected:
            abort(400, f"Unexpected equipment field: {sorted(unexpected)[0]}.")
        lines.append(
            {
                "equipment_type": _required_text(
                    item.get("equipment_type"), f"Equipment requirement {index} type"
                ),
                "quantity": _positive_integer(
                    item.get("quantity"), f"Equipment requirement {index} quantity"
                ),
                "notes": _optional_text(item.get("notes"), f"Equipment requirement {index} notes"),
            }
        )
    return lines


def _find_event_request(session: Session, event_request_id: int) -> EventRequest:
    event = session.scalar(
        select(EventRequest)
        .where(EventRequest.id == event_request_id)
        .options(selectinload(EventRequest.equipment_requirements))
    )
    if event is None:
        abort(404, "Event request not found.")
    return event


def _mapped_slots(start: time, end: time) -> list[str]:
    start_minutes = start.hour * 60 + start.minute
    end_minutes = end.hour * 60 + end.minute
    return [
        name
        for name, slot_start, slot_end in SLOT_WINDOWS
        if start_minutes < slot_end and end_minutes > slot_start
    ]


def _serialize_event_request(event: EventRequest) -> dict[str, Any]:
    return {
        "id": event.id,
        "organiser_account_id": event.organiser_account_id,
        "organisation_id": event.organisation_id,
        "name": event.name,
        "purpose": event.purpose,
        "description": event.description,
        "proposed_date": event.proposed_date.isoformat(),
        "start_time": event.start_time.isoformat(timespec="minutes"),
        "end_time": event.end_time.isoformat(timespec="minutes"),
        "mapped_slots": _mapped_slots(event.start_time, event.end_time),
        "expected_attendance": event.expected_attendance,
        "status": event.status,
        "preferred_room_layout": event.preferred_room_layout,
        "required_facilities": event.required_facilities,
        "facilities_notes": event.facilities_notes,
        "accessibility_needs": event.accessibility_needs,
        "location_preference": event.location_preference,
        "venue_notes": event.venue_notes,
        "preferred_venue_name": event.preferred_venue_name,
        "registration_required": event.registration_required,
        "registration_notes": event.registration_notes,
        "equipment_requirements": [
            {
                "id": line.id,
                "equipment_type": line.equipment_type,
                "quantity": line.quantity,
                "notes": line.notes,
            }
            for line in event.equipment_requirements
        ],
    }
