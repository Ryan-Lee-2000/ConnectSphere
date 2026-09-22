"""Coordinator assignment routes for Sprint 1 stories SPL-59 through SPL-61.

These operate on the CS-E03 `event_requests` aggregate and the CS-E07-S1 status vocabulary.
Assignment is the first thing that moves a request off `submitted`, so it also stamps
`status_changed_at`.
"""

import uuid
from datetime import date, datetime
from typing import Any

from flask import Flask, abort, g, jsonify, request
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.authorization import require_roles
from app.event_requests import SINGAPORE
from app.event_statuses import EVENT_REQUEST_STATUSES
from app.models import (
    Account,
    AccountRole,
    EventCoordinatorAssignment,
    EventCoordinatorHistory,
    EventRequest,
    Role,
)

SUBMITTED = "submitted"
UNDER_REVIEW = "under_review"
NON_REASSIGNABLE_STATUSES = frozenset({"completed", "cancelled", "rejected", "withdrawn"})
# CS-E07-S1 owns the vocabulary; fail at import if a value used here ever leaves it.
assert {SUBMITTED, UNDER_REVIEW} | NON_REASSIGNABLE_STATUSES <= set(EVENT_REQUEST_STATUSES)

ALREADY_ASSIGNED = "This event already has an Event Coordinator. Reassign it instead."
NO_COORDINATOR_AVAILABLE = (
    "No active Event Coordinator is available, so this event cannot be assigned yet."
)
NO_OTHER_COORDINATOR_AVAILABLE = (
    "No other active Event Coordinator is available, so this event cannot be reassigned yet."
)


