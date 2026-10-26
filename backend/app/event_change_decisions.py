"""Assigned coordinator decisions and their effects, saved atomically (SPL-112)."""

import hashlib
import json
from datetime import datetime

from flask import Flask, abort, g, jsonify
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app import significant_event_changes as significant
from app.authorization import require_roles
from app.coordinator_assignment import _serialize_assigned_event_detail
from app.equipment_releases import _held_quantity
from app.equipment_requirements import (
    _locked_editable_requirement,
    _new_attributes,
    _notify_technical_support,
    remove_requirement,
)
from app.event_change_requests import (
    MAX_ITEMS,
    _current_value,
    _equipment_snapshot,
    _field_label,
    _requested_value,
    serialize_change_request,
)
from app.event_information import _assigned_event
from app.event_requests import SINGAPORE
from app.event_statuses import ACTIVE_EVENT_STATUSES
from app.models import (
    EquipmentRequirement,
    EquipmentType,
    EventChangeRequest,
    EventDetailChange,
    EventRequest,
    Role,
)
from app.notifications import add_organiser_notice
from app.validation import request_json, required_text


def register_event_change_decision_routes(app: Flask):
    endpoint = (
        "/api/event-requests/assigned/<int:event_id>/change-requests/<int:request_id>/decisions"
    )

    @app.post(endpoint + "/preview")
    @require_roles(Role.EVENT_COORDINATOR)
    def preview_change_decisions(event_id, request_id):
        with Session(app.extensions["engine"]) as session:
            plan = _prepare(session, event_id, request_id)
            return jsonify(**plan["preview"])

    @app.post(endpoint)
    @require_roles(Role.EVENT_COORDINATOR)
    def save_change_decisions(event_id, request_id):
        with Session(app.extensions["engine"]) as session:
            plan = _prepare(session, event_id, request_id)
            if request_json().get("preview_token") != plan["preview"]["preview_token"]:
                abort(409, "The request or arrangements changed. Review the decisions again.")
            event, change_request = plan["event"], plan["request"]
            now = datetime.now(SINGAPORE)
            # AC2: all accepted values, impacts and decisions commit together or not at all.
            if plan["significant"] is not None:
                _, values, changes, impacts, _, equipment = plan["significant"]
                if changes:
                    significant.apply_prepared_change(
                        session, event, values, changes, impacts, equipment
                    )
            ordinary_changes = {}
            for field, value in plan["ordinary"].items():
                if getattr(event, field) != value:
                    ordinary_changes[field] = {"previous": getattr(event, field), "new": value}
                    setattr(event, field, value)
            if ordinary_changes:
                _audit(session, event, ordinary_changes, now)
            for operation, payload in plan["equipment"]:
                if operation == "update":
                    _, values, changes, impacts, _, equipment = payload
                    if changes:
                        significant.apply_prepared_change(
                            session, event, values, changes, impacts, equipment
                        )
                elif operation == "add":
                    line = EquipmentRequirement(**payload)
                    session.add(line)
                    session.flush()
                    _notify_technical_support(
                        session, line, "requirement_recorded", f"line-{line.id}"
                    )
                    _audit(
                        session,
                        event,
                        {
                            f"equipment_requirement:{line.id}": {
                                "previous": None,
                                "new": _equipment_snapshot(line),
                            }
                        },
                        now,
                    )
                    significant.return_to_planning(session, event, now)
                else:
                    line, equipment_type = payload
                    previous = _equipment_snapshot(line)
                    remove_requirement(session, line, equipment_type)
                    _audit(
                        session,
                        event,
                        {f"equipment_requirement:{line.id}": {"previous": previous, "new": None}},
                        now,
                    )
                    significant.return_to_planning(session, event, now)
            for item, decision, reason in plan["decisions"]:
                item.decision = decision
                item.decline_reason = reason
                item.decided_by_account_id = g.user_id
                item.decided_at = now
                # SPL-123 AC4: the values themselves stay in SPL-113's outcome view.
                outcome = f"declined. Reason: {reason}" if reason else f"{decision}."
                add_organiser_notice(
                    session,
                    event,
                    actor_id=g.user_id,
                    kind="change_item_decided",
                    source_id=item.id,
                    message=f"Your change request for {event.name}: {_field_label(item.field)} "
                    f"was {outcome}",
                    recipient_id=change_request.submitted_by_account_id,
                )
            if all(item.decision is not None for item in change_request.items):
                change_request.status = "closed"
            session.commit()
            return jsonify(
                change_request=serialize_change_request(change_request),
                event=_serialize_assigned_event_detail(event),
            )


