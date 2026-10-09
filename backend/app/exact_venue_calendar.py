"""SPL-138 calendar adapter: stored occupancy, shared intervals, anonymous reasons."""

from datetime import datetime, time, timedelta

from flask import abort
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.exact_venue_bookings import interval_from_json
from app.models import VenueBooking, VenueOperationalBlock
from app.venue_operational_blocks import block_intervals
from app.venue_timing import SGT, Interval, legacy_slot_interval, opening_covers, validate_intervals


def exact_calendar(session, venue, start, end):
    try:
        limit = datetime.combine(end, time(), SGT) + timedelta(days=1)
    except OverflowError:
        abort(400, "Calendar range exceeds supported dates.")
    window = Interval(datetime.combine(start, time(), SGT), limit)
    records = []
    uncertain = False
    bookings = session.scalars(
        select(VenueBooking)
        .where(
            VenueBooking.venue_id == venue.id, VenueBooking.status.in_(("requested", "approved"))
        )
        .options(selectinload(VenueBooking.occupancy))
    ).all()

    def add(interval, status, key, label):
        if interval.overlaps(window):
            records.append((interval, status, {"key": key, "label": label, "detail": label}))

    for booking in bookings:
        status = "booked" if booking.status == "approved" else "requested"
        label = "Approved booking" if status == "booked" else "Requested booking"
        if booking.exact_timing:
            event = interval_from_json(booking.exact_timing["event"])
            occupied = interval_from_json(booking.exact_timing["occupied"])
            add(event, status, "booking", label)
            if occupied.start < event.start:
                add(Interval(occupied.start, event.start), "preparation", "setup", "Setup")
            if event.end < occupied.end:
                add(Interval(event.end, occupied.end), "preparation", "turnaround", "Turnaround")
        elif not booking.occupancy:
            uncertain = True
        for claim in booking.occupancy:
            add(
                legacy_slot_interval(claim.day, claim.slot),
                status if claim.kind == "event" else "preparation",
                "booking" if claim.kind == "event" else claim.kind,
                label if claim.kind == "event" else claim.kind.capitalize(),
            )
    blocks = session.scalars(
        select(VenueOperationalBlock).where(
            VenueOperationalBlock.venue_id == venue.id,
            VenueOperationalBlock.removed_at.is_(None),
            VenueOperationalBlock.start_date <= end,
            VenueOperationalBlock.end_date >= start,
        )
    ).all()
    for block in blocks:
        for interval in block_intervals(block, start, end):
            add(interval, "blocked", "block", "Operational closure")
    try:
        hours = (
            validate_intervals(venue.operating_intervals)
            if venue.operating_intervals is not None
            else None
        )
    except ValueError:
        hours = None
    if venue.setup_minutes is None or venue.turnaround_minutes is None:
        hours = None
    days = []
    day = start
    precedence = ("blocked", "booked", "requested", "preparation")
    while day <= end:
        base = datetime.combine(day, time(), SGT)
        finish = base + timedelta(days=1)
        points = {base, finish}
        for interval, _, _ in records:
            if interval.start < finish and interval.end > base:
                points.update((max(base, interval.start), min(finish, interval.end)))
        for begin, stop in hours or []:
            points.update((base + timedelta(minutes=begin), base + timedelta(minutes=stop)))
        ordered = sorted(points)
        segments = []
        for left, right in zip(ordered, ordered[1:]):
            segment = Interval(left, right)
            matches = [
                (status, reason)
                for interval, status, reason in records
                if segment.overlaps(interval)
            ]
            reasons = []
            for _, reason in matches:
                if reason not in reasons:
                    reasons.append(reason)
            status = next(
                (candidate for candidate in precedence if any(s == candidate for s, _ in matches)),
                None,
            )
            if hours is None or uncertain:
                reasons.append(
                    {
                        "key": "review",
                        "label": "Timing review required",
                        "detail": "Availability cannot be confirmed.",
                    }
                )
            if status is None:
                status = (
                    "review_required"
                    if hours is None or uncertain
                    else ("available" if opening_covers(segment, hours) else "not_operated")
                )
            segments.append({**segment.serialize(), "status": status, "reasons": reasons})
        days.append({"date": day.isoformat(), "intervals": segments})
        if day == end:
            break
        day += timedelta(days=1)
    return {
        "mode": "exact",
        "venue": {"id": venue.id, "name": venue.name},
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "days": days,
    }
