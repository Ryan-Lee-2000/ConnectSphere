"""The equipment review queue Technical Support works from (SPL-92).

What this story is, and what it deliberately is not
---------------------------------------------------
A work view. AC4 is explicit that opening the queue or adding a note must not reserve stock,
change a line's status or message the organiser, so every route here either reads, or writes only
to ``equipment_review_notes``. No requirement line is ever mutated. That is also why the notes
live in their own table rather than as a column on the line.

Who sees what (AC5)
-------------------
The queue is Technical Support's. The assigned coordinator never opens it, but does read the notes
on their own event's lines, because AC3 says a note has to reach them. That is one extra route
with an ownership filter, not a share of the queue.

Why a line "awaiting review" is defined twice over
--------------------------------------------------
A line is in the queue when *both* the line and its event are active: the line is Requested or
Review Required (AC1), and the event is In planning, Confirmed or Postponed (AC1). Lines on
Completed or Cancelled events are not work, and neither are lines on an event that has not
reached planning yet.
"""

from datetime import datetime
from typing import Any

from flask import Flask, abort, g, jsonify, request
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.authorization import require_roles
from app.coordinator_assignment import is_assigned_coordinator
from app.event_requests import SINGAPORE
from app.event_statuses import status_label
from app.models import (
    MAX_REVIEW_NOTE_LENGTH,
    Account,
    EquipmentRequirement,
    EquipmentReviewNote,
    EquipmentType,
    EventCoordinatorAssignment,
    EventRequest,
    Role,
)

# AC1. A line is work when it has been requested, or when something made it need another look.
QUEUED_LINE_STATUSES = ("requested", "review_required")

# AC1. An event whose equipment still matters. Completed and Cancelled are named by the story;
# the earlier statuses are events that have not reached planning, so their lines are not yet work.
ACTIVE_EVENT_STATUSES = ("planning", "confirmed", "postponed")

NOT_FOUND = "Equipment requirement not found."
MAX_REQUIREMENT_ID = 2**31 - 1


def _now() -> datetime:
    """The single clock for this module, so tests can freeze it."""

    return datetime.now(SINGAPORE)


def register_equipment_review_queue_routes(app: Flask) -> None:
    """Register the Technical Support review queue and the coordinator's note read."""

    @app.get("/api/equipment-review-queue")
    @require_roles(Role.TECHNICAL_SUPPORT_STAFF)
    def list_equipment_review_queue():
        """Every line awaiting review, earliest required start first (AC1, AC2)."""

        with Session(app.extensions["engine"]) as session:
            lines = _queued_lines(session)
            coordinators = _coordinators_for(session, [line.event_request_id for line in lines])
            return jsonify(
                requirements=[
                    _serialize_line(line, coordinators.get(line.event_request_id)) for line in lines
                ]
            )

    @app.get("/api/equipment-review-queue/<int:requirement_id>")
    @require_roles(Role.TECHNICAL_SUPPORT_STAFF)
    def show_equipment_review_queue_entry(requirement_id: int):
        """One line, plus its technical notes and review notes (AC2)."""

        with Session(app.extensions["engine"]) as session:
            line = _queued_line(session, requirement_id)
            coordinators = _coordinators_for(session, [line.event_request_id])
            detail = _serialize_line(line, coordinators.get(line.event_request_id))
            detail["notes"] = line.notes
            detail["review_notes"] = [
                _serialize_note(note) for note in _notes_for(session, line.id)
            ]
            return jsonify(requirement=detail)

    @app.post("/api/equipment-review-queue/<int:requirement_id>/notes")
    @require_roles(Role.TECHNICAL_SUPPORT_STAFF)
    def add_equipment_review_note(requirement_id: int):
        """Save a review note or clarification question against a line (AC3).

        The only write in this story, and it touches only this table: the line it is about is read
        to check it is in the queue, and then left exactly as it was (AC4).
        """

        note_text = _note_text()
        with Session(app.extensions["engine"]) as session:
            line = _queued_line(session, requirement_id)
            note = EquipmentReviewNote(
                equipment_requirement_id=line.id,
                note=note_text,
                author_account_id=g.user_id,
                created_at=_now(),
            )
            session.add(note)
            session.commit()
            session.refresh(note)
            return jsonify(note=_serialize_note(note)), 201

    @app.get("/api/equipment-requirements/<int:requirement_id>/review-notes")
    @require_roles(Role.TECHNICAL_SUPPORT_STAFF, Role.EVENT_COORDINATOR)
    def read_equipment_review_notes(requirement_id: int):
        """The notes on one line, oldest first (AC3, AC5).

        Technical Support may read any line's notes. A coordinator may read only their own event's
        lines, and anything else answers exactly like an unknown line, so trying ids reveals
        nothing about other people's events.
        """

        with Session(app.extensions["engine"]) as session:
            line = _any_line(session, requirement_id)
            if Role.TECHNICAL_SUPPORT_STAFF.value not in g.account_roles:
                if not is_assigned_coordinator(session, line.event_request_id, g.user_id):
                    abort(404, NOT_FOUND)
            return jsonify(
                review_notes=[_serialize_note(note) for note in _notes_for(session, line.id)]
            )


