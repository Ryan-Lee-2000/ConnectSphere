"""Replacing a venue booking after operational disruption (SPL-132, Week 7 change 2).

A Venue Staff block already flags the bookings it overlaps (SPL-89, SPL-138). This module adds
what follows: only bookings that have not ended are flagged, the coordinator is told the time and
reason, a Confirmed or Preparing event returns to Planning (through SPL-109's transition), and a
replacement request linked to the original releases the original only when Venue Staff approve
the replacement. The event itself is never cancelled or rescheduled (AC3).
"""

from datetime import datetime, timezone

from flask import abort
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    ACTIVE_BOOKING_STATUSES,
    EventRequest,
    Venue,
    VenueBooking,
    VenueBookingReviewFinding,
    VenueOperationalBlock,
)

ENDED_EVENT_STATUSES = ("cancelled", "completed")
OPERATIONAL_BLOCK = "operational_block"
REPLACEMENT_NOT_FOUND = "The venue booking to replace was not found for this event."
ONLY_ACTIVE = "Only a Requested or Approved venue booking can be replaced."
NOT_DISRUPTED = "Only a booking flagged because its venue became unavailable can be replaced."
REPLACEMENT_PENDING = (
    "A replacement for this booking is already waiting for a Venue Staff decision. "
    "Withdraw it before requesting another."
)


def lock_events_at_venue(session: Session, venue_id: int) -> None:
    """Lock every event holding an active booking at the venue, before the venue itself.

    A block may return those events to Planning (AC10), and booking writers lock event before
    venue (SPL-137), so taking the events first keeps one lock order and cannot deadlock.
    """

    from app.exact_venue_bookings import lock_event

    event_ids = session.scalars(
        select(VenueBooking.event_request_id)
        .where(
            VenueBooking.venue_id == venue_id,
            VenueBooking.status.in_(ACTIVE_BOOKING_STATUSES),
        )
        .distinct()
    ).all()
    for event_id in sorted(event_ids):
        lock_event(session, event_id)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def is_affected(booking: VenueBooking, event: EventRequest) -> bool:
    """AC1: a booking is affected only while its event time has not ended."""

    from app.venue_booking_assessment import _booking_advertised

    if event.status in ENDED_EVENT_STATUSES:
        return False
    advertised = _booking_advertised(event, booking)
    return advertised is None or advertised.end > _now()


def notify_disruption(
    session: Session, booking: VenueBooking, event: EventRequest, block: VenueOperationalBlock
) -> None:
    """AC2: one notice per affected booking, naming the event, venue, time and reason."""

    from app.notifications import add_arrangement_notice, booking_time

    venue = session.get(Venue, block.venue_id)
    # The key is SPL-121's, so the disruption notice is that notice, never a second one.
    add_arrangement_notice(
        session,
        event,
        kind="booking_flagged",
        source_id=f"block-{block.id}-booking-{booking.id}",
        message=f"Venue booking for {event.name} at {venue.name}{booking_time(booking, event)} "
        f"needs a replacement: Venue Staff marked the venue unavailable ({block.reason}).",
    )


def return_disrupted_events(
    session: Session, events: list[EventRequest], *, actor_id: str, now: datetime
) -> None:
    """AC10: a Confirmed or Preparing event returns to Planning and its organiser is told."""

    from app.significant_event_changes import return_to_planning

    for event in events:
        return_to_planning(
            session,
            event,
            now,
            actor_id=actor_id,
            message=f"{event.name} has returned to Planning because a booked venue became "
            "unavailable. It must be confirmed again once the venue arrangement is resolved.",
        )


def is_disrupted(session: Session, booking: VenueBooking) -> bool:
    """Whether an unresolved venue-block finding is still recorded on the booking."""

    return (
        session.scalar(
            select(VenueBookingReviewFinding.id)
            .where(
                VenueBookingReviewFinding.booking_id == booking.id,
                VenueBookingReviewFinding.reason_type == OPERATIONAL_BLOCK,
                VenueBookingReviewFinding.resolved_at.is_(None),
            )
            .limit(1)
        )
        is not None
    )


