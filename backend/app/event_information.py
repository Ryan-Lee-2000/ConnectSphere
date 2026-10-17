"""Assigned-coordinator ordinary event information edits (SPL-108).

The route accepts a deliberately small whitelist. Date, time, attendance, venue, facilities,
equipment, registration settings and lifecycle status can affect arrangements and are owned by
their respective workflows. A save locks the event, normalizes supplied values and commits the
changed values with one audit record, so concurrent edits retain truthful previous values.
"""

import re
from datetime import datetime
from typing import Any

from flask import Flask, abort, g, jsonify
from sqlalchemy.orm import Session

from app.authorization import require_roles
from app.coordinator_assignment import MAX_EVENT_REQUEST_ID, _serialize_assigned_event_detail
from app.event_requests import SINGAPORE
from app.event_statuses import ACTIVE_EVENT_STATUSES
from app.exact_venue_bookings import lock_event
from app.models import EventDetailChange, EventRequest, Role
from app.validation import request_json

FIELDS = {
    "purpose": ("Purpose", 2000),
    "description": ("Description", 2000),
    "event_notes": ("Event notes", 2000),
    "registration_notes": ("Registration notes", 2000),
    "event_contact_name": ("Event contact name", 200),
    "event_contact_email": ("Event contact email", 320),
    "event_contact_phone": ("Event contact phone", 50),
}
EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")
NOT_FOUND = "Assigned event not found."
NOT_ACTIVE = "Event information can only be edited while the event is active."
ONLY_INFORMATION = (
    "Event information accepts only purpose, description, event_notes, registration_notes, "
    "event_contact_name, event_contact_email and event_contact_phone."
)


def register_event_information_routes(app: Flask) -> None:
    @app.patch("/api/event-requests/assigned/<int:event_request_id>/event-information")
    @require_roles(Role.EVENT_COORDINATOR)
    def edit_event_information(event_request_id: int):
        with Session(app.extensions["engine"]) as session:
            event = _assigned_event(session, event_request_id)
            if event.status not in ACTIVE_EVENT_STATUSES:
                abort(409, NOT_ACTIVE)

            values = _values()
            changes: dict[str, dict[str, str | None]] = {}
            for field, value in values.items():
                previous = getattr(event, field)
                if value != previous:
                    changes[field] = {"previous": previous, "new": value}

            if not changes:
                return jsonify(event=_serialize_assigned_event_detail(event), change=None)

            changed_at = datetime.now(SINGAPORE)
            for field, change in changes.items():
                setattr(event, field, change["new"])
            audit = EventDetailChange(
                event_request_id=event.id,
                changes=changes,
                changed_by_account_id=g.user_id,
                changed_at=changed_at,
            )
            session.add(audit)
            session.commit()
            return jsonify(
                event=_serialize_assigned_event_detail(event),
                change={
                    "id": audit.id,
                    "changes": audit.changes,
                    "changed_by_account_id": audit.changed_by_account_id,
                    "changed_at": audit.changed_at.isoformat(),
                },
            )


def _assigned_event(session: Session, event_request_id: int) -> EventRequest:
    """Use the shared event-then-assignment lock order and keep one generic 404."""

    if event_request_id > MAX_EVENT_REQUEST_ID:
        abort(404, NOT_FOUND)
    # Reassignment writes the assignment before its history row. Taking NO KEY UPDATE on the
    # event first lets that history foreign-key check finish while this request waits for the
    # assignment, avoiding an event/assignment lock cycle.
    event = lock_event(session, event_request_id, g.user_id)
    if event is None:
        abort(404, NOT_FOUND)
    return event


def _values() -> dict[str, str | None]:
    data = request_json()
    if not data or set(data) - set(FIELDS):
        abort(400, ONLY_INFORMATION)

    values: dict[str, str | None] = {}
    for field, (label, maximum) in FIELDS.items():
        if field not in data:
            continue
        value: Any = data[field]
        if value is not None and not isinstance(value, str):
            abort(400, f"{label} must be text.")
        normalized = value.strip() or None if value else None
        if normalized is not None and len(normalized) > maximum:
            abort(400, f"{label} must be {maximum} characters or fewer.")
        values[field] = normalized

    email = values.get("event_contact_email")
    if email is not None and not EMAIL.fullmatch(email):
        abort(400, "Enter the event contact email in the form name@domain.")
    return values
