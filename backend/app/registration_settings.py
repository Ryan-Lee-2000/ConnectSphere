"""Attendee registration settings for a Confirmed event (SPL-114, CS-E19-S1).

What this module does
---------------------
The event's assigned Event Coordinator enables registration by choosing three things: when it
opens, when it closes, and how many places there are (the capacity). They can change those
settings later under the same rules. Every save is appended to ``registration_settings_history``.

How a save is checked (``PUT /api/event-requests/<id>/registration``), in order
--------------------------------------------------------------------------------
1. Role: only Event Coordinators reach the route at all (``require_roles``) -> otherwise 403.
2. Assignment: only *this event's* coordinator -> otherwise 404, the same answer an unknown event
   gets, so the response never confirms that someone else's event exists (AC7).
3. Status: only while the event is Confirmed -> otherwise 409 (AC7).
4. Shape: exactly ``opens_at``, ``closes_at`` and ``capacity``, each well formed -> otherwise 400
   naming the field (AC2, AC3).
5. Rules: opens before it closes, closes before the event starts (AC2); capacity no larger than
   the booked layout (AC3) -> otherwise 400 naming the field. No Approved booking at all -> 409.
6. Save: write the new settings and one history row in the same transaction (AC6).

Any refusal happens before anything is written, so "nothing is saved" holds for every refusal.

What later stories reuse
------------------------
SPL-115 (see open events) and SPL-116 (register) call ``registration_state`` to decide whether an
attendee may see an event and register for it, so the "is it open?" rule lives in one place.
"""

from datetime import datetime
from typing import Any

from flask import Flask, abort, g, jsonify, make_response
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app.authorization import require_roles
from app.coordinator_assignment import MAX_EVENT_REQUEST_ID, is_assigned_coordinator
from app.event_requests import SINGAPORE
from app.models import (
    EventRequest,
    RegistrationSettingsChange,
    Role,
    VenueBooking,
    VenueLayout,
)
from app.validation import request_json

CONFIRMED = "confirmed"
APPROVED = "approved"
# The only three keys a save accepts, with the human name used in error messages.
FIELDS = {
    "opens_at": "Registration opening time",
    "closes_at": "Registration closing time",
    "capacity": "Registration capacity",
}
NOT_FOUND = "Assigned event not found."
NOT_CONFIRMED = "Registration can only be set up for a Confirmed event."
NO_APPROVED_BOOKING = "Registration needs an Approved venue booking to set its capacity against."
ONLY_SETTINGS = "Registration settings accept only opens_at, closes_at and capacity."
OPEN_BEFORE_CLOSE = "Registration must open before it closes."
CLOSE_BEFORE_START = "Registration must close before the event starts."


def _now() -> datetime:
    """The current Singapore time.

    It is a separate function so tests can replace it with a fixed time ("freeze the clock") and
    check exact boundaries, for example that registration is open at 09:00 but not at 08:59.
    """

    return datetime.now(SINGAPORE)


