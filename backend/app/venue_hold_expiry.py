"""Tentative venue-hold deadlines and expiry (SPL-133, Week 7 change 4).

A Requested booking is the tentative hold. The system gives it a deadline when it is requested
(AC1); Venue Staff may move it (AC3). At or after the deadline the hold is Expired:

* AC5 - due holds are processed before every authenticated API request (``register``), so every
  availability, search, conflict, calendar and confirmation read runs after expiry has released
  the hold's claimed time. No separate worker is needed for correctness.
* AC4/AC10 - expiry and approval lock the booking in the shared SPL-137 order (event, venue,
  booking), so exactly one of them wins. The loser re-reads the committed status and refuses.
  Approval takes its decision time after its blocking checks, so checks that run past the
  deadline cannot approve an expired hold. Each due hold is expired in its own transaction, so
  the batch never keeps one event's locks while waiting for another event's.
* AC9/AC10 - expiry runs at most once per booking: the status changes only from Requested, the
  notice is keyed to the booking, and only that booking's own claims are released, so processing
  late after downtime never frees a booking made after the expiry.
"""

from datetime import datetime, timedelta
from typing import Any

from flask import Flask, abort, g, jsonify, request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.authorization import require_roles
from app.models import EventRequest, Role, Venue, VenueBooking
from app.venue_timing import SGT

REQUESTED = "requested"
EXPIRED = "expired"
DEFAULT_HOLD = timedelta(days=7)
MAX_HOLD = timedelta(days=14)
HOLD_EXPIRED = "This hold expired at {deadline}, so it can no longer be approved."
HOLD_TOO_LATE = "This booking's time has already started, so it can no longer be held."


def _now() -> datetime:
    """The current Singapore time; separate so tests can freeze the clock at the deadline."""

    return datetime.now(SGT)


def aware(value: datetime) -> datetime:
    """SQLite drops the offset; every stored time is Singapore time (Q36)."""

    return value if value.tzinfo else value.replace(tzinfo=SGT)


def is_expired(booking: VenueBooking, now: datetime) -> bool:
    return (
        booking.status == REQUESTED
        and booking.expires_at is not None
        and now >= aware(booking.expires_at)
    )


def booking_event_start(booking: VenueBooking, event: EventRequest) -> datetime | None:
    """When this booking's own event time starts (SPL-131: each booking may have its own)."""

    if booking.exact_timing:
        try:
            return datetime.fromisoformat(booking.exact_timing["event"]["start"])
        except (KeyError, TypeError, ValueError):
            return None
    if booking.booking_date and event.start_time:
        return datetime.combine(booking.booking_date, event.start_time, tzinfo=SGT)
    return None


def default_deadline(start: datetime | None, now: datetime) -> datetime:
    """AC1: 7 days after the request, or the booking's event start if that is earlier.

    A new hold is never requested at or after its start (``hold_created`` refuses it), so the cap
    always applies. The deployment cutover has its own no-backdating rule in the migration.
    """

    deadline = now + DEFAULT_HOLD
    if start is not None and start < deadline:
        return start
    return deadline


def format_deadline(value: datetime) -> str:
    local = aware(value).astimezone(SGT)
    return f"{local.day} {local:%b %Y, %H:%M} SGT"


def hold_created(session: Session, booking: VenueBooking, event: EventRequest) -> None:
    """AC1 and AC8: set the default deadline on a new hold and tell the coordinator."""

    from app.notifications import add_arrangement_notice

    # AC1: a hold for a time that has already started would be born expired; refuse it instead.
    # The caller has not committed, so the refusal leaves no booking, claim or notice behind.
    start = booking_event_start(booking, event)
    now = _now()
    if start is not None and now >= start:
        abort(409, HOLD_TOO_LATE)
    booking.expires_at = default_deadline(start, now)
    venue = session.get(Venue, booking.venue_id)
    add_arrangement_notice(
        session,
        event,
        kind="hold_created",
        source_id=booking.id,
        message=f"{venue.name} is held for {event.name} until "
        f"{format_deadline(booking.expires_at)}. Venue Staff must approve it before then.",
    )


def expire_booking(session: Session, booking: VenueBooking, now: datetime) -> bool:
    """Expire one locked, due hold: release its time, record it, notify once (AC5, AC9)."""

    if not is_expired(booking, now):
        return False
    from app.notifications import add_arrangement_notice
    from app.venue_booking_history import record_booking_transition
    from app.venue_conflicts import transition_booking_status

    deadline = format_deadline(booking.expires_at)
    transition_booking_status(session, booking, EXPIRED)
    record_booking_transition(
        session,
        booking.id,
        action="expire",
        previous_status=REQUESTED,
        resulting_status=EXPIRED,
        actor_account_id=None,
        changed_at=now,
        note=f"Hold expired at {deadline}.",
    )
    event = session.get(EventRequest, booking.event_request_id)
    venue = session.get(Venue, booking.venue_id)
    add_arrangement_notice(
        session,
        event,
        kind="hold_expired",
        source_id=booking.id,
        message=f"The hold on {venue.name} for {event.name} expired at {deadline}. "
        "Request the venue again if it is still needed.",
    )
    return True


