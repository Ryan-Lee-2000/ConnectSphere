"""Assigned-coordinator review workflow: SPL-70, SPL-65, SPL-67 (approve) and SPL-68 (reject)."""

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from flask import Flask, abort, g, jsonify, request
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.authorization import require_roles
from app.coordinator_assignment import MAX_EVENT_REQUEST_ID
from app.event_requests import (
    SINGAPORE,
    serialize_approval,
    serialize_clarifications,
    serialize_rejection,
)
from app.event_statuses import status_label
from app.models import (
    Account,
    ClarificationRequest,
    EventCoordinatorAssignment,
    EventRequest,
    EventStatusHistory,
    Role,
)
from app.slots import slots_for_range

BEGIN_REVIEW = "begin_review"
REQUEST_CLARIFICATION = "request_clarification"
APPROVE = "approve"
REJECT = "reject"
SUBMITTED = "submitted"
UNDER_REVIEW = "under_review"
RETURNED_FOR_CLARIFICATION = "returned_for_clarification"
PLANNING = "planning"
REJECTED = "rejected"
MAX_CLARIFICATION_LENGTH = 2000
MAX_REJECTION_REASON_LENGTH = 2000


@dataclass(frozen=True)
class TransitionRule:
    previous_status: str
    resulting_status: str


TRANSITION_RULES = {
    BEGIN_REVIEW: TransitionRule(
        previous_status=SUBMITTED,
        resulting_status=UNDER_REVIEW,
    ),
    REQUEST_CLARIFICATION: TransitionRule(
        previous_status=UNDER_REVIEW,
        resulting_status=RETURNED_FOR_CLARIFICATION,
    ),
    # Approval lets planning begin; it books nothing and confirms nothing (Q80).
    APPROVE: TransitionRule(
        previous_status=UNDER_REVIEW,
        resulting_status=PLANNING,
    ),
    # Rejection is final (Q67): nothing leaves Rejected, so a new request is needed to proceed.
    REJECT: TransitionRule(
        previous_status=UNDER_REVIEW,
        resulting_status=REJECTED,
    ),
}


class InvalidStatusTransition(Exception):
    """The event no longer satisfies the server-owned transition rule."""


