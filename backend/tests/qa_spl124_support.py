"""Shared helpers for the SPL-124 QA files (not a test module)."""

from datetime import datetime

from app.event_requests import SINGAPORE
from app.models import EventRegistration, Notification
from sqlalchemy import select
from sqlalchemy.orm import Session


def registrations(app, event, registered, withdrawn):
    """Store one Registered and one Withdrawn registration directly.

    These harnesses' events are not open for registration, so the route cannot be used.
    """

    now = datetime.now(SINGAPORE)
    with Session(app.extensions["engine"]) as session:
        for account, status in ((registered, "registered"), (withdrawn, "withdrawn")):
            session.add(
                EventRegistration(
                    event_request_id=event,
                    attendee_account_id=account,
                    status=status,
                    name="QA attendee",
                    email="qa@example.test",
                    contact_number="91234567",
                    registered_at=now,
                    withdrawn_at=now if status == "withdrawn" else None,
                )
            )
        session.commit()


def attendee_notices(app, account):
    with Session(app.extensions["engine"]) as session:
        return session.scalars(
            select(Notification.message)
            .where(
                Notification.recipient_account_id == account,
                Notification.dedupe_key.like("attendee_%"),
            )
            .order_by(Notification.id)
        ).all()
