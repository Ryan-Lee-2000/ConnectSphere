"""In-app notification inbox (SPL-101, CS-E20-S1).

Every account sees only the notices addressed to it. The recipient always comes from the verified
session, never from the request, so one account cannot read or change another's inbox.
"""

from datetime import date, datetime, time
from typing import Any

from flask import Flask, abort, g, jsonify
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session, joinedload

from app.authorization import require_roles
from app.event_requests import SINGAPORE
from app.models import (
    Account,
    AccountRole,
    EventCoordinatorAssignment,
    EventRegistration,
    EventRequest,
    Notification,
    Role,
    Venue,
    VenueBooking,
)

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


def add_review_outcome_notice(
    session: Session, event: EventRequest, *, kind: str, source_id: int, message: str
) -> None:
    """Notify the event's organiser of a review outcome (SPL-102), in the caller's transaction.

    The recipient is always the organiser stored on the event, never a value from the request.
    The notice commits or rolls back with the action, so a refused action leaves none. The
    source row (status history or clarification) identifies this action, so a repeat of it
    cannot add a second notice. The ``organiser_`` prefix opens the organiser's event page.
    """

    session.add(
        Notification(
            recipient_account_id=event.organiser_account_id,
            event_request_id=event.id,
            message=message,
            dedupe_key=f"organiser_{kind}:{source_id}",
            created_at=datetime.now(SINGAPORE),
        )
    )


def add_organiser_notice(
    session: Session,
    event: EventRequest,
    *,
    actor_id: str,
    kind: str,
    source_id: int,
    message: str,
    recipient_id: str | None = None,
) -> None:
    """Notify an organiser that their event's confirmation state changed (SPL-123).

    The recipient is the event's organiser, or ``recipient_id`` (the organiser who submitted a
    change request), both read on the server. Nobody is told of their own action. Runs in the
    caller's transaction, so a refused or failed action leaves no notice, and the source row in
    the dedupe key stops a repeat adding a second (AC5). The ``organiser_`` prefix opens the
    organiser's event page.
    """

    recipient = recipient_id or event.organiser_account_id
    if recipient == actor_id:
        return
    session.add(
        Notification(
            recipient_account_id=recipient,
            event_request_id=event.id,
            message=message,
            dedupe_key=f"organiser_{kind}:{source_id}",
            created_at=datetime.now(SINGAPORE),
        )
    )


def add_clarification_answered_notice(
    session: Session, event: EventRequest, *, author_id: str, clarification_id: int
) -> None:
    """Notify the coordinator who asked a clarification question that it was answered (SPL-103).

    The recipient is the question's author, read from the stored row, never from the request, even
    if the event has been reassigned since. Runs in the caller's transaction, so a refused response
    leaves no notice, and the clarification row id stops a repeat adding a second.
    """

    session.add(
        Notification(
            recipient_account_id=author_id,
            event_request_id=event.id,
            message=f"The organiser responded to your clarification request on {event.name}.",
            dedupe_key=f"clarification_answered:{clarification_id}",
            created_at=datetime.now(SINGAPORE),
        )
    )


def add_change_request_submitted_notice(
    session: Session,
    event: EventRequest,
    *,
    change_request_id: int,
    field_labels: list[str],
) -> None:
    """Notify the event's assigned coordinator of a new change request (SPL-103).

    The recipient is the coordinator currently assigned to the event. An event with no assignment
    notifies nobody. The message names the fields only, never the values or reasons. Runs in the
    caller's transaction, so a refused submission leaves no notice, and the change request id
    stops a repeat adding a second.
    """

    coordinator_id = session.scalar(
        select(EventCoordinatorAssignment.coordinator_account_id).where(
            EventCoordinatorAssignment.event_request_id == event.id
        )
    )
    if coordinator_id is None:
        return
    session.add(
        Notification(
            recipient_account_id=coordinator_id,
            event_request_id=event.id,
            message=f"A change request was submitted on {event.name}: {', '.join(field_labels)}.",
            dedupe_key=f"change_request_submitted:{change_request_id}",
            created_at=datetime.now(SINGAPORE),
        )
    )


def add_arrangement_notice(
    session: Session, event: EventRequest, *, kind: str, source_id: str | int, message: str
) -> None:
    """Notify the event's assigned coordinator of a decision on its arrangements (SPL-121).

    The recipient is the coordinator assigned when the action happens, read on the server; an
    event with no assignment notifies nobody. Runs in the caller's transaction, so a refused or
    failed action leaves no notice, and the source row in the dedupe key stops a repeat adding a
    second.
    """

    coordinator_id = session.scalar(
        select(EventCoordinatorAssignment.coordinator_account_id).where(
            EventCoordinatorAssignment.event_request_id == event.id
        )
    )
    if coordinator_id is None:
        return
    session.add(
        Notification(
            recipient_account_id=coordinator_id,
            event_request_id=event.id,
            message=message,
            dedupe_key=f"arrangement_{kind}:{source_id}",
            created_at=datetime.now(SINGAPORE),
        )
    )


