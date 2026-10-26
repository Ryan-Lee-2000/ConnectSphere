"""Event completion (SPL-105): the assigned coordinator closes an event after it has taken place.

* AC1 - only a Preparing event (safety approved, Week 7 change 6) can be completed, and only at or
  after its end: the latest end across the event and its Approved venue bookings, in Singapore
  time. Setup and turnaround buffers are venue occupancy, not the event, so they are excluded.
* AC2 - every other status, and any time before the end, is refused with the reason.
* AC3 - the event lock refuses with 404 unless the caller is the assigned coordinator, so other
  coordinators never learn the event exists; every other role is refused by role.
* AC4 - the status change, its history row and who/when/note are written in one transaction.

Completed is already inactive and final (event_statuses.py), which is what keeps the event
read-only for AC5 and visible to its existing readers for AC6. Completion sends no notice.
"""

from datetime import datetime
from typing import Any

from flask import Flask, abort, g, jsonify, request
from sqlalchemy import update
from sqlalchemy.orm import Session

from app.authorization import require_roles
from app.models import Account, EventRequest, Role

APPROVED = "approved"
COMPLETED = "completed"
CONFIRMED = "confirmed"
PREPARING = "preparing"
MAX_NOTE_LENGTH = 2000
ALREADY_COMPLETED = "This event is already completed."
NOT_SAFETY_APPROVED = (
    "This event has not entered Preparation after safety approval, so it cannot be completed."
)
END_NOT_RECORDED = "This event's end time is not recorded, so it cannot be completed."


def register_event_completion_routes(app: Flask) -> None:
    # Imported here: event_review imports coordinator_assignment, which imports event_requests.
    from app.coordinator_assignment import MAX_EVENT_REQUEST_ID
    from app.event_review import (
        COMPLETE,
        InvalidStatusTransition,
        _serialize_event,
        _serialize_transition,
        transition_event_status,
    )
    from app.event_statuses import status_label
    from app.exact_venue_bookings import lock_event

    @app.post("/api/event-requests/<int:event_request_id>/complete")
    @require_roles(Role.EVENT_COORDINATOR)
    def complete_event(event_request_id: int):
        """The assigned coordinator marks an event that has taken place as completed."""

        # Validate the body first, so an invalid request never reaches the database.
        note = _closing_note()
        if event_request_id > MAX_EVENT_REQUEST_ID:
            abort(404, "Assigned event not found.")
        with Session(app.extensions["engine"]) as session:
            # The row lock makes a simultaneous completion or cancellation wait, then see the
            # status the first one committed.
            event = lock_event(session, event_request_id, g.user_id)
            if event.status == COMPLETED:
                abort(409, ALREADY_COMPLETED)
            if event.status == CONFIRMED:
                abort(409, NOT_SAFETY_APPROVED)
            if event.status != PREPARING:
                label = status_label(event.status).lower()
                abort(409, f"This event is {label} and cannot be completed.")
            ends_at = event_end(event)
            if ends_at is None:
                abort(409, END_NOT_RECORDED)
            now = _now()
            if now < ends_at:
                abort(409, f"This event can be completed from {_format_time(ends_at)}.")
            try:
                audit = transition_event_status(
                    session,
                    event_request_id=event_request_id,
                    action=COMPLETE,
                    actor_account_id=g.user_id,
                    changed_at=now,
                )
            except InvalidStatusTransition:
                session.rollback()
                abort(409, "This event cannot be completed in its current status.")
            session.execute(
                update(EventRequest)
                .where(EventRequest.id == event_request_id)
                .values(completed_by_account_id=g.user_id, completed_at=now, completion_note=note)
                .execution_options(synchronize_session=False)
            )
            session.commit()
            actor = session.get(Account, g.user_id)
            session.expire_all()
            event = session.get(EventRequest, event_request_id)
            return jsonify(
                event={**_serialize_event(event), **serialize_completion(event, include_note=True)},
                transition=_serialize_transition(audit, actor),
                message="Event completed. It is now closed as a historical record.",
            )


def event_end(event: EventRequest) -> datetime | None:
    """The latest end across the event's own times and its Approved bookings (AC1).

    None when the event's own end is not recorded, or a booking's stored timing cannot be read,
    because completing on a guessed end could close an event that is still running.
    """

    from app.event_requests import SINGAPORE
    from app.exact_venue_bookings import interval_from_json

    if event.proposed_date is None or event.end_time is None:
        return None
    ends = [datetime.combine(event.proposed_date, event.end_time, tzinfo=SINGAPORE)]
    for booking in event.venue_bookings:
        # A slot-era booking has no times of its own; the event's times already cover it.
        if booking.status != APPROVED or not booking.exact_timing:
            continue
        try:
            ends.append(interval_from_json(booking.exact_timing["event"]).end)
        except (KeyError, TypeError, ValueError):
            return None
    return max(ends)


def serialize_completion(event: EventRequest, *, include_note: bool = False) -> dict[str, Any]:
    """Who completed the event and when; the closing note only for the assigned coordinator."""

    from app.event_requests import _singapore_time

    completion = {
        "completed_by": (
            {"id": event.completer.id, "name": event.completer.display_name}
            if event.completer
            else None
        ),
        "completed_at": _singapore_time(event.completed_at) if event.completed_at else None,
    }
    if include_note:
        completion["completion_note"] = event.completion_note
    return completion


def completion_available_at(event: EventRequest) -> str | None:
    """When the coordinator may complete the event, so the panel can say so before the end."""

    from app.event_requests import _singapore_time

    ends_at = event_end(event)
    return _singapore_time(ends_at) if ends_at else None


def _now() -> datetime:
    """The current Singapore time; separate so tests can freeze the clock at the boundary."""

    from app.event_requests import SINGAPORE

    return datetime.now(SINGAPORE)


def _format_time(value: datetime) -> str:
    from app.event_requests import SINGAPORE

    local = value.astimezone(SINGAPORE)
    return f"{local.day} {local:%b %Y, %H:%M} SGT"


def _closing_note() -> str | None:
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or not set(data) <= {"note"}:
        abort(400, "Send only an optional closing note.")
    note = data.get("note")
    if note is None:
        return None
    if not isinstance(note, str):
        abort(400, "The closing note must be text.")
    if len(note.strip()) > MAX_NOTE_LENGTH:
        abort(400, f"Keep the closing note to {MAX_NOTE_LENGTH} characters or fewer.")
    return note.strip() or None