def _audit(session, event, changes, now):
    session.add(
        EventDetailChange(
            event_request_id=event.id,
            changes=changes,
            changed_by_account_id=g.user_id,
            changed_at=now,
        )
    )


def _decisions(change_request, raw):
    if not isinstance(raw, list) or not raw or len(raw) > MAX_ITEMS:
        abort(400, "Select at least one item to decide (at most 100).")
    items = {item.id: item for item in change_request.items}
    seen = set()
    decisions = []
    for entry in raw:
        if not isinstance(entry, dict) or set(entry) - {"item_id", "decision", "decline_reason"}:
            abort(400, "Send only item_id, decision and decline_reason for each decision.")
        item_id = entry.get("item_id")
        if isinstance(item_id, bool) or not isinstance(item_id, int) or item_id not in items:
            abort(400, "Choose an item from this change request.")
        if item_id in seen:
            abort(400, "Decide each item only once.")
        seen.add(item_id)
        item = items[item_id]
        if item.decision is not None:
            abort(409, "Saved decisions are final. Reload the change request.")
        decision = entry.get("decision")
        if decision not in ("accepted", "declined"):
            abort(400, "Choose Accepted or Declined.")
        reason = None
        if decision == "declined":
            reason = required_text(entry.get("decline_reason"), "Decline reason")
            if len(reason) > 1000:
                abort(400, "Decline reason must be at most 1000 characters.")
        elif entry.get("decline_reason") not in (None, ""):
            abort(400, "Only declined items have a decline reason.")
        decisions.append((item, decision, reason))
    return sorted(decisions, key=lambda row: row[0].id)