def register_event_review_routes(app: Flask) -> None:
    @app.post("/api/event-requests/<int:event_request_id>/begin-review")
    @require_roles(Role.EVENT_COORDINATOR)
    def begin_review(event_request_id: int):
        _require_action_without_parameters()
        with Session(app.extensions["engine"]) as session:
            event = session.scalar(
                select(EventRequest)
                .join(EventCoordinatorAssignment)
                .where(
                    EventRequest.id == event_request_id,
                    EventCoordinatorAssignment.coordinator_account_id == g.user_id,
                )
            )
            if event is None:
                abort(404, "Assigned event not found.")
            now = datetime.now(SINGAPORE)
            try:
                audit = transition_event_status(
                    session,
                    event_request_id=event_request_id,
                    action=BEGIN_REVIEW,
                    actor_account_id=g.user_id,
                    changed_at=now,
                )
            except InvalidStatusTransition:
                session.rollback()
                abort(409, "Only a submitted event can begin review.")
            session.commit()
            actor = session.get(Account, g.user_id)
            event = session.get(EventRequest, event_request_id)
            return jsonify(
                event=_serialize_event(event),
                transition=_serialize_transition(audit, actor),
            )

    @app.post("/api/event-requests/<int:event_request_id>/request-clarification")
    @require_roles(Role.EVENT_COORDINATOR)
    def request_clarification(event_request_id: int):
        message = _clarification_message()
        if event_request_id > MAX_EVENT_REQUEST_ID:
            abort(404, "Assigned event not found.")
        with Session(app.extensions["engine"]) as session:
            event = session.scalar(
                select(EventRequest)
                .join(EventCoordinatorAssignment)
                .where(
                    EventRequest.id == event_request_id,
                    EventCoordinatorAssignment.coordinator_account_id == g.user_id,
                )
            )
            if event is None:
                abort(404, "Assigned event not found.")
            now = datetime.now(SINGAPORE)
            try:
                audit = transition_event_status(
                    session,
                    event_request_id=event_request_id,
                    action=REQUEST_CLARIFICATION,
                    actor_account_id=g.user_id,
                    changed_at=now,
                )
            except InvalidStatusTransition:
                session.rollback()
                abort(409, "Clarification can only be requested while the event is under review.")
            session.add(
                ClarificationRequest(
                    event_request_id=event_request_id,
                    message=message,
                    author_account_id=g.user_id,
                    created_at=now,
                )
            )
            session.commit()
            actor = session.get(Account, g.user_id)
            event = session.get(EventRequest, event_request_id)
            return jsonify(
                event=_serialize_event(event),
                transition=_serialize_transition(audit, actor),
                clarifications=serialize_clarifications(event),
            )

    @app.post("/api/event-requests/<int:event_request_id>/approve")
    @require_roles(Role.EVENT_COORDINATOR)
    def approve_event_request(event_request_id: int):
        _require_action_without_parameters("Approval")
        if event_request_id > MAX_EVENT_REQUEST_ID:
            abort(404, "Assigned event not found.")
        with Session(app.extensions["engine"]) as session:
            event = session.scalar(
                select(EventRequest)
                .join(EventCoordinatorAssignment)
                .where(
                    EventRequest.id == event_request_id,
                    EventCoordinatorAssignment.coordinator_account_id == g.user_id,
                )
            )
            if event is None:
                abort(404, "Assigned event not found.")
            now = datetime.now(SINGAPORE)
            try:
                audit = transition_event_status(
                    session,
                    event_request_id=event_request_id,
                    action=APPROVE,
                    actor_account_id=g.user_id,
                    changed_at=now,
                )
            except InvalidStatusTransition:
                session.rollback()
                abort(409, "Only an event under review can be approved.")
            session.execute(
                update(EventRequest)
                .where(EventRequest.id == event_request_id)
                .values(approved_by_account_id=g.user_id, approved_at=now)
                .execution_options(synchronize_session=False)
            )
            session.commit()
            actor = session.get(Account, g.user_id)
            session.expire_all()
            event = session.get(EventRequest, event_request_id)
            return jsonify(
                event={**_serialize_event(event), **serialize_approval(event)},
                transition=_serialize_transition(audit, actor),
                message="Request approved. Event planning can begin.",
            )

    @app.post("/api/event-requests/<int:event_request_id>/reject")
    @require_roles(Role.EVENT_COORDINATOR)
    def reject_event_request(event_request_id: int):
        reason = _rejection_reason()
        if event_request_id > MAX_EVENT_REQUEST_ID:
            abort(404, "Assigned event not found.")
        with Session(app.extensions["engine"]) as session:
            event = session.scalar(
                select(EventRequest)
                .join(EventCoordinatorAssignment)
                .where(
                    EventRequest.id == event_request_id,
                    EventCoordinatorAssignment.coordinator_account_id == g.user_id,
                )
            )
            if event is None:
                abort(404, "Assigned event not found.")
            now = datetime.now(SINGAPORE)
            try:
                audit = transition_event_status(
                    session,
                    event_request_id=event_request_id,
                    action=REJECT,
                    actor_account_id=g.user_id,
                    changed_at=now,
                )
            except InvalidStatusTransition:
                session.rollback()
                abort(409, "Only an event under review can be rejected.")
            session.execute(
                update(EventRequest)
                .where(EventRequest.id == event_request_id)
                .values(rejected_by_account_id=g.user_id, rejected_at=now, rejection_reason=reason)
                .execution_options(synchronize_session=False)
            )
            session.commit()
            actor = session.get(Account, g.user_id)
            session.expire_all()
            event = session.get(EventRequest, event_request_id)
            return jsonify(
                event={**_serialize_event(event), **serialize_rejection(event)},
                transition=_serialize_transition(audit, actor),
                message="Request rejected. The Event Organiser can see your reason.",
            )