def add_technical_support_notices(
    session: Session, event: EventRequest, *, kind: str, source_id: str | int, message: str
) -> None:
    """Notify every active Technical Support Staff account (SPL-122), in the caller's transaction.

    Recipients come from server-owned role assignments, never from the request. The notice commits
    or rolls back with the action, so a refused action leaves none, and the source row in the
    dedupe key stops a repeat of the same action adding a second.
    """

    now = datetime.now(SINGAPORE)
    for recipient_id in _active_role_holders(session, Role.TECHNICAL_SUPPORT_STAFF):
        session.add(
            Notification(
                recipient_account_id=recipient_id,
                event_request_id=event.id,
                message=message,
                dedupe_key=f"technical_{kind}:{source_id}",
                created_at=now,
            )
        )


def add_venue_booking_notices(
    session: Session, booking: VenueBooking, event: EventRequest, *, kind: str
) -> None:
    """Notify every active Venue Staff account that a booking was requested or withdrawn (SPL-104).

    ``kind`` is ``requested`` or ``withdrawn``. Recipients come from role assignments, so an
    account that also requested the booking is notified as Venue Staff. Runs in the caller's
    transaction, so a refused action leaves no notice, and the booking id in the dedupe key gives
    each booking its own notice and stops a retry adding a second (AC4, AC7).
    """

    venue = session.get(Venue, booking.venue_id)
    action = "Venue booking requested" if kind == "requested" else "Venue booking request withdrawn"
    message = f"{action} for {event.name}: {venue.name}{_booking_details(booking, event)}."
    now = datetime.now(SINGAPORE)
    for recipient_id in _active_role_holders(session, Role.VENUE_STAFF):
        session.add(
            Notification(
                recipient_account_id=recipient_id,
                event_request_id=event.id,
                message=message,
                dedupe_key=f"venue_booking_{kind}:{booking.id}",
                created_at=now,
            )
        )


def add_attendee_notices(
    session: Session, event: EventRequest, *, kind: str, source_id: str | int, message: str
) -> None:
    """Notify every attendee still registered for the event (SPL-124), in the caller's transaction.

    Recipients are the registrations that are Registered when the action happens, read on the
    server, so an attendee who has withdrawn gets nothing (AC5). The notice commits or rolls back
    with the action, and the source in the dedupe key stops a repeat adding a second (AC4).
    """

    now = datetime.now(SINGAPORE)
    for recipient_id in session.scalars(
        select(EventRegistration.attendee_account_id).where(
            EventRegistration.event_request_id == event.id,
            EventRegistration.status == "registered",
        )
    ).all():
        session.add(
            Notification(
                recipient_account_id=recipient_id,
                event_request_id=event.id,
                message=message,
                dedupe_key=f"attendee_{kind}:{source_id}",
                created_at=now,
            )
        )


def add_registration_notice(
    session: Session, registration: EventRegistration, event: EventRequest, *, withdrawn: bool
) -> None:
    """AC3: acknowledge an attendee's own registration or withdrawal, keyed to the registration."""

    if withdrawn:
        kind, message = "withdrawn", f"You withdrew your registration for {event.name}."
    else:
        kind = "registered"
        message = (
            f"You are registered for {event.name} on {_day(event.proposed_date)}, "
            f"{event.start_time:%H:%M}–{event.end_time:%H:%M} SGT."
        )
    session.add(
        Notification(
            recipient_account_id=registration.attendee_account_id,
            event_request_id=event.id,
            message=message,
            dedupe_key=f"attendee_{kind}:{registration.id}",
            created_at=datetime.now(SINGAPORE),
        )
    )


def add_schedule_change_notices(
    session: Session, event: EventRequest, changes: dict[str, dict], *, change_id: int
) -> None:
    """AC1: tell registered attendees the event's new date or times, with the old ones.

    ``changes`` is the saved change record ({field: {"previous", "new"}}); only the date and the
    times are public, so a change to anything else notifies nobody.
    """

    parts = []
    if "proposed_date" in changes:
        previous = date.fromisoformat(changes["proposed_date"]["previous"])
        parts.append(f"date now {_day(event.proposed_date)} (was {_day(previous)})")
    if "start_time" in changes or "end_time" in changes:
        previous_start, previous_end = (
            time.fromisoformat(changes[key]["previous"]) if key in changes else getattr(event, key)
            for key in ("start_time", "end_time")
        )
        parts.append(
            f"time now {event.start_time:%H:%M}–{event.end_time:%H:%M} SGT "
            f"(was {previous_start:%H:%M}–{previous_end:%H:%M} SGT)"
        )
    if parts:
        add_attendee_notices(
            session,
            event,
            kind="schedule_changed",
            source_id=change_id,
            message=f"{event.name} has changed: {'; '.join(parts)}.",
        )