def register_coordinator_assignment_routes(app: Flask) -> None:
    @app.get("/api/event-requests/awaiting-assignment")
    @require_roles(Role.EVENT_OPERATIONS_MANAGER)
    def list_events_awaiting_assignment():
        with Session(app.extensions["engine"]) as session:
            events = session.scalars(
                select(EventRequest)
                .outerjoin(EventCoordinatorAssignment)
                .where(
                    EventRequest.status == SUBMITTED,
                    EventCoordinatorAssignment.event_request_id.is_(None),
                )
                # Oldest submission first. Requests stored before CS-E03-S5 carry no submission
                # time; they sort last by id rather than first, which NULL ordering would differ
                # on between PostgreSQL and SQLite.
                .order_by(
                    EventRequest.submitted_at.is_(None),
                    EventRequest.submitted_at,
                    EventRequest.id,
                )
            ).all()
            return jsonify(
                events=[_serialize_queue_event(event) for event in events], count=len(events)
            )

    @app.get("/api/event-requests/<int:event_request_id>/coordinator-options")
    @require_roles(Role.EVENT_OPERATIONS_MANAGER)
    def list_coordinator_options(event_request_id: int):
        with Session(app.extensions["engine"]) as session:
            _find_event_request(session, event_request_id)
            current = _current_assignment(session, event_request_id)
            current_id = current.coordinator_account_id if current else None
            coordinators = _active_coordinators(session, excluding=current_id)
            unavailable_reason = None
            if not coordinators:
                unavailable_reason = (
                    NO_OTHER_COORDINATOR_AVAILABLE if current else NO_COORDINATOR_AVAILABLE
                )
            return jsonify(
                coordinators=[_serialize_account(account) for account in coordinators],
                current_coordinator=(
                    _serialize_account(session.get(Account, current_id)) if current_id else None
                ),
                unavailable_reason=unavailable_reason,
            )

    @app.post("/api/event-requests/<int:event_request_id>/coordinator")
    @require_roles(Role.EVENT_OPERATIONS_MANAGER)
    def assign_coordinator(event_request_id: int):
        coordinator_id = _requested_coordinator_id()
        with Session(app.extensions["engine"]) as session:
            event = _find_event_request(session, event_request_id)
            if _current_assignment(session, event_request_id) is not None:
                abort(409, ALREADY_ASSIGNED)
            if event.status != SUBMITTED:
                abort(409, "Only submitted events can be assigned an Event Coordinator.")
            coordinator = _chosen_coordinator(
                session, coordinator_id, current_id=None, unavailable=NO_COORDINATOR_AVAILABLE
            )
            now = datetime.now(SINGAPORE)
            try:
                # The assignment key and the conditional status change both reject a concurrent
                # assignment that passed the checks above, so the first commit always wins.
                session.add(
                    EventCoordinatorAssignment(
                        event_request_id=event_request_id,
                        coordinator_account_id=coordinator.id,
                        assigned_by_account_id=g.user_id,
                        assigned_at=now,
                    )
                )
                session.add(
                    EventCoordinatorHistory(
                        event_request_id=event_request_id,
                        new_coordinator_account_id=coordinator.id,
                        changed_by_account_id=g.user_id,
                        changed_at=now,
                    )
                )
                transitioned = session.execute(
                    update(EventRequest)
                    .where(EventRequest.id == event_request_id, EventRequest.status == SUBMITTED)
                    .values(status=UNDER_REVIEW, status_changed_at=now)
                )
                if transitioned.rowcount != 1:
                    abort(409, ALREADY_ASSIGNED)
                session.commit()
            except IntegrityError:
                session.rollback()
                abort(409, ALREADY_ASSIGNED)
            return jsonify(assignment=_serialize_assignment(session, event_request_id)), 201

    @app.put("/api/event-requests/<int:event_request_id>/coordinator")
    @require_roles(Role.EVENT_OPERATIONS_MANAGER)
    def reassign_coordinator(event_request_id: int):
        coordinator_id = _requested_coordinator_id()
        with Session(app.extensions["engine"]) as session:
            event = _find_event_request(session, event_request_id)
            current = _current_assignment(session, event_request_id)
            if current is None:
                abort(409, "This event has no Event Coordinator to reassign. Assign one first.")
            if event.status in NON_REASSIGNABLE_STATUSES:
                abort(
                    409, "Completed, cancelled, rejected or withdrawn events cannot be reassigned."
                )
            previous_id = current.coordinator_account_id
            coordinator = _chosen_coordinator(
                session,
                coordinator_id,
                current_id=previous_id,
                unavailable=NO_OTHER_COORDINATOR_AVAILABLE,
            )
            now = datetime.now(SINGAPORE)
            reassigned = session.execute(
                _reassignment_statement(
                    event_request_id,
                    previous_id=previous_id,
                    coordinator_id=coordinator.id,
                    actor_id=g.user_id,
                    now=now,
                )
            )
            if reassigned.rowcount != 1:
                session.rollback()
                abort(409, _reassignment_refusal(session, event_request_id))
            session.add(
                EventCoordinatorHistory(
                    event_request_id=event_request_id,
                    previous_coordinator_account_id=previous_id,
                    new_coordinator_account_id=coordinator.id,
                    changed_by_account_id=g.user_id,
                    changed_at=now,
                )
            )
            session.commit()
            return jsonify(assignment=_serialize_assignment(session, event_request_id))

    @app.get("/api/event-requests/<int:event_request_id>/coordinator-history")
    @require_roles(Role.EVENT_OPERATIONS_MANAGER)
    def list_coordinator_history(event_request_id: int):
        with Session(app.extensions["engine"]) as session:
            _find_event_request(session, event_request_id)
            entries = session.scalars(
                select(EventCoordinatorHistory)
                .where(EventCoordinatorHistory.event_request_id == event_request_id)
                .order_by(EventCoordinatorHistory.changed_at, EventCoordinatorHistory.id)
            ).all()
            account_ids = {
                account_id
                for entry in entries
                for account_id in (
                    entry.previous_coordinator_account_id,
                    entry.new_coordinator_account_id,
                    entry.changed_by_account_id,
                )
                if account_id
            }
            accounts = {
                account.id: account
                for account in session.scalars(select(Account).where(Account.id.in_(account_ids)))
            }
            return jsonify(history=[_serialize_history(entry, accounts) for entry in entries])


def is_assigned_coordinator(session: Session, event_request_id: int, account_id: str) -> bool:
    """Whether the account currently holds responsibility (and edit rights) for the request."""

    assignment = _current_assignment(session, event_request_id)
    return assignment is not None and assignment.coordinator_account_id == account_id


def _reassignment_statement(
    event_request_id: int, *, previous_id: str, coordinator_id: str, actor_id: str, now: datetime
):
    """Reassign only while the coordinator is unchanged and the request is still reassignable.

    Both conditions belong in the statement: a status read before the write would let a
    concurrent transition to a terminal status slip through.
    """

    still_reassignable = (
        select(EventRequest.id)
        .where(
            EventRequest.id == event_request_id,
            EventRequest.status.not_in(sorted(NON_REASSIGNABLE_STATUSES)),
        )
        .exists()
    )
    return (
        update(EventCoordinatorAssignment)
        .where(
            EventCoordinatorAssignment.event_request_id == event_request_id,
            EventCoordinatorAssignment.coordinator_account_id == previous_id,
            still_reassignable,
        )
        .values(
            coordinator_account_id=coordinator_id,
            assigned_by_account_id=actor_id,
            assigned_at=now,
        )
        .execution_options(synchronize_session=False)
    )


