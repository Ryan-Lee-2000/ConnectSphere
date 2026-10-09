"""The events an attendee can register for right now (SPL-115, CS-E19-S2).

What this module does
---------------------
``GET /api/open-events`` is the attendee's entry point to registration. It lists every event they
could register for at this moment, with the public facts they need to choose one, how many places
are left, and whether they are already registered.

How the list is built, in order
-------------------------------
1. Role: only accounts with the Attendee role (``require_roles``) -> 403; no session -> 401 (AC5).
2. Candidates: events that are Confirmed and have registration enabled (SPL-114's settings set).
3. Open now: keep only those whose registration period has started and not yet closed (AC1).
   This uses SPL-114's ``registration_state``, the same rule SPL-116 uses when an attendee
   registers, so the list can never show an event that registering would then refuse.
4. Order: earliest event date first, then start time (AC1), then id so the order is stable.
5. Each event: SPL-116's ``public_event`` (name, description, date, times, Approved venues,
   places remaining - AC2, AC3), plus ``registered`` for the signed-in attendee (AC4).

Nothing is written, so this route cannot change any event or registration.
"""

from typing import Any

from flask import Flask, g, jsonify
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import registration_settings as settings
from app.authorization import require_roles
from app.event_registrations import CONFIRMED, REGISTERED, public_event
from app.models import EventRegistration, EventRequest, Role


def register_open_registration_routes(app: Flask) -> None:
    @app.get("/api/open-events")
    @require_roles(Role.ATTENDEE)
    def list_open_events():
        """Every event open for registration now, earliest first, as an attendee may see it."""

        with Session(app.extensions["engine"]) as session:
            now = settings._now()

            # Step 2. Confirmed with registration enabled. An event that was postponed, cancelled
            # or completed keeps its settings but drops out here, because it is no longer
            # Confirmed (AC1).
            candidates = session.scalars(
                select(EventRequest).where(
                    EventRequest.status == CONFIRMED,
                    EventRequest.registration_opens_at.is_not(None),
                )
            ).all()

            # Step 3 (AC1). Filtered in Python on purpose: "open" is decided by one function
            # shared with SPL-116, rather than a second copy of the rule written in SQL.
            open_now = [
                event for event in candidates if settings.registration_state(event, now) == "open"
            ]

            # Step 4 (AC1). Earliest event date first; same-day events by start time.
            open_now.sort(key=lambda event: (event.proposed_date, event.start_time, event.id))

            # Step 5 (AC4). One query for every event this attendee currently holds a place at.
            # Withdrawn registrations are not counted, so withdrawing removes the mark.
            registered_ids = set(
                session.scalars(
                    select(EventRegistration.event_request_id).where(
                        EventRegistration.attendee_account_id == g.user_id,
                        EventRegistration.status == REGISTERED,
                    )
                )
            )

            return jsonify(events=[_listed(session, event, registered_ids) for event in open_now])


def _listed(session: Session, event: EventRequest, registered_ids: set[int]) -> dict[str, Any]:
    """One list entry: SPL-116's public view of the event, plus this attendee's mark.

    Reusing ``public_event`` means the list and the registration confirmation show the same public
    facts, and nothing internal (coordinator, organiser contact, equipment, notes or booking
    details) can reach an attendee through either (AC3).
    """

    return {**public_event(session, event), "registered": event.id in registered_ids}
