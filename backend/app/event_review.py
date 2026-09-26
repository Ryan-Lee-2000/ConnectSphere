"""Assigned-coordinator review workflow for CS-E07-S2 / SPL-70."""

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from flask import Flask, abort, g, jsonify, request
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.authorization import require_roles
from app.event_requests import SINGAPORE
from app.event_statuses import status_label
from app.models import (
    Account,
    EventCoordinatorAssignment,
    EventRequest,
    EventStatusHistory,
    Role,
)
from app.slots import slots_for_range

BEGIN_REVIEW = "begin_review"
SUBMITTED = "submitted"
UNDER_REVIEW = "under_review"


@dataclass(frozen=True)
class TransitionRule:
    previous_status: str
    resulting_status: str


TRANSITION_RULES = {
    BEGIN_REVIEW: TransitionRule(
        previous_status=SUBMITTED,
        resulting_status=UNDER_REVIEW,
    )
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


def _require_action_without_parameters() -> None:
    """Keep the server-owned target status out of the client request."""

    if request.content_length in (None, 0):
        return
    if not request.is_json or request.get_json(silent=True) != {}:
        abort(400, "Begin review does not accept a target status or other parameters.")


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