def process_due_holds(session: Session, now: datetime) -> int:
    """Expire every hold whose deadline has passed, in id order, each in its own transaction.

    Each hold is locked, expired and committed (or released) before the next is locked. Keeping
    them all to one final commit would hold event A and its venue while waiting for event B, and
    a booking operation already holding event B and waiting for that venue would deadlock it.
    """

    from app.exact_venue_bookings import lock_booking

    due = session.scalars(
        select(VenueBooking.id)
        .where(VenueBooking.status == REQUESTED, VenueBooking.expires_at <= now)
        .order_by(VenueBooking.id)
    ).all()
    expired = 0
    for booking_id in due:
        booking = lock_booking(session, booking_id)
        if booking is not None and expire_booking(session, booking, now):
            session.commit()
            expired += 1
        else:
            session.rollback()
    return expired


def register_hold_expiry(app: Flask) -> None:
    """Process due holds before each authenticated API request, and the deadline route."""

    def run_due_expiry() -> None:
        with Session(app.extensions["engine"]) as session:
            process_due_holds(session, _now())

    app.extensions["process_due_holds"] = run_due_expiry

    @app.put("/api/venue-bookings/<int:booking_id>/hold-deadline")
    @require_roles(Role.VENUE_STAFF)
    def change_hold_deadline(booking_id: int):
        """AC3: Venue Staff move a hold's deadline within the limits, with history and notice."""

        from app.coordinator_assignment import MAX_EVENT_REQUEST_ID
        from app.exact_venue_bookings import lock_booking
        from app.notifications import add_arrangement_notice
        from app.venue_booking_history import record_booking_transition
        from app.venue_booking_requests import serialize_venue_booking

        requested_deadline = _deadline_body()
        if booking_id > MAX_EVENT_REQUEST_ID:
            abort(404, "Venue-booking request not found.")
        with Session(app.extensions["engine"]) as session:
            booking = lock_booking(session, booking_id)
            if booking is None:
                abort(404, "Venue-booking request not found.")
            now = _now()
            if expire_booking(session, booking, now):
                session.commit()
                abort(409, "This hold has expired, so its deadline can no longer be changed.")
            if booking.status != REQUESTED or booking.expires_at is None:
                abort(409, "Only a Requested hold with a deadline can have its deadline changed.")
            event = session.get(EventRequest, booking.event_request_id)
            _refuse_out_of_range(requested_deadline, now, booking_event_start(booking, event))
            previous = aware(booking.expires_at)
            if requested_deadline == previous:
                return jsonify(booking=serialize_venue_booking(session, booking))
            booking.expires_at = requested_deadline
            entry = record_booking_transition(
                session,
                booking.id,
                action="change_deadline",
                previous_status=REQUESTED,
                resulting_status=REQUESTED,
                actor_account_id=g.user_id,
                changed_at=now,
                note=f"Hold deadline moved from {format_deadline(previous)} to "
                f"{format_deadline(requested_deadline)}.",
            )
            session.flush()
            venue = session.get(Venue, booking.venue_id)
            add_arrangement_notice(
                session,
                event,
                kind="hold_deadline_changed",
                source_id=entry.id,
                message=f"The hold on {venue.name} for {event.name} now expires at "
                f"{format_deadline(requested_deadline)}.",
            )
            session.commit()
            return jsonify(booking=serialize_venue_booking(session, booking))


def _refuse_out_of_range(deadline: datetime, now: datetime, start: datetime | None) -> None:
    if deadline <= now:
        abort(400, "Choose a deadline in the future.")
    if deadline > now + MAX_HOLD:
        abort(400, "A hold can be kept for at most 14 days from now.")
    if start is not None and deadline > start:
        abort(400, f"The deadline cannot be after the booking starts ({format_deadline(start)}).")


def _deadline_body() -> datetime:
    """Only ``expires_at``: an ISO date-time, read as Singapore time when it has no offset."""

    data: Any = request.get_json(silent=True)
    if not isinstance(data, dict) or set(data) != {"expires_at"}:
        abort(400, "Send only the new deadline.")
    value = data["expires_at"]
    if not isinstance(value, str):
        abort(400, "The deadline must be a date and time.")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        abort(400, "The deadline must be a date and time.")
    return aware(parsed).astimezone(SGT)
