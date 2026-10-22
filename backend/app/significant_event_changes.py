"""Preview and atomically apply significant coordinator edits (SPL-109)."""

import hashlib
import json
from datetime import date, datetime, time
from typing import Any

from flask import Flask, abort, g, jsonify
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.authorization import require_roles
from app.coordinator_assignment import _serialize_assigned_event_detail
from app.event_information import _assigned_event
from app.event_requests import SINGAPORE, _iso_date, _iso_time, _positive_integer, _string_list
from app.event_review import transition_event_status
from app.event_statuses import ACTIVE_EVENT_STATUSES
from app.models import (
    ACTIVE_BOOKING_STATUSES,
    EquipmentRequirement,
    EquipmentType,
    EventDetailChange,
    EventRequest,
    Role,
    Venue,
    VenueBooking,
)
from app.validation import request_json
from app.venue_requirement_review import assess_event_bookings, requirement_reasons

FIELDS = {
    "proposed_date": "Date",
    "start_time": "Start time",
    "end_time": "End time",
    "expected_attendance": "Expected attendance",
    "preferred_room_layout": "Room layout",
    "required_facilities": "Required facilities",
    "accessibility_needs": "Accessibility needs",
    "location_preference": "Location preference",
}
HELD_STATUSES = {"reserved", "partially_reserved", "review_required"}


def register_significant_event_change_routes(app: Flask) -> None:
    @app.post("/api/event-requests/assigned/<int:event_request_id>/significant-changes/preview")
    @require_roles(Role.EVENT_COORDINATOR)
    def preview_significant_change(event_request_id: int):
        with Session(app.extensions["engine"]) as session:
            event, values, changes, impacts, snapshot, equipment = _prepare(
                session, event_request_id
            )
            preview = _preview(event, changes, impacts, snapshot)
            if not changes:
                preview["event"] = _serialize_assigned_event_detail(event)
            return jsonify(**preview)

    @app.patch("/api/event-requests/assigned/<int:event_request_id>/significant-changes")
    @require_roles(Role.EVENT_COORDINATOR)
    def save_significant_change(event_request_id: int):
        with Session(app.extensions["engine"]) as session:
            event, values, changes, impacts, snapshot, equipment = _prepare(
                session, event_request_id
            )
            preview = _preview(event, changes, impacts, snapshot)
            if request_json().get("preview_token") != preview["preview_token"]:
                abort(
                    409,
                    "The event or its arrangements changed. "
                    "Review the changes again before saving.",
                )
            if not changes:
                return jsonify(event=_serialize_assigned_event_detail(event), change=None)
            now = datetime.now(SINGAPORE)
            released = 0
            if equipment is not None:
                from app.equipment_requirements import _apply_change

                line, equipment_type = equipment
                changed = {
                    key: (getattr(line, key), value)
                    for key, value in values.items()
                    if getattr(line, key) != value
                }
                released = _apply_change(session, line, equipment_type, values, changed)
                audit_changes = {f"equipment_requirement:{line.id}": changes}
            else:
                for key, value in values.items():
                    setattr(event, key, value)
                assess_event_bookings(
                    session, event, assessed_by_account_id=g.user_id, assessed_at=now
                )
                _flag_equipment(session, impacts, now)
                audit_changes = changes
            status_change = return_to_planning(session, event, now)
            audit = EventDetailChange(
                event_request_id=event.id,
                changes=audit_changes,
                changed_by_account_id=g.user_id,
                changed_at=now,
            )
            session.add(audit)
            session.commit()
            return jsonify(
                event=_serialize_assigned_event_detail(event),
                change={"id": audit.id, "changes": audit.changes},
                status_change_id=status_change.id if status_change else None,
                released_quantity=released,
            )


def return_to_planning(session: Session, event: EventRequest, now: datetime):
    if event.status != "confirmed":
        return None
    # AC4: the durable status-history event is the handoff to SPL-123, in this transaction.
    history = transition_event_status(
        session,
        event_request_id=event.id,
        action="significant_change",
        actor_account_id=g.user_id,
        changed_at=now,
    )
    event.status = "planning"
    event.status_changed_at = now
    event.confirmed_by_account_id = None
    event.confirmed_at = None
    return history


def _json(value: Any) -> Any:
    if isinstance(value, time):
        return value.isoformat(timespec="minutes")
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def _snapshot(row) -> dict:
    return {column.key: _json(getattr(row, column.key)) for column in row.__table__.columns}