def _prepare(session, event_id, request_id):
    data = request_json()
    if set(data) - {"decisions", "preview_token"}:
        abort(400, "Send only decisions and preview_token.")
    event = _assigned_event(session, event_id)
    if event.status not in ACTIVE_EVENT_STATUSES:
        abort(409, "Change request decisions can only be made while the event is active.")
    if request_id > 2**31 - 1:
        abort(404, "Change request not found.")
    change_request = session.scalar(
        select(EventChangeRequest)
        .where(
            EventChangeRequest.id == request_id,
            EventChangeRequest.event_request_id == event.id,
        )
        .with_for_update()
        .options(selectinload(EventChangeRequest.items))
    )
    if change_request is None:
        abort(404, "Change request not found.")
    if change_request.status != "pending":
        abort(409, "Items on a Closed request cannot be changed.")
    decisions = _decisions(change_request, data.get("decisions"))
    ordinary, values, equipment_items = {}, {}, []
    for item, decision, _ in decisions:
        if decision != "accepted":
            continue
        if item.field.startswith("equipment:"):
            equipment_items.append(item)
        else:
            if _current_value(event, item.field) != item.current_value:
                abort(
                    409,
                    f"{item.field}: the original value has changed. Decline this stale proposal.",
                )
            value = _requested_value(item.field, item.requested_value)
            (values if item.field in significant.FIELDS else ordinary)[item.field] = value
    if equipment_items and event.status not in {"planning", "confirmed"}:
        abort(
            409,
            "Equipment proposals can be accepted in Planning or Confirmed. "
            "Leave them pending or decline them until then.",
        )
    added_type_ids = {
        item.requested_value["equipment_type_id"]
        for item in equipment_items
        if item.requested_value["operation"] == "add"
    }
    prepared = (
        significant.prepare_change(session, event, values, extra_type_ids=added_type_ids)
        if values
        else None
    )
    proposed = EventRequest(**{c.key: getattr(event, c.key) for c in event.__table__.columns})
    if prepared:
        for key, value in prepared[1].items():
            setattr(proposed, key, value)
    equipment, arrangements, tokens = [], [], []
    has_significant_change = False
    if prepared:
        preview = significant._preview(event, prepared[2], prepared[3], prepared[4])
        arrangements.extend(preview["arrangements"])
        tokens.append(preview["preview_token"])
        has_significant_change = bool(prepared[2])
    if equipment_items:
        # AC2: lock all catalogue types before any line, as the existing stock writers do.
        type_ids = set(
            session.scalars(
                select(EquipmentRequirement.equipment_type_id).where(
                    EquipmentRequirement.event_request_id == event.id,
                    EquipmentRequirement.equipment_type_id.is_not(None),
                )
            ).all()
        )
        type_ids.update(
            item.requested_value["equipment_type_id"]
            for item in equipment_items
            if item.requested_value["operation"] == "add"
        )
        session.scalars(
            select(EquipmentType)
            .where(EquipmentType.id.in_(type_ids))
            .order_by(EquipmentType.id)
            .with_for_update()
        ).all()
    for item in equipment_items:
        value = item.requested_value
        operation = value["operation"]
        if operation == "add":
            attributes = _new_attributes(
                session,
                proposed,
                {
                    **{key: value[key] for key in ("equipment_type_id", "quantity", "notes")},
                    "required_start_date": significant._json(proposed.proposed_date),
                    "required_end_date": significant._json(proposed.proposed_date),
                },
            )
            equipment.append((operation, attributes))
            tokens.append(
                {"addition": {key: significant._json(v) for key, v in attributes.items()}}
            )
            arrangements.append(
                {
                    "kind": "equipment",
                    "id": item.id,
                    "name": attributes["equipment_type"],
                    "reason": (
                        "Add a Requested requirement for Technical Support; no stock is reserved."
                    ),
                }
            )
            has_significant_change = True
            continue
        line, equipment_type = _locked_editable_requirement(session, event, value["requirement_id"])
        if _equipment_snapshot(line) != item.current_value:
            abort(409, "The equipment requirement has changed. Decline this stale proposal.")
        if operation == "update":
            change = significant.prepare_change(
                session,
                event,
                {
                    "quantity": value["quantity"],
                    "notes": value["notes"],
                },
                line.id,
            )
            preview = significant._preview(event, change[2], change[3], change[4])
            tokens.append(preview["preview_token"])
            arrangements.extend(preview["arrangements"])
            has_significant_change |= bool(change[2])
            equipment.append((operation, change))
        else:
            held = _held_quantity(session, line.id)
            tokens.append({"removal": significant._snapshot(line), "held": held})
            arrangements.append(
                {
                    "kind": "equipment",
                    "id": line.id,
                    "name": line.equipment_type,
                    "reason": f"Remove this requirement and release {held} reserved unit(s).",
                }
            )
            equipment.append((operation, (line, equipment_type)))
            has_significant_change = True
    snapshot = {
        "event": significant._snapshot(event),
        "request": serialize_change_request(change_request),
        "actor": g.user_id,
        "tokens": tokens,
        "decisions": [(item.id, decision, reason) for item, decision, reason in decisions],
    }
    token = hashlib.sha256(json.dumps(snapshot, sort_keys=True).encode()).hexdigest()
    return {
        "event": event,
        "request": change_request,
        "decisions": decisions,
        "ordinary": ordinary,
        "significant": prepared,
        "equipment": equipment,
        "preview": {
            "preview_token": token,
            "arrangements": arrangements,
            "returns_to_planning": has_significant_change and event.status == "confirmed",
        },
    }