def register_registration_settings_routes(app: Flask) -> None:
    @app.get("/api/event-requests/<int:event_request_id>/registration")
    @require_roles(Role.EVENT_COORDINATOR)
    def read_registration_settings(event_request_id: int):
        """The current settings, whether registration is open now, the capacity cap and history."""

        with Session(app.extensions["engine"]) as session:
            event = _assigned_event(session, event_request_id)
            return jsonify(registration=_serialize(session, event))

    @app.put("/api/event-requests/<int:event_request_id>/registration")
    @require_roles(Role.EVENT_COORDINATOR)
    def save_registration_settings(event_request_id: int):
        """Enable registration, or change its settings. The same call does both (AC1, AC4)."""

        with Session(app.extensions["engine"]) as session:
            # Steps 1-2. ``lock=True`` takes a row lock on the event (SELECT ... FOR UPDATE), so if
            # two saves for the same event arrive together, the second waits for the first. Each
            # history row then records the true "previous" settings instead of both claiming the
            # same starting point.
            event = _assigned_event(session, event_request_id, lock=True)

            # Step 3 (AC7). Checked before reading the body: a non-Confirmed event is refused
            # whatever settings were sent.
            if event.status != CONFIRMED:
                abort(409, NOT_CONFIRMED)

            # Step 4 (AC2, AC3). Parse and type-check the three values.
            opens_at, closes_at, capacity = _settings()

            # Step 5 (AC2). Both comparisons use exact instants, so the boundaries are strict:
            # closing exactly when the event starts is refused, one minute earlier is accepted.
            if opens_at >= closes_at:
                _refuse("opens_at", OPEN_BEFORE_CLOSE)
            if closes_at >= event_start(event):
                _refuse("closes_at", CLOSE_BEFORE_START)

            # Step 5 (AC3). The capacity can never exceed the room actually booked.
            limit = max_capacity(session, event.id)
            if limit is None:
                # 409, not 400: the request is well formed, but the event is not in a state
                # where a capacity can be set, because there is no Approved booking to cap it.
                abort(409, NO_APPROVED_BOOKING)
            if capacity > limit:
                _refuse(
                    "capacity",
                    f"Registration capacity cannot be more than {limit}, "
                    "the booked layout's capacity.",
                )

            # AC4 also says capacity may never go below the attendees already Registered. That
            # needs registrations, which arrive with SPL-116; until then no event has any, so
            # every capacity of 1 or more meets it. SPL-116 adds the check (QA-SPL-114 TC-10).

            # Step 6 (AC6). Record the previous values before overwriting them. The history row and
            # the new settings commit together, so there is never a change without its record.
            session.add(
                RegistrationSettingsChange(
                    event_request_id=event.id,
                    previous_opens_at=event.registration_opens_at,
                    previous_closes_at=event.registration_closes_at,
                    previous_capacity=event.registration_capacity,
                    opens_at=opens_at,
                    closes_at=closes_at,
                    capacity=capacity,
                    # The actor comes from the verified session, never from the request body.
                    changed_by_account_id=g.user_id,
                    changed_at=_now(),
                )
            )
            event.registration_opens_at = opens_at
            event.registration_closes_at = closes_at
            event.registration_capacity = capacity
            session.commit()
            return jsonify(registration=_serialize(session, event))


def event_start(event: EventRequest) -> datetime:
    """When the event starts: its date plus its start time, in Singapore time (AC2's deadline)."""

    return datetime.combine(event.proposed_date, event.start_time, tzinfo=SINGAPORE)


def max_capacity(session: Session, event_request_id: int) -> int | None:
    """The largest booked-layout capacity among the event's Approved bookings, or None if none.

    A booking records the venue and the layout name ("theatre", "banquet", ...); the venue's layout
    row holds that layout's capacity, so the two are joined on (venue, layout name).

    Only Approved bookings count: a Requested, Rejected or Withdrawn booking does not guarantee the
    room. Working interpretation pending the PO (SPL-114 open question 1): when SPL-131 lets an
    event hold several bookings, their capacities are never added together (SPL-131 AC3), so the
    largest single booked layout is the cap.
    """

    return session.scalar(
        select(func.max(VenueLayout.capacity))
        .select_from(VenueBooking)
        .join(
            VenueLayout,
            (VenueLayout.venue_id == VenueBooking.venue_id)
            & (VenueLayout.layout == VenueBooking.layout),
        )
        .where(VenueBooking.event_request_id == event_request_id, VenueBooking.status == APPROVED)
    )


def registration_state(event: EventRequest, now: datetime) -> str:
    """Where registration stands at ``now``: off, not_yet_open, open or closed (AC5).

    - off: never enabled, so all three settings are still empty.
    - not_yet_open: enabled, but the opening time has not arrived.
    - open: from the opening time up to, but not including, the closing time.
    - closed: the closing time has passed. Setting a later closing time reopens it (AC4).

    This only looks at the period. SPL-115 and SPL-116 also require the event to still be
    Confirmed before attendees can see it or register.
    """

    if event.registration_opens_at is None:
        return "off"
    if now < _singapore(event.registration_opens_at):
        return "not_yet_open"
    if now < _singapore(event.registration_closes_at):
        return "open"
    return "closed"


def _assigned_event(session: Session, event_request_id: int, *, lock: bool = False) -> EventRequest:
    """The event, only if the caller currently coordinates it; otherwise one 404 for all (AC7).

    Another coordinator's event, an event that does not exist, and an id too large for the database
    all get the identical 404, so a coordinator cannot probe which event ids exist. This matches
    the assignment check SPL-78 uses for venue bookings.
    """

    if event_request_id > MAX_EVENT_REQUEST_ID or not is_assigned_coordinator(
        session, event_request_id, g.user_id
    ):
        abort(404, NOT_FOUND)
    query = select(EventRequest).where(EventRequest.id == event_request_id)
    return session.scalar(query.with_for_update() if lock else query)