def transition_event_status(
    session: Session,
    *,
    event_request_id: int,
    action: str,
    actor_account_id: str,
    changed_at: datetime,
) -> EventStatusHistory:
    """Apply one named transition and append its evidence in the caller's transaction."""

    rule = TRANSITION_RULES[action]
    transitioned = session.execute(
        update(EventRequest)
        .where(
            EventRequest.id == event_request_id,
            EventRequest.status == rule.previous_status,
        )
        .values(status=rule.resulting_status, status_changed_at=changed_at)
        .execution_options(synchronize_session=False)
    )
    if transitioned.rowcount != 1:
        raise InvalidStatusTransition
    audit = EventStatusHistory(
        event_request_id=event_request_id,
        action=action,
        previous_status=rule.previous_status,
        resulting_status=rule.resulting_status,
        actor_account_id=actor_account_id,
        changed_at=changed_at,
    )
    session.add(audit)
    return audit


def _require_action_without_parameters(action: str = "Begin review") -> None:
    """Keep the server-owned target status out of the client request."""

    if request.content_length in (None, 0):
        return
    if not request.is_json or request.get_json(silent=True) != {}:
        abort(400, f"{action} does not accept a target status or other parameters.")


def _clarification_message() -> str:
    """The message and nothing else, so the target status stays server-owned."""

    data = request.get_json(silent=True)
    if not isinstance(data, dict) or set(data) != {"message"}:
        abort(400, "Send only a clarification message.")
    message = data["message"]
    if not isinstance(message, str) or not message.strip():
        abort(400, "Enter a clarification message.")
    message = message.strip()
    if len(message) > MAX_CLARIFICATION_LENGTH:
        abort(400, f"Keep the clarification to {MAX_CLARIFICATION_LENGTH} characters or fewer.")
    return message


def _rejection_reason() -> str:
    """The reason and nothing else, so the target status stays server-owned."""

    data = request.get_json(silent=True)
    if not isinstance(data, dict) or set(data) != {"reason"}:
        abort(400, "Send only a rejection reason.")
    reason = data["reason"]
    if not isinstance(reason, str) or not reason.strip():
        abort(400, "Enter a reason for rejecting the request.")
    reason = reason.strip()
    if len(reason) > MAX_REJECTION_REASON_LENGTH:
        abort(400, f"Keep the reason to {MAX_REJECTION_REASON_LENGTH} characters or fewer.")
    return reason


def _serialize_event(event: EventRequest) -> dict[str, Any]:
    return {
        "id": event.id,
        "name": event.name,
        "status": event.status,
        "status_label": status_label(event.status),
        "proposed_date": _date(event.proposed_date),
        # Keep the response compatible with the assigned-event detail after its
        # server-owned status transition. These are persisted event fields, not
        # values supplied by the browser.
        "mapped_slots": (
            slots_for_range(event.start_time, event.end_time)
            if event.start_time and event.end_time
            else []
        ),
        "expected_attendance": event.expected_attendance,
        "preferred_room_layout": event.preferred_room_layout,
        "required_facilities": event.required_facilities,
        "accessibility_needs": event.accessibility_needs,
        "location_preference": event.location_preference,
    }


def _serialize_transition(audit: EventStatusHistory, actor: Account) -> dict[str, Any]:
    return {
        "action": audit.action,
        "previous_status": audit.previous_status,
        "resulting_status": audit.resulting_status,
        "actor": {"id": actor.id, "name": actor.display_name},
        "changed_at": _timestamp(audit.changed_at),
    }


def _date(value: date | None) -> str | None:
    return value.isoformat() if value else None


def _timestamp(value: datetime) -> str:
    return (value if value.tzinfo else value.replace(tzinfo=SINGAPORE)).isoformat()