def add_venue_change_notices(
    session: Session, event: EventRequest, booking_id: int, *, added: bool
) -> None:
    """AC1: an Approved venue was added to or removed from the event; name the venues it now holds.

    A booking is approved once and cancelled once, so its id keys each notice.
    """

    session.flush()
    names = session.scalars(
        select(Venue.name)
        .join(VenueBooking, VenueBooking.venue_id == Venue.id)
        .where(VenueBooking.event_request_id == event.id, VenueBooking.status == "approved")
        .distinct()
        .order_by(Venue.name)
    ).all()
    add_attendee_notices(
        session,
        event,
        kind="venue_added" if added else "venue_removed",
        source_id=booking_id,
        message=f"The venue for {event.name} has changed. Venues now: "
        f"{', '.join(names) if names else 'none confirmed yet'}.",
    )


def _active_role_holders(session: Session, role: Role) -> list[str]:
    return session.scalars(
        select(Account.id)
        .join(AccountRole, AccountRole.account_id == Account.id)
        .where(AccountRole.role == role.value, Account.is_active.is_(True))
    ).all()


def _booking_details(booking: VenueBooking, event: EventRequest) -> str:
    """AC5: date, Singapore times and the whole occupied window, from the booking's own timing."""

    day = booking.booking_date
    if booking.exact_timing:
        start, end = _interval(booking.exact_timing["event"])
        occupied_start, occupied_end = _interval(booking.exact_timing["occupied"])
        return (
            f" on {_day(day)}, {start:%H:%M}–{end:%H:%M} SGT; venue occupied "
            f"{_clock(occupied_start, day)}–{_clock(occupied_end, day)} "
            "including setup and turnaround"
        )
    if day is None or not booking.event_slots:
        # A Requested booking stored without timing (SPL-83 claims) must still be withdrawable.
        return ""
    # Slot timing keeps the event's own times and records preparation as whole slots.
    times = (
        f", {event.start_time:%H:%M}–{event.end_time:%H:%M} SGT"
        if event.start_time and event.end_time
        else ""
    )
    preparation = [
        f"{label} {_slot_name(slot)}" + (f" on {_day(slot_day)}" if slot_day != day else "")
        for label, slot_day, slot in (
            ("setup", booking.setup_date, booking.setup_slot),
            ("turnaround", booking.turnaround_date, booking.turnaround_slot),
        )
        if slot
    ]
    slots = ", ".join(_slot_name(slot) for slot in booking.event_slots)
    return f" on {_day(day)}{times}; venue occupied {slots}" + (
        f" ({', '.join(preparation)})" if preparation else ""
    )


def _interval(stored: dict[str, str]) -> tuple[datetime, datetime]:
    return tuple(
        datetime.fromisoformat(stored[edge]).astimezone(SINGAPORE) for edge in ("start", "end")
    )


def _clock(moment: datetime, day: date) -> str:
    # Preparation can cross midnight, so name the other day when it does.
    return f"{moment:%H:%M}" if moment.date() == day else f"{_day(moment.date())} {moment:%H:%M}"


def _day(value: date) -> str:
    return f"{value:%a} {value.day} {value:%b %Y}"


def _slot_name(slot: str) -> str:
    return "Night" if slot == "NIGHT" else slot


def add_safety_decision_notice(session: Session, event: EventRequest, *, review) -> None:
    """Notify the currently assigned coordinator of a durable safety decision."""
    coordinator_id = session.scalar(
        select(EventCoordinatorAssignment.coordinator_account_id).where(
            EventCoordinatorAssignment.event_request_id == event.id
        )
    )
    if coordinator_id is None:
        return
    wording = {
        "approved": "approved the safety arrangement.",
        "changes_requested": "requested changes to the safety arrangement.",
        "rejected": "rejected the safety arrangement.",
    }[review.status]
    session.add(
        Notification(
            recipient_account_id=coordinator_id,
            event_request_id=event.id,
            message=f"Safety Officer {wording} for {event.name}",
            dedupe_key=f"safety_decision:{review.id}",
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
        "link": _event_link(notice),
        "created_at": _timestamp(notice.created_at),
        "read": notice.read_at is not None,
    }


def _event_link(notice: Notification) -> str:
    # The notice kind is the dedupe key's prefix. Notices written for the organiser open the
    # organisation event page; the coordinator-only page would send them back to the workspace.
    # Both pages stay behind their own role and ownership checks on the server.
    kind = notice.dedupe_key.split(":", 1)[0]
    if kind.startswith("technical_"):
        # SPL-122 AC5: Technical Support cannot open coordinator pages; their queue holds the work.
        return "/workspace/equipment-review-queue"
    if kind.startswith("venue_booking_"):
        # SPL-104: Venue Staff cannot open coordinator pages; their booking queue holds the work.
        return "/workspace/booking-requests"
    if kind.startswith("attendee_"):
        # SPL-124 AC6: attendees cannot open event pages; their registrations are listed here.
        return "/workspace/my-registrations"
    page = "organisation-events" if kind.startswith("organiser_") else "assigned-events"
    return f"/workspace/{page}/{notice.event_request_id}"


def _timestamp(value: datetime) -> str:
    # SQLite drops the offset, so stamp the known zone back (matches the other serialisers).
    return (value if value.tzinfo else value.replace(tzinfo=SINGAPORE)).isoformat()
