"""Shared read model for organiser and coordinator registration lists."""

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import EventRegistration, EventRequest


def serialize_registration_attendee(registration: EventRegistration) -> dict[str, Any]:
    """Return the attendee details approved for an event's internal registration list."""

    return {
        "id": registration.id,
        "name": registration.name,
        "email": registration.email,
        "contact_number": registration.contact_number,
        "special_requirements": registration.special_requirements,
    }


def serialize_registration_list(session: Session, event: EventRequest) -> dict[str, Any]:
    """Return active and withdrawn registrations in deterministic signup order."""

    enabled = event.registration_opens_at is not None
    if not enabled:
        return {
            "enabled": False,
            "capacity": None,
            "registered_count": 0,
            "registered": [],
            "withdrawn": [],
        }

    registrations = session.scalars(
        select(EventRegistration)
        .where(EventRegistration.event_request_id == event.id)
        .order_by(EventRegistration.registered_at, EventRegistration.id)
    ).all()
    registered = [
        serialize_registration_attendee(row) for row in registrations if row.status == "registered"
    ]
    withdrawn = [
        serialize_registration_attendee(row) for row in registrations if row.status == "withdrawn"
    ]
    return {
        "enabled": True,
        "capacity": event.registration_capacity,
        "registered_count": len(registered),
        "registered": registered,
        "withdrawn": withdrawn,
    }
