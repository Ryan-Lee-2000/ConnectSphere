"""Exact booking evidence and shared venue transaction boundary (SPL-137).

Lock order: event, assignment (coordinator actions), venue, booking, legacy slots.
Venue-only writers never acquire event/assignment locks. All callers commit atomically.
"""

from datetime import datetime

from flask import abort
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.models import EventCoordinatorAssignment, EventRequest, Venue, VenueBooking
from app.venue_timing import Interval, parse_event_interval

REQUIREMENT_FIELDS = (
    "expected_attendance",
    "preferred_room_layout",
    "required_facilities",
    "accessibility_needs",
    "location_preference",
    "facilities_notes",
    "venue_notes",
)


def lock_venue(session, venue_id):
    return session.scalar(
        select(Venue)
        .where(Venue.id == venue_id)
        .options(selectinload(Venue.layouts))
        .with_for_update(key_share=True)
        .execution_options(populate_existing=True)
    )


def lock_event(session, event_id, coordinator_id=None):
    # NO KEY UPDATE still serializes event edits, but permits the foreign-key reads
    # needed by assignment history while we wait for a concurrent reassignment.
    event = session.scalar(
        select(EventRequest)
        .where(EventRequest.id == event_id)
        .with_for_update(key_share=True)
        .execution_options(populate_existing=True)
    )
    if coordinator_id is not None:
        assignment = session.scalar(
            select(EventCoordinatorAssignment)
            .where(EventCoordinatorAssignment.event_request_id == event_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if assignment is None or assignment.coordinator_account_id != coordinator_id:
            abort(404, "Assigned event not found.")
    return event


def lock_booking(session, booking_id, coordinator_id=None):
    identity = session.execute(
        select(VenueBooking.event_request_id, VenueBooking.venue_id).where(
            VenueBooking.id == booking_id
        )
    ).first()
    if identity is None:
        return None
    lock_event(session, identity.event_request_id, coordinator_id)
    lock_venue(session, identity.venue_id)
    return session.scalar(
        select(VenueBooking)
        .where(VenueBooking.id == booking_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )


def requirements(event):
    return {key: getattr(event, key) for key in REQUIREMENT_FIELDS} | {
        "proposed_date": event.proposed_date.isoformat() if event.proposed_date else None,
        "start_time": event.start_time.isoformat() if event.start_time else None,
        "end_time": event.end_time.isoformat() if event.end_time else None,
    }


def interval_from_json(value):
    return Interval(datetime.fromisoformat(value["start"]), datetime.fromisoformat(value["end"]))


def saved_event_interval(event):
    """SPL-137 retains SPL-77's saved-event schedule for a single booking."""
    if not event.proposed_date or not event.start_time or not event.end_time:
        raise ValueError("Record a valid saved event date and quarter-hour times.")
    if any((value.second or value.microsecond) for value in (event.start_time, event.end_time)):
        raise ValueError("Review the saved event's time precision before requesting a booking.")
    return parse_event_interval(
        event.proposed_date.isoformat(),
        event.start_time.strftime("%H:%M"),
        event.end_time.strftime("%H:%M"),
    )


def exact_review_reasons(session, booking):
    if not booking.exact_timing or booking.status not in ("requested", "approved"):
        return []
    from app.exact_venue_availability import exact_availability
    from app.venue_availability import profile_suitability_checks
    from app.venue_booking_requests import _selected_layout

    venue = session.get(Venue, booking.venue_id)
    event = session.get(EventRequest, booking.event_request_id)
    reasons = []
    if booking.reviewed_requirements != requirements(event):
        reasons.append("Event requirements changed. Review and submit a new request.")
    if _selected_layout(venue.layouts, booking.layout, event) is None:
        reasons.append("The requested layout no longer holds the expected attendance.")
    reasons.extend(
        check["detail"] for check in profile_suitability_checks(venue, event) if not check["passed"]
    )
    try:
        if interval_from_json(booking.exact_timing["event"]) != saved_event_interval(event):
            reasons.append(
                "Booking date and times do not match the saved event. "
                "Review and submit a new request."
            )
        available, detail, timing = exact_availability(
            session,
            venue,
            interval_from_json(booking.exact_timing["event"]),
            exclude_booking_id=booking.id,
        )
        if not available:
            reasons.append(detail)
        if timing and timing["occupied"] != booking.exact_timing["occupied"]:
            reasons.append("Preparation requirements changed. Review and submit a new request.")
    except (ValueError, KeyError, TypeError):
        reasons.append("Booking timing evidence requires review.")
    return reasons


def cancel_booking(session, booking_id, *, coordinator_id, changed_at, note=None):
    """Assigned coordinator cancels one Approved booking, once, in the caller transaction.

    SPL-131 exposes this action in its arrangement UI. Actor must come from authenticated
    request context, never submitted JSON. No commit here: arrangement updates
    share the transaction.
    """
    from app.venue_conflicts import transition_booking_status
    from app.venue_timing import SGT

    if changed_at.utcoffset() is None:
        raise ValueError("Cancellation requires an aware timestamp.")
    changed_at = changed_at.astimezone(SGT)
    from app.venue_booking_history import record_booking_transition

    booking = lock_booking(session, booking_id, coordinator_id)
    if booking is None:
        abort(404, "Venue-booking request not found.")
    if booking.status != "approved":
        abort(409, "Only an Approved venue booking can be cancelled.")
    transition_booking_status(session, booking, "cancelled")
    record_booking_transition(
        session,
        booking.id,
        action="cancel",
        previous_status="approved",
        resulting_status="cancelled",
        actor_account_id=coordinator_id,
        changed_at=changed_at,
        note=note,
    )
    return booking