def _queue_statement():
    """The one definition of "awaiting review", so the list and the detail cannot disagree."""

    return (
        select(EquipmentRequirement)
        .join(EventRequest)
        .options(
            joinedload(EquipmentRequirement.catalogue_type),
            joinedload(EquipmentRequirement.event_request),
        )
        .where(
            EquipmentRequirement.status.in_(QUEUED_LINE_STATUSES),
            EventRequest.status.in_(ACTIVE_EVENT_STATUSES),
        )
    )


def _queued_lines(session: Session) -> list[EquipmentRequirement]:
    return list(
        session.scalars(
            _queue_statement().order_by(
                # AC1's order, then two tie-breaks so two identical requests never disagree.
                EquipmentRequirement.required_start_date,
                EquipmentRequirement.event_request_id,
                EquipmentRequirement.id,
            )
        ).unique()
    )


def _queued_line(session: Session, requirement_id: int) -> EquipmentRequirement:
    """A line that is actually in the queue, or 404.

    A line that exists but is not awaiting review answers like one that does not exist: the queue
    is the subject here, so "not in the queue" and "not a line" are the same answer.
    """

    if requirement_id > MAX_REQUIREMENT_ID:
        abort(404, NOT_FOUND)
    line = session.scalar(_queue_statement().where(EquipmentRequirement.id == requirement_id))
    if line is None:
        abort(404, NOT_FOUND)
    return line


def _any_line(session: Session, requirement_id: int) -> EquipmentRequirement:
    """Any line, queued or not: a coordinator reads notes on their line whatever its status."""

    if requirement_id > MAX_REQUIREMENT_ID:
        abort(404, NOT_FOUND)
    line = session.get(EquipmentRequirement, requirement_id)
    if line is None:
        abort(404, NOT_FOUND)
    return line


def _notes_for(session: Session, requirement_id: int) -> list[EquipmentReviewNote]:
    """Oldest first: the notes read as the conversation they are."""

    return list(
        session.scalars(
            select(EquipmentReviewNote)
            .options(joinedload(EquipmentReviewNote.author))
            .where(EquipmentReviewNote.equipment_requirement_id == requirement_id)
            .order_by(EquipmentReviewNote.created_at, EquipmentReviewNote.id)
        ).unique()
    )


def _coordinators_for(session: Session, event_ids: list[int]) -> dict[int, Account]:
    """The assigned coordinator of each event, in one query rather than one per line (AC2)."""

    if not event_ids:
        return {}
    rows = session.execute(
        select(EventCoordinatorAssignment.event_request_id, Account)
        .join(Account, Account.id == EventCoordinatorAssignment.coordinator_account_id)
        .where(EventCoordinatorAssignment.event_request_id.in_(set(event_ids)))
    ).all()
    return {event_id: account for event_id, account in rows}


def _note_text() -> str:
    """AC3: a note, and nothing else, and not a blank one."""

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        abort(400, "A JSON object is required.")
    unexpected = set(data) - {"note"}
    if unexpected:
        abort(400, f"Unexpected field: {sorted(unexpected)[0]}.")
    note = data.get("note")
    if not isinstance(note, str) or not note.strip():
        abort(400, "A note is required.")
    note = note.strip()
    if len(note) > MAX_REVIEW_NOTE_LENGTH:
        abort(400, f"Keep the note to {MAX_REVIEW_NOTE_LENGTH} characters or fewer.")
    return note


def _serialize_line(line: EquipmentRequirement, coordinator: Account | None) -> dict[str, Any]:
    """What Technical Support needs to act on one line (AC2), and nothing more."""

    event = line.event_request
    return {
        "id": line.id,
        "event": {
            "id": event.id,
            "name": event.name,
            "date": event.proposed_date.isoformat() if event.proposed_date else None,
            "status": event.status,
            # The plain-language name, the same wording the organiser sees.
            "status_label": status_label(event.status),
        },
        "coordinator": _serialize_account(coordinator),
        # The organiser's own words are kept whether or not the line has been mapped, so a
        # reviewer can always see what was actually asked for.
        "organiser_equipment_text": line.equipment_type,
        "equipment_type": _serialize_equipment_type(line.catalogue_type),
        # AC2: a line never mapped to the catalogue is work in itself, so it says so plainly
        # rather than leaving the reader to infer it from a null.
        "needs_mapping": line.equipment_type_id is None,
        "quantity": line.quantity,
        "required_start_date": (
            line.required_start_date.isoformat() if line.required_start_date else None
        ),
        "required_end_date": (
            line.required_end_date.isoformat() if line.required_end_date else None
        ),
        "status": line.status,
    }


def _serialize_note(note: EquipmentReviewNote) -> dict[str, Any]:
    return {
        "id": note.id,
        "note": note.note,
        "author": _serialize_account(note.author),
        "created_at": note.created_at.isoformat() if note.created_at else None,
    }


def _serialize_account(account: Account | None) -> dict[str, Any] | None:
    if account is None:
        return None
    return {"id": account.id, "display_name": account.display_name}


def _serialize_equipment_type(equipment_type: EquipmentType | None) -> dict[str, Any] | None:
    if equipment_type is None:
        return None
    return {
        "id": equipment_type.id,
        "name": equipment_type.name,
        "location": equipment_type.location,
    }
