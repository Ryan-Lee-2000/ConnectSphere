"""In-app notification inbox (SPL-101, CS-E20-S1).

Every account sees only the notices addressed to it. The recipient always comes from the verified
session, never from the request, so one account cannot read or change another's inbox.
"""

from datetime import datetime
from typing import Any

from flask import Flask, abort, g, jsonify
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session, joinedload

from app.authorization import require_roles
from app.event_requests import SINGAPORE
from app.models import Account, EventRequest, Notification, Role

# Event, role and organisation permissions are enforced where the linked record is opened, so a
# notice never grants access on its own.
ALL_ROLES = tuple(Role)
# notifications.id is a 32-bit integer; a larger path id cannot name a notice, and binding it
# would overflow the driver instead of answering "not found".
MAX_NOTIFICATION_ID = 2**31 - 1


def add_coordinator_assigned_notice(
    session: Session, event: EventRequest, coordinator_id: str, history_id: int
) -> None:
    """Notify a newly assigned coordinator, in the caller's transaction.

    The notice commits or rolls back with the assignment, so a refused assignment leaves none.
    The history row identifies this assignment, so a repeat of it cannot add a second notice.
    """

    session.add(
        Notification(
            recipient_account_id=coordinator_id,
            event_request_id=event.id,
            message=f"You have been assigned to {event.name}.",
            dedupe_key=f"coordinator_assigned:{history_id}",
            created_at=datetime.now(SINGAPORE),
        )
    )


def add_assignment_change_notices(
    session: Session,
    event: EventRequest,
    *,
    history_id: int,
    new_coordinator: Account,
    previous_coordinator: Account | None,
    already_notified: set[str],
) -> None:
    """Notify everyone else affected by an assignment or reassignment (SPL-134 AC5).

    Runs in the caller's transaction, after the new coordinator's own notice. Each account gets
    one notice per change: ``already_notified`` and the set grown here skip an account that holds
    more than one part in it (an organiser who is also the former coordinator, say), and the
    history row id in the dedupe key stops a retry adding a second.
    """

    notified = set(already_notified)
    now = datetime.now(SINGAPORE)

    def notify(recipient_id: str, message: str, kind: str) -> None:
        if recipient_id in notified:
            return
        notified.add(recipient_id)
        session.add(
            Notification(
                recipient_account_id=recipient_id,
                event_request_id=event.id,
                message=message,
                dedupe_key=f"{kind}:{history_id}",
                created_at=now,
            )
        )

    if previous_coordinator is not None:
        notify(
            previous_coordinator.id,
            f"You are no longer responsible for {event.name}. "
            f"It has been reassigned to {new_coordinator.display_name}.",
            "coordinator_removed",
        )
        organiser_message = (
            f"{new_coordinator.display_name} has taken over {event.name} from "
            f"{previous_coordinator.display_name} as the Event Coordinator responsible for it."
        )
    else:
        organiser_message = (
            f"{new_coordinator.display_name} is now the Event Coordinator responsible for "
            f"{event.name}."
        )
    notify(event.organiser_account_id, organiser_message, "organiser_coordinator_changed")


def register_notification_routes(app: Flask) -> None:
    @app.get("/api/notifications")
    @require_roles(*ALL_ROLES)
    def list_my_notifications():
        with Session(app.extensions["engine"]) as session:
            notifications = session.scalars(
                select(Notification)
                .where(Notification.recipient_account_id == g.user_id)
                .options(joinedload(Notification.event_request))
                .order_by(Notification.created_at.desc(), Notification.id.desc())
            ).all()
            return jsonify(
                notifications=[_serialize(notice) for notice in notifications],
                unread_count=_unread_count(session),
            )

    @app.post("/api/notifications/<int:notification_id>/read")
    @require_roles(*ALL_ROLES)
    def mark_notification_read(notification_id: int):
        if notification_id > MAX_NOTIFICATION_ID:
            abort(404, "Notification not found.")
        with Session(app.extensions["engine"]) as session:
            # One refusal for a missing notice and another account's notice.
            owned = session.scalar(
                select(Notification.id).where(
                    Notification.id == notification_id,
                    Notification.recipient_account_id == g.user_id,
                )
            )
            if owned is None:
                abort(404, "Notification not found.")
            _mark_read(session, Notification.id == notification_id)
            return jsonify(unread_count=_unread_count(session))

    @app.post("/api/notifications/read-all")
    @require_roles(*ALL_ROLES)
    def mark_all_notifications_read():
        with Session(app.extensions["engine"]) as session:
            _mark_read(session)
            return jsonify(unread_count=_unread_count(session))


def _mark_read(session: Session, *conditions) -> None:
    # Only unread rows are stamped, so reading twice keeps the first read time.
    session.execute(
        update(Notification)
        .where(
            Notification.recipient_account_id == g.user_id,
            Notification.read_at.is_(None),
            *conditions,
        )
        .values(read_at=datetime.now(SINGAPORE))
        .execution_options(synchronize_session=False)
    )
    session.commit()


def _unread_count(session: Session) -> int:
    return session.scalar(
        select(func.count())
        .select_from(Notification)
        .where(Notification.recipient_account_id == g.user_id, Notification.read_at.is_(None))
    )


def _serialize(notice: Notification) -> dict[str, Any]:
    return {
        "id": notice.id,
        "message": notice.message,
        "event": {"id": notice.event_request_id, "name": notice.event_request.name},
        "link": _event_link(notice),
        "created_at": _timestamp(notice.created_at),
        "read": notice.read_at is not None,
    }


def _event_link(notice: Notification) -> str:
    # The notice kind is the dedupe key's prefix. Notices written for the organiser open the
    # organisation event page; the coordinator-only page would send them back to the workspace.
    # Both pages stay behind their own role and ownership checks on the server.
    kind = notice.dedupe_key.split(":", 1)[0]
    page = "organisation-events" if kind.startswith("organiser_") else "assigned-events"
    return f"/workspace/{page}/{notice.event_request_id}"


def _timestamp(value: datetime) -> str:
    # SQLite drops the offset, so stamp the known zone back (matches the other serialisers).
    return (value if value.tzinfo else value.replace(tzinfo=SINGAPORE)).isoformat()
