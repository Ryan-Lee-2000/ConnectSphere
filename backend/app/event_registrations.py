"""Attendee registration for an open event (SPL-116, CS-E19-S3).

What this module does
---------------------
A signed-in attendee registers for an event whose registration is open (SPL-114 set the period and
the capacity). They give their name, email address and contact number, plus any special
requirements, and take one place. The registration is stored with status Registered.

How a registration is checked (``POST /api/event-requests/<id>/registrations``), in order
------------------------------------------------------------------------------------------
1. Role: only accounts with the Attendee role (``require_roles``) -> 403; no session -> 401 (AC4).
2. Public: the event must be Confirmed with registration enabled -> otherwise 404, the same answer
   as an unknown id, so an attendee cannot discover events that are not public (AC4).
3. Open: "now" must be inside the registration period -> otherwise 409 (AC4).
4. Details: exactly name, email, contact_number and an optional special_requirements; the three
   required ones not blank; the email in the form name@domain -> otherwise 400 naming the field
   (AC2).
5. Not already Registered for this event -> otherwise 409 (AC5).
6. A place left -> otherwise 409 "This event is full." (AC3).
7. Save one Registered row (AC1) and answer 201 with the confirmation (AC7).

Steps 2-7 run while holding a lock on the event's row, so two attendees racing for the last place
are handled one after the other: the second one sees the event is full (AC6). Every refusal
happens before anything is written, so "nothing is saved" holds for every refusal.

How a withdrawal is checked (SPL-118, ``POST /api/registrations/<id>/withdraw``), in order
-------------------------------------------------------------------------------------------
1. Role: Attendee only -> 403; no session -> 401. No request fields: the status and the time are
   set by the server -> otherwise 400.
2. Own registration: someone else's, or an unknown id, gets the same 404 (SPL-118 AC3).
3. Still Registered -> otherwise 409 "already withdrawn" (AC3).
4. Before the event starts (its date and start time, Singapore time) -> otherwise 409 (AC1, AC3).
5. Mark it Withdrawn with the time (AC2). The row is kept as history, and because places remaining
   only counts Registered rows, the place is free again at once (AC2).

Steps 2-5 run while holding a lock on the registration's row, so two simultaneous withdrawals of
the same registration are handled one after the other: the second one sees it is already
withdrawn, and the place is freed exactly once.
"""

import re
from typing import Any

from flask import Flask, abort, g, jsonify, make_response, request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import registration_settings as settings
from app.authorization import require_roles
from app.coordinator_assignment import MAX_EVENT_REQUEST_ID
from app.models import EventRegistration, EventRequest, Role, Venue, VenueBooking
from app.validation import request_json

CONFIRMED = "confirmed"
REGISTERED = "registered"
WITHDRAWN = "withdrawn"
# The four keys a registration accepts, with the human name used in error messages.
DETAILS = {
    "name": "Name",
    "email": "Email address",
    "contact_number": "Contact number",
    "special_requirements": "Special requirements",
}
REQUIRED = ("name", "email", "contact_number")
# name@domain.tld: something before the @, something after it with a dot, and no spaces anywhere.
# Deliberately simple: the story asks for the form name@domain, not full RFC 5322 validation.
EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")
NOT_FOUND = "Event not found."
NOT_OPEN = "Registration is not open for this event."
ONLY_DETAILS = "A registration accepts only name, email, contact_number and special_requirements."
ALREADY_REGISTERED = "You are already registered for this event."
FULL = "This event is full."
# SPL-118 messages.
REGISTRATION_NOT_FOUND = "Registration not found."
ALREADY_WITHDRAWN = "This registration is already withdrawn."
EVENT_STARTED = "This event has already started."
NO_WITHDRAWAL_FIELDS = "Withdrawing accepts no fields; the status and time are set by the server."


