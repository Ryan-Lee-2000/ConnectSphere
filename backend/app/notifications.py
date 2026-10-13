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
from app.models import EventRequest, Notification, Role

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
        "created_at": _timestamp(notice.created_at),
        "read": notice.read_at is not None,
    }


def _timestamp(value: datetime) -> str:
    # SQLite drops the offset, so stamp the known zone back (matches the other serialisers).
    return (value if value.tzinfo else value.replace(tzinfo=SINGAPORE)).isoformat()