def _settings() -> tuple[datetime, datetime, int]:
    """The three settings from the request body, or a 400 naming the field that is wrong."""

    data = request_json()
    # Refuse anything extra (for example "enabled" or "status") so a client can never set a
    # server-owned value through this route.
    if set(data) - set(FIELDS):
        abort(400, ONLY_SETTINGS)
    opens_at = _date_time(data.get("opens_at"), "opens_at")
    closes_at = _date_time(data.get("closes_at"), "closes_at")
    capacity = data.get("capacity")
    if capacity is None:
        _refuse("capacity", f"{FIELDS['capacity']} is required.")
    # In Python, True counts as the integer 1, so booleans are refused explicitly. 2.5 and "ten"
    # fail the integer check, and 0 or a negative number fails the lower bound (AC3).
    if isinstance(capacity, bool) or not isinstance(capacity, int) or capacity < 1:
        _refuse("capacity", f"{FIELDS['capacity']} must be a positive whole number.")
    return opens_at, closes_at, capacity


def _date_time(value: Any, field: str) -> datetime:
    """An ISO 8601 date-time such as "2026-10-10T09:00", converted to Singapore time.

    The coordinator's form sends a wall-clock time with no offset; the story says every time is
    Singapore time, so that is how it is read. A time that does carry an offset ("...Z" for UTC)
    is converted, so 10:00 UTC is understood as 18:00 in Singapore.
    """

    if value is None:
        _refuse(field, f"{FIELDS[field]} is required.")
    try:
        parsed = datetime.fromisoformat(value) if isinstance(value, str) else None
    except ValueError:
        parsed = None
    if parsed is None:
        _refuse(field, f"{FIELDS[field]} must be a date and time.")
    # Always store Singapore time. SQLite (used by the fast tests) drops the offset when it saves,
    # so storing Singapore wall time means the value reads back as the same instant there too.
    return (
        parsed.replace(tzinfo=SINGAPORE) if parsed.tzinfo is None else parsed.astimezone(SINGAPORE)
    )


def _refuse(field: str, message: str) -> None:
    """Stop with 400 and say which field broke the rule, so the page can show it beside that field.

    The app's normal error handler only returns ``{"error": ...}``; this adds ``"field"`` as well.
    """

    abort(make_response(jsonify(error=message, field=field), 400))


def _serialize(session: Session, event: EventRequest) -> dict[str, Any]:
    """Everything the coordinator's panel shows, in one response."""

    # Newest change first, with each changer's account loaded in the same query.
    changes = session.scalars(
        select(RegistrationSettingsChange)
        .where(RegistrationSettingsChange.event_request_id == event.id)
        .options(joinedload(RegistrationSettingsChange.changed_by))
        .order_by(RegistrationSettingsChange.id.desc())
    ).all()
    return {
        "enabled": event.registration_opens_at is not None,
        "state": registration_state(event, _now()),
        **_values(
            event.registration_opens_at, event.registration_closes_at, event.registration_capacity
        ),
        # Sent so the page can tell the coordinator the limit before they try to save.
        "max_capacity": max_capacity(session, event.id),
        "event_starts_at": _timestamp(event_start(event))
        if event.proposed_date and event.start_time
        else None,
        "history": [
            {
                # The first enabling has no previous settings, shown as null.
                "previous": (
                    _values(
                        change.previous_opens_at,
                        change.previous_closes_at,
                        change.previous_capacity,
                    )
                    if change.previous_opens_at is not None
                    else None
                ),
                "current": _values(change.opens_at, change.closes_at, change.capacity),
                "changed_by": {"id": change.changed_by.id, "name": change.changed_by.display_name},
                "changed_at": _timestamp(change.changed_at),
            }
            for change in changes
        ],
    }


def _values(opens_at: datetime | None, closes_at: datetime | None, capacity: int | None) -> dict:
    return {
        "opens_at": _timestamp(opens_at),
        "closes_at": _timestamp(closes_at),
        "capacity": capacity,
    }


def _singapore(value: datetime) -> datetime:
    """The same instant in Singapore time, whichever database it came from.

    SQLite returns the stored Singapore wall time with no offset, so the offset is added back.
    PostgreSQL returns a time with an offset (usually UTC), so it is converted.
    """

    return value.replace(tzinfo=SINGAPORE) if value.tzinfo is None else value.astimezone(SINGAPORE)


def _timestamp(value: datetime | None) -> str | None:
    """ISO 8601 text with the +08:00 offset, for example "2026-10-10T09:00:00+08:00"."""

    return _singapore(value).isoformat() if value is not None else None
