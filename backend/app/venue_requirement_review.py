"""Per-arrangement requirement assessment and event-change handoff (SPL-106)."""

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import ACTIVE_BOOKING_STATUSES, EventRequest, Venue, VenueBooking

REQUIREMENT_REASON_TYPES = frozenset(
    {"layout_capacity", "facilities", "accessibility", "location", "attendance", "event_times"}
)


def requirement_reasons(venue: Venue, event: EventRequest, booking: VenueBooking):
    from app.exact_venue_bookings import interval_from_json, saved_event_interval
    from app.venue_arrangements import (
        arrangement_checks,
        booking_attendee_count,
        booking_facilities,
        within_event,
    )

    reasons = []
    count = booking_attendee_count(booking, event)
    checks = arrangement_checks(
        venue,
        event,
        layout_name=booking.layout,
        attendee_count=count,
        facilities=booking_facilities(booking, event),
    )
    for check in checks:
        if not check["passed"]:
            reasons.append((f"requirement:{check['key']}", check["key"], check["detail"]))
    if (
        count is not None
        and event.expected_attendance is not None
        and count > event.expected_attendance
    ):
        reasons.append(
            (
                "requirement:attendance",
                "attendance",
                "This booking's attendee count is above the event's expected attendance.",
            )
        )
    if booking.exact_timing:
        try:
            inside = within_event(
                interval_from_json(booking.exact_timing["event"]), saved_event_interval(event)
            )
        except (ValueError, KeyError, TypeError):
            inside = False
        if not inside:
            reasons.append(
                (
                    "requirement:event-times",
                    "event_times",
                    "Booking date and times fall outside the saved event "
                    "or require valid timing evidence.",
                )
            )
    else:
        from app.slots import slots_for_range

        slots = (
            slots_for_range(event.start_time, event.end_time)
            if event.start_time and event.end_time
            else []
        )
        if booking.booking_date != event.proposed_date or set(booking.event_slots or []) != set(
            slots
        ):
            reasons.append(
                (
                    "requirement:event-times",
                    "event_times",
                    "The booked date or slots differ from the event's saved schedule.",
                )
            )
    return reasons


def legacy_timing_reasons(session: Session, venue: Venue, booking: VenueBooking):
    from app.slots import derive_venue_occupancy
    from app.venue_booking_assessment import _protected_intervals
    from app.venue_operational_blocks import operational_block_for_slot
    from app.venue_timing import legacy_slot_interval

    try:
        slots = derive_venue_occupancy(
            [(booking.booking_date, slot) for slot in booking.event_slots or []],
            setup_buffer_slots=venue.setup_buffer_slots,
            turnaround_buffer_slots=venue.turnaround_buffer_slots,
        )
        intervals = [legacy_slot_interval(slot.date, slot.slot) for slot in slots]
    except (ValueError, TypeError, OverflowError):
        return [
            (
                "historical-timing",
                "unresolved_historical_timing",
                "Booking slot evidence requires review.",
            )
        ]
    reasons = {}
    if any(slot.slot not in venue.operating_slots for slot in slots):
        reasons["outside-operating-hours"] = (
            "outside_operating_hours",
            "The booked slots are outside the venue's operating slots.",
        )
    for slot in slots:
        block = operational_block_for_slot(session, venue.id, slot.date, slot.slot)
        if block:
            reasons[f"operational-block:{block.id}"] = (
                "operational_block",
                f"Operational block: {block.reason}",
            )
    peers = session.scalars(
        select(VenueBooking).where(
            VenueBooking.venue_id == venue.id,
            VenueBooking.id != booking.id,
            VenueBooking.status.in_(ACTIVE_BOOKING_STATUSES),
        )
    ).all()
    for peer in peers:
        protected = _protected_intervals(peer)
        if not protected or any(
            interval.overlaps(other) for interval in intervals for other in protected
        ):
            reasons[f"overlap:{peer.id}"] = (
                "overlap",
                f"Booking {peer.id} protects or needs review of this venue's time.",
            )
    return [(key, kind, detail) for key, (kind, detail) in reasons.items()]


def assess_event_bookings(
    session: Session,
    event: EventRequest,
    *,
    assessed_by_account_id: str,
    assessed_at: datetime | None = None,
) -> int:
    """Call after a trusted event/arrangement edit, in its transaction; never commit here.

    SPL-109/112 must authorize and lock the event before editing it, then call this function
    before commit. Booking allocations and occupied intervals are never rewritten.
    """
    from app.venue_booking_assessment import _assess_bookings

    session.flush()
    venue_ids = session.scalars(
        select(VenueBooking.venue_id)
        .where(
            VenueBooking.event_request_id == event.id,
            VenueBooking.status.in_(ACTIVE_BOOKING_STATUSES),
        )
        .distinct()
        .order_by(VenueBooking.venue_id)
    ).all()
    venues = session.scalars(
        select(Venue)
        .where(Venue.id.in_(venue_ids))
        .order_by(Venue.id)
        .with_for_update()
        .options(selectinload(Venue.layouts))
        .execution_options(populate_existing=True)
    ).all()
    count = 0
    when = assessed_at or datetime.now(timezone.utc)
    for venue in venues:
        bookings = session.scalars(
            select(VenueBooking)
            .where(
                VenueBooking.event_request_id == event.id,
                VenueBooking.venue_id == venue.id,
                VenueBooking.status.in_(ACTIVE_BOOKING_STATUSES),
            )
            .order_by(VenueBooking.id)
            .options(selectinload(VenueBooking.occupancy))
            .with_for_update()
            .execution_options(populate_existing=True)
        ).all()
        count += _assess_bookings(session, venue, bookings, assessed_by_account_id, when)
    return count
