"""Per-type email settings for the signed-in account (SPL-126, CS-E20).

The account always comes from the verified session, never from the request, so one account cannot
read or change another's settings (AC5). Only types written for a role the account holds are
listed or changed. The settings govern email only; in-app notices are always on (AC4).
"""

from datetime import datetime
from typing import Any

from flask import Flask, abort, g, jsonify, request
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.authorization import require_roles
from app.event_requests import SINGAPORE
from app.models import (
    NOTIFICATION_TYPE_ROLES,
    ROLE_DISPLAY_NAMES,
    NotificationEmailOptOut,
    NotificationType,
)
from app.notifications import ALL_ROLES

TYPE_LABELS = {
    NotificationType.COORDINATOR_ASSIGNMENT: (
        "Assignment changes",
        "You are assigned to an event, or it is reassigned to someone else.",
    ),
    NotificationType.COORDINATOR_REQUESTS: (
        "Change requests and clarification replies",
        "An organiser submits a change request or answers your clarification request.",
    ),
    NotificationType.COORDINATOR_ARRANGEMENTS: (
        "Arrangement decisions",
        "Venue bookings are approved, rejected or flagged, and equipment is reserved, flagged or "
        "unavailable.",
    ),
    NotificationType.COORDINATOR_HOLD_DEADLINES: (
        "Venue hold deadlines",
        "A tentative venue hold is created, its deadline changes, or it expires.",
    ),
    NotificationType.COORDINATOR_SAFETY: (
        "Safety decisions",
        "The Safety Officer decides on an event's safety arrangement.",
    ),
    NotificationType.ORGANISER_REVIEW: (
        "Review outcomes",
        "Your event request is decided, returned for clarification or withdrawn.",
    ),
    NotificationType.ORGANISER_COORDINATOR: (
        "Coordinator changes",
        "An Event Coordinator takes on or takes over your event.",
    ),
    NotificationType.ORGANISER_CONFIRMATION: (
        "Confirmation and changes",
        "Your event is confirmed, returned to planning or cancelled, or a change request item is "
        "decided.",
    ),
    NotificationType.TECHNICAL_EQUIPMENT: (
        "Equipment requirement changes",
        "Equipment requirements are added, changed or removed, or an event needing equipment is "
        "cancelled.",
    ),
    NotificationType.VENUE_BOOKING_REQUESTS: (
        "Booking requests",
        "A venue booking is requested, or a request is withdrawn.",
    ),
    NotificationType.ATTENDEE_REGISTRATION: (
        "Registration receipts",
        "You register for an event or withdraw your registration.",
    ),
    NotificationType.ATTENDEE_EVENT_CHANGES: (
        "Registered event changes",
        "An event you registered for changes its date, time or venue, or is cancelled.",
    ),
}
if missing := set(NotificationType) - set(TYPE_LABELS):
    raise RuntimeError(f"Notification types without a label: {sorted(missing)}")


def register_notification_settings_routes(app: Flask) -> None:
    @app.get("/api/notification-settings")
    @require_roles(*ALL_ROLES)
    def list_my_notification_settings():
        with Session(app.extensions["engine"]) as session:
            off = _opted_out(session)
            return jsonify(types=[_serialize(kind, kind.value not in off) for kind in _my_types()])

    @app.put("/api/notification-settings/<notification_type>")
    @require_roles(*ALL_ROLES)
    def change_my_notification_setting(notification_type: str):
        # One refusal for an unknown type and a type for a role this account does not hold.
        kind = next((kind for kind in _my_types() if kind.value == notification_type), None)
        if kind is None:
            abort(404, "Notification type not found.")
        email = _email_setting()
        with Session(app.extensions["engine"]) as session:
            if email:
                session.execute(
                    delete(NotificationEmailOptOut).where(
                        NotificationEmailOptOut.account_id == g.user_id,
                        NotificationEmailOptOut.notification_type == kind.value,
                    )
                )
                session.commit()
            elif session.get(NotificationEmailOptOut, (g.user_id, kind.value)) is None:
                session.add(
                    NotificationEmailOptOut(
                        account_id=g.user_id,
                        notification_type=kind.value,
                        created_at=datetime.now(SINGAPORE),
                    )
                )
                try:
                    session.commit()
                except IntegrityError:
                    # A concurrent request turned it off first; the outcome is the same.
                    session.rollback()
            return jsonify(_serialize(kind, email))


def _my_types() -> list[NotificationType]:
    return [
        kind for kind in NotificationType if NOTIFICATION_TYPE_ROLES[kind].value in g.account_roles
    ]


def _opted_out(session: Session) -> set[str]:
    return set(
        session.scalars(
            select(NotificationEmailOptOut.notification_type).where(
                NotificationEmailOptOut.account_id == g.user_id
            )
        ).all()
    )


def _email_setting() -> bool:
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        abort(400, "A JSON object is required.")
    if unexpected := set(data) - {"email"}:
        abort(400, f"Unexpected setting field: {sorted(unexpected)[0]}.")
    if not isinstance(data.get("email"), bool):
        abort(400, "Email must be true or false.")
    return data["email"]


def _serialize(kind: NotificationType, email: bool) -> dict[str, Any]:
    label, description = TYPE_LABELS[kind]
    role = NOTIFICATION_TYPE_ROLES[kind]
    return {
        "type": kind.value,
        "label": label,
        "description": description,
        "role": role.value,
        "role_label": ROLE_DISPLAY_NAMES[role],
        "email": email,
    }