def _reassignment_refusal(session: Session, event_request_id: int) -> str:
    """Explain which of the statement's conditions a competing transaction changed."""

    event = session.get(EventRequest, event_request_id)
    if event is None or event.status in NON_REASSIGNABLE_STATUSES:
        return "Completed, cancelled, rejected or withdrawn events cannot be reassigned."
    return "The Event Coordinator changed while you were reassigning. Try again."


def _requested_coordinator_id() -> str:
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        abort(400, "A JSON object is required.")
    unexpected = set(data) - {"coordinator_account_id"}
    if unexpected:
        abort(400, f"Unexpected assignment field: {sorted(unexpected)[0]}.")
    value = data.get("coordinator_account_id")
    try:
        return str(uuid.UUID(value))
    except (TypeError, ValueError, AttributeError):
        abort(400, "Choose an Event Coordinator.")


def _find_event_request(session: Session, event_request_id: int) -> EventRequest:
    event = session.get(EventRequest, event_request_id)
    if event is None:
        abort(404, "Event request not found.")
    return event


def _current_assignment(
    session: Session, event_request_id: int
) -> EventCoordinatorAssignment | None:
    return session.get(EventCoordinatorAssignment, event_request_id)


def _active_coordinators(session: Session, *, excluding: str | None) -> list[Account]:
    query = (
        select(Account)
        .join(AccountRole, AccountRole.account_id == Account.id)
        .where(AccountRole.role == Role.EVENT_COORDINATOR.value, Account.is_active.is_(True))
        .order_by(Account.display_name, Account.id)
    )
    if excluding is not None:
        query = query.where(Account.id != excluding)
    return list(session.scalars(query).all())


def _chosen_coordinator(
    session: Session, coordinator_id: str, *, current_id: str | None, unavailable: str
) -> Account:
    candidates = _active_coordinators(session, excluding=current_id)
    if not candidates:
        abort(409, unavailable)
    if coordinator_id == current_id:
        abort(400, "Choose a different Event Coordinator from the current one.")
    for candidate in candidates:
        if candidate.id == coordinator_id:
            return candidate
    abort(400, "Choose an active Event Coordinator from the list.")


def _serialize_queue_event(event: EventRequest) -> dict[str, Any]:
    return {
        "id": event.id,
        "name": event.name,
        "organisation_id": event.organisation_id,
        "organisation_name": event.organisation.name,
        "proposed_date": _date(event.proposed_date),
        "submitted_at": _timestamp(event.submitted_at),
    }


def _serialize_assignment(session: Session, event_request_id: int) -> dict[str, Any]:
    assignment = session.get(EventCoordinatorAssignment, event_request_id)
    event = session.get(EventRequest, event_request_id)
    return {
        "event_request_id": event_request_id,
        "status": event.status,
        "coordinator": _serialize_account(session.get(Account, assignment.coordinator_account_id)),
        "assigned_by": _serialize_account(session.get(Account, assignment.assigned_by_account_id)),
        "assigned_at": _timestamp(assignment.assigned_at),
    }


def _serialize_history(
    entry: EventCoordinatorHistory, accounts: dict[str, Account]
) -> dict[str, Any]:
    previous_id = entry.previous_coordinator_account_id
    return {
        "id": entry.id,
        "previous_coordinator": _serialize_account(accounts[previous_id]) if previous_id else None,
        "new_coordinator": _serialize_account(accounts[entry.new_coordinator_account_id]),
        "changed_by": _serialize_account(accounts[entry.changed_by_account_id]),
        "changed_at": _timestamp(entry.changed_at),
    }


def _serialize_account(account: Account) -> dict[str, Any]:
    return {"id": account.id, "name": account.display_name}


def _date(value: date | None) -> str | None:
    return value.isoformat() if value else None


def _timestamp(value: datetime | None) -> str | None:
    """Match CS-E03-S5's representation: SQLite drops the offset, so stamp the known zone back."""

    if value is None:
        return None
    return (value if value.tzinfo else value.replace(tzinfo=SINGAPORE)).isoformat()