def register_event_registration_routes(app: Flask) -> None:
    @app.post("/api/event-requests/<int:event_request_id>/registrations")
    @require_roles(Role.ATTENDEE)
    def register_for_event(event_request_id: int):
        """Register the signed-in attendee for an open event and return the confirmation."""

        with Session(app.extensions["engine"]) as session:
            # Steps 1-2. Locking the event row makes concurrent registrations for this event wait
            # their turn, so "count the places, then take one" can never be interleaved (AC6).
            event = _public_event(session, event_request_id, lock=True)

            # Step 3 (AC4). The single "is it open?" rule lives in SPL-114's module.
            if settings.registration_state(event, settings._now()) != "open":
                abort(409, NOT_OPEN)

            # Step 4 (AC2).
            details = _details()

            # Step 5 (AC5). One Registered registration per attendee per event. A Withdrawn one
            # does not count, so registering again after withdrawing (SPL-118) is allowed.
            if _has_active_registration(session, event.id, g.user_id):
                abort(409, ALREADY_REGISTERED)

            # Step 6 (AC3). Only Registered registrations take a place.
            if settings.registered_count(session, event.id) >= event.registration_capacity:
                abort(409, FULL)

            # Step 7 (AC1). The attendee is always the signed-in account, never a browser value.
            registration = EventRegistration(
                event_request_id=event.id,
                attendee_account_id=g.user_id,
                status=REGISTERED,
                registered_at=settings._now(),
                **details,
            )
            session.add(registration)
            try:
                session.commit()
            except IntegrityError:
                # Backstop for AC5: the partial unique index refuses a second Registered row for
                # the same attendee even if two of their requests somehow got past step 5 together.
                session.rollback()
                abort(409, ALREADY_REGISTERED)
            # Step 7 (AC7). The confirmation: what they registered for, and what they submitted.
            return jsonify(
                registration=serialize_registration(registration),
                event=public_event(session, event),
            ), 201

    @app.post("/api/registrations/<int:registration_id>/withdraw")
    @require_roles(Role.ATTENDEE)
    def withdraw_registration(registration_id: int):
        """SPL-118: withdraw the signed-in attendee's own registration before the event starts."""

        # Step 1. Validate the request before touching the database, so a refused request can
        # never leave a half-written change behind.
        _require_no_fields()
        with Session(app.extensions["engine"]) as session:
            # Step 2 (AC3). Only the caller's own registration. The row lock makes a second,
            # simultaneous withdrawal wait here, then see Withdrawn at step 3 (TC-SPL-118-07).
            registration = _own_registration(session, registration_id)

            # Step 3 (AC3).
            if registration.status != REGISTERED:
                abort(409, ALREADY_WITHDRAWN)

            # Step 4 (AC1, AC3). The cut-off is the event's start (a team proposal recorded on the
            # story). It is not the registration close: an attendee can still withdraw after
            # registration has closed, until the event begins.
            event = session.get(EventRequest, registration.event_request_id)
            now = settings._now()
            if now >= settings.event_start(event):
                abort(409, EVENT_STARTED)

            # Step 5 (AC2). Kept as history rather than deleted. Places remaining counts only
            # Registered rows, so this frees the place without any counter to update.
            registration.status = WITHDRAWN
            registration.withdrawn_at = now
            session.commit()
            return jsonify(
                registration=serialize_registration(registration),
                event=public_event(session, event),
            )


def public_event(session: Session, event: EventRequest) -> dict[str, Any]:
    """What an attendee may see about an event, and nothing internal.

    No coordinator, organiser contact details, equipment, notes or booking information appear
    here. SPL-115 (the open-events list) and SPL-117 (my registrations) reuse this, so attendees
    see the same public facts everywhere.
    """

    return {
        "id": event.id,
        "name": event.name,
        "description": event.description,
        "date": event.proposed_date.isoformat(),
        "start_time": event.start_time.isoformat(timespec="minutes"),
        "end_time": event.end_time.isoformat(timespec="minutes"),
        "venues": _approved_venue_names(session, event.id),
        "places_remaining": event.registration_capacity
        - settings.registered_count(session, event.id),
    }


def serialize_registration(registration: EventRegistration) -> dict[str, Any]:
    return {
        "id": registration.id,
        "status": registration.status,
        "name": registration.name,
        "email": registration.email,
        "contact_number": registration.contact_number,
        "special_requirements": registration.special_requirements,
        "registered_at": settings._timestamp(registration.registered_at),
        # SPL-118 AC2: null until the attendee withdraws.
        "withdrawn_at": settings._timestamp(registration.withdrawn_at),
    }