def check_replaceable(session: Session, event: EventRequest, original_id: int) -> VenueBooking:
    """AC5: the original must be this event's active booking, flagged by a venue block."""

    original = session.get(VenueBooking, original_id)
    if original is None or original.event_request_id != event.id:
        abort(404, REPLACEMENT_NOT_FOUND)
    if original.status not in ACTIVE_BOOKING_STATUSES:
        abort(409, ONLY_ACTIVE)
    if not is_disrupted(session, original):
        abort(409, NOT_DISRUPTED)
    if pending_replacement(session, original.id) is not None:
        abort(409, REPLACEMENT_PENDING)
    return original


def pending_replacement(session: Session, original_id: int) -> VenueBooking | None:
    return session.scalar(
        select(VenueBooking).where(
            VenueBooking.replaces_booking_id == original_id,
            VenueBooking.status == "requested",
        )
    )


def lock_replacement_venues(session: Session, booking_id: int) -> None:
    """Lock a replacement's event, then its venue and the original's venue in id order.

    Approving a replacement locks the original's venue to release it, after the replacement's
    venue. Two replacements in opposite directions (A to B for one event, B to A for another)
    would take the two venue locks in reverse order and deadlock, so both are taken first,
    lowest id first. The later per-booking locks then find them already held.
    """

    from app.exact_venue_bookings import lock_event, lock_venue

    replacement = session.execute(
        select(
            VenueBooking.event_request_id,
            VenueBooking.venue_id,
            VenueBooking.replaces_booking_id,
        ).where(VenueBooking.id == booking_id)
    ).first()
    if replacement is None or replacement.replaces_booking_id is None:
        return
    original_venue_id = session.scalar(
        select(VenueBooking.venue_id).where(VenueBooking.id == replacement.replaces_booking_id)
    )
    # The original belongs to the same event (check_replaceable), so one event lock covers both.
    lock_event(session, replacement.event_request_id)
    for venue_id in sorted({replacement.venue_id, original_venue_id} - {None}):
        lock_venue(session, venue_id)


def release_replaced_original(
    session: Session, replacement: VenueBooking, *, actor_id: str, now: datetime
) -> VenueBooking | None:
    """AC7: release the original in the approval's transaction, once.

    An Approved original is Cancelled and a Requested one Withdrawn, each with a history entry
    naming its replacement. An original already released by another route is left alone.
    """

    from app.exact_venue_bookings import lock_booking
    from app.venue_booking_history import record_booking_transition
    from app.venue_conflicts import transition_booking_status

    if replacement.replaces_booking_id is None:
        return None
    original = lock_booking(session, replacement.replaces_booking_id)
    if original is None or original.status not in ACTIVE_BOOKING_STATUSES:
        return None
    previous = original.status
    resulting = "cancelled" if previous == "approved" else "withdrawn"
    transition_booking_status(session, original, resulting)
    venue = session.get(Venue, replacement.venue_id)
    record_booking_transition(
        session,
        original.id,
        action="replaced",
        previous_status=previous,
        resulting_status=resulting,
        actor_account_id=actor_id,
        changed_at=now,
        note=f"Replaced by the {venue.name} booking (#{replacement.id}).",
    )
    return original


def serialize_replacement_links(session: Session, booking: VenueBooking) -> dict:
    """Both directions of the link, kept after release so either history explains the other."""

    replaces = (
        session.get(VenueBooking, booking.replaces_booking_id)
        if booking.replaces_booking_id
        else None
    )
    replaced_by = session.scalars(
        select(VenueBooking)
        .where(VenueBooking.replaces_booking_id == booking.id)
        .order_by(VenueBooking.id.desc())
    ).all()
    return {
        "replaces": _link(session, replaces) if replaces else None,
        "replacements": [_link(session, item) for item in replaced_by],
        "replaceable": booking.status in ACTIVE_BOOKING_STATUSES
        and is_disrupted(session, booking)
        and not any(item.status == "requested" for item in replaced_by),
    }


def _link(session: Session, booking: VenueBooking) -> dict:
    venue = session.get(Venue, booking.venue_id)
    return {
        "id": booking.id,
        "venue": {"id": venue.id, "name": venue.name},
        "status": booking.status,
    }
