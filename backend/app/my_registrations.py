"""An attendee's own registrations (SPL-117, CS-E19-S4).

What this module does
---------------------
``GET /api/my-registrations`` lists every registration the signed-in attendee has made, Registered
or Withdrawn (SPL-118), each with the event's current public details, soonest event first.
``GET /api/my-registrations/<id>`` opens one of them.

How it answers, in order
------------------------
1. Role: only accounts with the Attendee role (``require_roles``) -> 403; no session -> 401.
2. Ownership (AC5): every query is filtered by the signed-in account, so another attendee's
   registration is never returned. Opening one by id answers 404, the same as an unknown id.
3. Event details (AC2): read from the event *now*, not copied at registration time, so a later
   change to the date, times or description is what the attendee sees.
4. Public only (AC4): the event is shown through SPL-116's ``public_event`` (the same allowlist
   SPL-115 uses), plus the event's current status and its plain-language name (AC3), so a
   cancelled or postponed event is visible without exposing anything internal.
5. Order (AC1): soonest event first, then start time; registrations for the same event newest
   first (a Withdrawn one followed by a new registration shows the new one on top).

Nothing is written, so these routes cannot change any registration.
"""

from typing import Any

from flask import Flask, abort, g, jsonify
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.authorization import require_roles
from app.coordinator_assignment import MAX_EVENT_REQUEST_ID
from app.event_registrations import REGISTRATION_NOT_FOUND, public_event, serialize_registration
from app.event_statuses import status_label
from app.models import EventRegistration, EventRequest, Role


def register_my_registration_routes(app: Flask) -> None:
    @app.get("/api/my-registrations")
    @require_roles(Role.ATTENDEE)
    def list_my_registrations():
        """Every registration the signed-in attendee has made, soonest event first (AC1)."""

        with Session(app.extensions["engine"]) as session:
            # Step 2 (AC5). Only this attendee's rows; the event is loaded with each in one query.
            registrations = session.scalars(
                select(EventRegistration)
                .where(EventRegistration.attendee_account_id == g.user_id)
                .options(joinedload(EventRegistration.event_request))
            ).all()

            # Step 5 (AC1). Soonest event first. A higher id is a newer registration, so -id puts
            # the newest first when one attendee has several rows for the same event.
            registrations = sorted(
                registrations,
                key=lambda registration: (
                    registration.event_request.proposed_date,
                    registration.event_request.start_time,
                    registration.event_request.id,
                    -registration.id,
                ),
            )
            return jsonify(
                registrations=[_entry(session, registration) for registration in registrations]
            )

    @app.get("/api/my-registrations/<int:registration_id>")
    @require_roles(Role.ATTENDEE)
    def open_my_registration(registration_id: int):
        """One of the signed-in attendee's registrations, with the event's public details (AC4)."""

        # Ids above this cannot exist in an Integer column; answering 404 avoids a database error.
        if registration_id > MAX_EVENT_REQUEST_ID:
            abort(404, REGISTRATION_NOT_FOUND)
        with Session(app.extensions["engine"]) as session:
            # Step 2 (AC5). Filtering on the account means someone else's registration is simply
            # "not found", so ids cannot be probed (the same rule as SPL-118's withdraw).
            registration = session.scalar(
                select(EventRegistration)
                .where(
                    EventRegistration.id == registration_id,
                    EventRegistration.attendee_account_id == g.user_id,
                )
                .options(joinedload(EventRegistration.event_request))
            )
            if registration is None:
                abort(404, REGISTRATION_NOT_FOUND)
            return jsonify(_entry(session, registration))


def _entry(session: Session, registration: EventRegistration) -> dict[str, Any]:
    """One registration: what the attendee submitted, and the event as it stands now."""

    return {
        "registration": serialize_registration(registration),
        "event": attendee_event(session, registration.event_request),
    }


def attendee_event(session: Session, event: EventRequest) -> dict[str, Any]:
    """The event for an attendee who registered: public details plus its current status.

    Steps 3 and 4 (AC2, AC3, AC4). ``public_event`` reads the event's current values, so changes
    after registering show, and it is the single allowlist that keeps internal fields out. The
    status is added because AC3 needs it; only the plain-language name is shown alongside, never
    the organiser-facing explanation.
    """

    return {
        **public_event(session, event),
        "status": event.status,
        "status_label": status_label(event.status),
    }