def _public_event(session: Session, event_request_id: int, *, lock: bool = False) -> EventRequest:
    """The event, only if attendees may see it: Confirmed, with registration enabled.

    Anything else (a draft, an event still in planning, a postponed or cancelled one, or one whose
    registration was never enabled) gets the same 404 as an id that does not exist.
    """

    if event_request_id > MAX_EVENT_REQUEST_ID:
        abort(404, NOT_FOUND)
    query = select(EventRequest).where(
        EventRequest.id == event_request_id,
        EventRequest.status == CONFIRMED,
        EventRequest.registration_opens_at.is_not(None),
    )
    event = session.scalar(query.with_for_update() if lock else query)
    if event is None:
        abort(404, NOT_FOUND)
    return event


def _details() -> dict[str, str | None]:
    """The submitted details, cleaned, or a 400 naming the field that is wrong (AC2)."""

    data = request_json()
    # Refuse anything extra (for example "status" or "attendee_id"), so a client can never set a
    # server-owned value through this route.
    if set(data) - set(DETAILS):
        abort(400, ONLY_DETAILS)
    details: dict[str, str | None] = {}
    for field in REQUIRED:
        value = data.get(field)
        if not isinstance(value, str) or not value.strip():
            _refuse(field, f"{DETAILS[field]} is required.")
        details[field] = value.strip()
    if not EMAIL.fullmatch(details["email"]):
        _refuse("email", "Enter an email address in the form name@domain.")
    special = data.get("special_requirements")
    if special is not None and not isinstance(special, str):
        _refuse("special_requirements", "Special requirements must be text.")
    # Optional: omitted, empty or only spaces are all stored as "none".
    details["special_requirements"] = special.strip() or None if special else None
    return details


def _own_registration(session: Session, registration_id: int) -> EventRegistration:
    """The caller's own registration, locked; anyone else's gets the same 404 as an unknown id.

    Filtering on the signed-in account (rather than loading the row and comparing afterwards)
    means another attendee's registration is simply "not found", so ids cannot be probed (AC3).
    """

    # Ids above this cannot exist in an Integer column; answering 404 avoids a database error.
    if registration_id > MAX_EVENT_REQUEST_ID:
        abort(404, REGISTRATION_NOT_FOUND)
    registration = session.scalar(
        select(EventRegistration)
        .where(
            EventRegistration.id == registration_id,
            EventRegistration.attendee_account_id == g.user_id,
        )
        .with_for_update()
    )
    if registration is None:
        abort(404, REGISTRATION_NOT_FOUND)
    return registration


def _require_no_fields() -> None:
    """Keep the outcome server-owned: no body, or an empty JSON object, and nothing else."""

    if request.content_length in (None, 0):
        return
    if not request.is_json or request.get_json(silent=True) != {}:
        abort(400, NO_WITHDRAWAL_FIELDS)


def _has_active_registration(session: Session, event_request_id: int, account_id: str) -> bool:
    return (
        session.scalar(
            select(EventRegistration.id).where(
                EventRegistration.event_request_id == event_request_id,
                EventRegistration.attendee_account_id == account_id,
                EventRegistration.status == REGISTERED,
            )
        )
        is not None
    )


def _approved_venue_names(session: Session, event_request_id: int) -> list[str]:
    """The names of the venues the event actually holds (Approved bookings only), A to Z."""

    return list(
        session.scalars(
            select(Venue.name)
            .join(VenueBooking, VenueBooking.venue_id == Venue.id)
            .where(
                VenueBooking.event_request_id == event_request_id,
                VenueBooking.status == settings.APPROVED,
            )
            .distinct()
            .order_by(Venue.name)
        )
    )


def _refuse(field: str, message: str) -> None:
    """Stop with 400 and name the field, the same shape SPL-114 uses: {"error", "field"}."""

    abort(make_response(jsonify(error=message, field=field), 400))