def _preview(event, changes, impacts, snapshot):
    state = {
        "event_id": event.id,
        "actor": g.user_id,
        "changes": {
            key: value for key, value in changes.items() if key != "essentiality_decided_at"
        },
        "impacts": impacts,
        "snapshot": snapshot,
    }
    token = hashlib.sha256(json.dumps(state, sort_keys=True).encode()).hexdigest()
    return {
        "changes": changes,
        "arrangements": impacts,
        "preview_token": token,
        "returns_to_planning": bool(changes) and event.status == "confirmed",
    }


def _prepare(session: Session, event_id: int):
    from app.equipment_releases import _held_quantity
    from app.equipment_requirements import (
        REVIEWED_FIELDS,
        _changed_values,
        _locked_editable_requirement,
        _update_attributes,
    )

    data = request_json()
    if set(data) - {"values", "preview_token", "equipment_requirement_id"}:
        abort(400, "Send only values, preview_token and an optional equipment_requirement_id.")
    raw = data.get("values")
    if not isinstance(raw, dict) or not raw:
        abort(400, "Provide the fields to change.")
    event = _assigned_event(session, event_id)
    if event.status not in ACTIVE_EVENT_STATUSES:
        abort(409, "Significant changes can only be made while the event is active.")
    snapshot = {"event": _snapshot(event)}
    equipment_id = data.get("equipment_requirement_id")
    if "equipment_requirement_id" in data:
        if isinstance(equipment_id, bool) or not isinstance(equipment_id, int) or equipment_id <= 0:
            abort(400, "Choose a valid equipment requirement.")
        if event.status not in {"planning", "confirmed"}:
            abort(409, "Equipment requirements can only be edited in Planning or Confirmed.")
        line, equipment_type = _locked_editable_requirement(session, event, equipment_id)
        values = _update_attributes(session, event, line, raw)
        changed = _changed_values(line, values)
        changes = {
            key: {"previous": _json(old), "new": _json(new)} for key, (old, new) in changed.items()
        }
        held = _held_quantity(session, line.id)
        snapshot["equipment"] = _snapshot(line)
        snapshot["held_quantity"] = held
        impacts = []
        if set(changed) & set(REVIEWED_FIELDS) and (held or line.status in HELD_STATUSES):
            impacts.append(
                {
                    "kind": "equipment",
                    "id": line.id,
                    "name": line.equipment_type,
                    "reason": (
                        f"Release {held} reserved unit(s) and return this line "
                        "to Technical Support for review."
                    ),
                }
            )
        return event, values, changes, impacts, snapshot, (line, equipment_type)

    values = _values(event, raw)
    changes = {
        key: {"previous": _json(getattr(event, key)), "new": _json(value)}
        for key, value in values.items()
        if getattr(event, key) != value
    }
    proposed = EventRequest(
        **{column.key: getattr(event, column.key) for column in event.__table__.columns}
    )
    for key, value in values.items():
        setattr(proposed, key, value)
    impacts = []
    venue_ids = session.scalars(
        select(VenueBooking.venue_id)
        .where(
            VenueBooking.event_request_id == event.id,
            VenueBooking.status.in_(ACTIVE_BOOKING_STATUSES),
        )
        .distinct()
        .order_by(VenueBooking.venue_id)
    ).all()
    venues = session.scalars(
        select(Venue)
        .where(Venue.id.in_(venue_ids))
        .order_by(Venue.id)
        .with_for_update()
        .options(selectinload(Venue.layouts))
    ).all()
    snapshot["venues"] = [_snapshot(venue) for venue in venues]
    snapshot["layouts"] = [
        _snapshot(layout)
        for venue in venues
        for layout in sorted(venue.layouts, key=lambda row: row.id)
    ]
    bookings = session.scalars(
        select(VenueBooking)
        .where(
            VenueBooking.event_request_id == event.id,
            VenueBooking.status.in_(ACTIVE_BOOKING_STATUSES),
        )
        .order_by(VenueBooking.id)
        .with_for_update()
    ).all()
    snapshot["bookings"] = [_snapshot(booking) for booking in bookings]
    from app.venue_booking_assessment import (
        _current_occupancy,
        _has_not_ended,
        _reasons_for_booking,
        active_findings,
    )
    from app.venue_requirement_review import REQUIREMENT_REASON_TYPES

    by_id = {venue.id: venue for venue in venues}
    intervals = {
        booking.id: _current_occupancy(by_id[booking.venue_id], proposed, booking)[0]
        for booking in bookings
    }
    for booking in bookings:
        if not _has_not_ended(booking, proposed, datetime.now(SINGAPORE)):
            continue
        reasons = _reasons_for_booking(
            session,
            by_id[booking.venue_id],
            booking,
            proposed,
            intervals[booking.id],
            {key: value for key, value in intervals.items() if value},
            include_peer_intervals=True,
        )
        reasons.extend(requirement_reasons(by_id[booking.venue_id], proposed, booking))
        if (
            changes
            and not reasons
            and any(
                finding.reason_type in REQUIREMENT_REASON_TYPES
                for finding in active_findings(session, booking.id)
            )
        ):
            impacts.append(
                {
                    "kind": "venue",
                    "id": booking.id,
                    "name": by_id[booking.venue_id].name,
                    "reason": (
                        "Resolved requirement findings will be cleared after reassessment. "
                        "Booking retained."
                    ),
                }
            )
        if changes and reasons:
            impacts.append(
                {
                    "kind": "venue",
                    "id": booking.id,
                    "name": by_id[booking.venue_id].name,
                    "reason": " ".join(reason[2] for reason in reasons)
                    + " Booking retained for review.",
                }
            )
    type_ids = session.scalars(
        select(EquipmentRequirement.equipment_type_id)
        .where(
            EquipmentRequirement.event_request_id == event.id,
            EquipmentRequirement.equipment_type_id.is_not(None),
        )
        .distinct()
        .order_by(EquipmentRequirement.equipment_type_id)
    ).all()
    session.scalars(
        select(EquipmentType)
        .where(EquipmentType.id.in_(type_ids))
        .order_by(EquipmentType.id)
        .with_for_update()
    ).all()
    lines = session.scalars(
        select(EquipmentRequirement)
        .where(EquipmentRequirement.event_request_id == event.id)
        .order_by(EquipmentRequirement.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).all()
    snapshot["equipment"] = [_snapshot(line) for line in lines]
    for line in lines:
        if changes and line.status in HELD_STATUSES:
            impacts.append(
                {
                    "kind": "equipment",
                    "id": line.id,
                    "name": line.equipment_type,
                    "reason": (
                        "Event requirements changed. Technical Support must review suitability; "
                        "reserved quantities and dates are retained."
                    ),
                }
            )
    return event, values, changes, impacts, snapshot, None


def _values(event: EventRequest, raw: dict) -> dict:
    if set(raw) - set(FIELDS):
        abort(400, "Only significant event fields can be changed here.")
    values = {}
    for key, value in raw.items():
        label = FIELDS[key]
        if key == "proposed_date":
            value = _iso_date(value)
            if value != event.proposed_date and value < datetime.now(SINGAPORE).date():
                abort(400, "Proposed date cannot be in the past.")
        elif key in {"start_time", "end_time"}:
            value = _iso_time(value, label)
        elif key == "expected_attendance":
            value = _positive_integer(value, label)
            if value > 2**31 - 1:
                abort(400, "Expected attendance is too large.")
        elif key in {"required_facilities", "accessibility_needs"}:
            value = list(dict.fromkeys(_string_list(value, label)))
            if len(value) > 100 or any(len(item) > 200 for item in value):
                abort(400, f"{label} must contain at most 100 entries of 200 characters.")
        else:
            if value is not None and (not isinstance(value, str) or len(value) > 2000):
                abort(400, f"{label} must be text of at most 2000 characters.")
            value = value.strip() or None if value else None
        values[key] = value
    start, end = values.get("start_time", event.start_time), values.get("end_time", event.end_time)
    if start is None or end is None or end <= start:
        abort(400, "End time must be after start time.")
    return values


def _flag_equipment(session: Session, impacts: list, now: datetime) -> None:
    from app.equipment_requirements import _record_change

    for impact in impacts:
        if impact["kind"] != "equipment":
            continue
        line = session.get(EquipmentRequirement, impact["id"])
        previous = {"status": line.status, "review_reason": line.review_reason}
        line.status = "review_required"
        reason = impact["reason"]
        if line.review_reason and reason not in line.review_reason:
            reason = line.review_reason + " " + reason
        elif line.review_reason:
            reason = line.review_reason
        line.review_reason = reason
        line.review_flagged_at = now
        _record_change(
            session,
            line,
            action="changed",
            old_values=previous,
            new_values={"status": line.status, "review_reason": reason},
            released=0,
            now=now,
        )
