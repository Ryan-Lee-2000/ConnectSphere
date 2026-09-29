"""Venue Staff review, approval and rejection of a Requested venue booking for SPL-81 (CS-E10-S3)
and SPL-82 (CS-E10-S4).

Approval rechecks the slots recorded on the request (SPL-87), not slots re-derived from venue
settings changed afterwards (Q120). The booking row is locked for the whole transaction, the
recorded slots are locked with SPL-83's slot locks so blocks and other claims queue behind it, and
SPL-83's ``transition_booking_status`` performs the final operational-block recheck. A conflict
rolls back the status and the approval record together
(docs/development/SPL-77-integration-contract.md).

Rejection commits nothing, so it rechecks neither slots nor the event's status
(docs/tasks/SPL-82.md): only the booking's own ``Requested`` status gates it, the same rule SPL-78's
withdrawal already uses. ``transition_booking_status`` frees its occupancy through the same shared
lifecycle rule.
"""

from datetime import date, datetime

from flask import Flask, abort, g, jsonify, request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.authorization import require_roles
from app.coordinator_assignment import MAX_EVENT_REQUEST_ID
from app.event_requests import SINGAPORE
from app.models import EventRequest, Role, Venue, VenueBooking, VenueBookingOccupancy
from app.venue_booking_history import record_booking_transition
from app.venue_booking_queue import decision_event_details
from app.venue_booking_requests import serialize_venue_booking
from app.venue_booking_status import _review
from app.venue_conflicts import VenueOccupancyConflict, transition_booking_status
from app.venue_slot_locks import lock_venue_slots

PLANNING = "planning"
REQUESTED = "requested"
APPROVED = "approved"
REJECTED = "rejected"
MAX_NOTE_LENGTH = 1000
MAX_REASON_LENGTH = 1000
MAX_SUGGESTION_LENGTH = 1000
NOT_FOUND = "Venue-booking request not found."
ONLY_REQUESTED = "Only a Requested venue-booking request can be approved."
ONLY_REQUESTED_TO_REJECT = "Only a Requested venue-booking request can be rejected."
ONLY_PLANNING = "The event must be in Planning for its venue booking to be approved."
SLOT_NAMES = {"AM": "AM", "PM": "PM", "NIGHT": "Night"}


def register_venue_booking_approval_routes(app: Flask) -> None:
    @app.get("/api/venue-bookings/<int:booking_id>")
    @require_roles(Role.VENUE_STAFF)
    def review_venue_booking(booking_id: int):
        with Session(app.extensions["engine"]) as session:
            booking = _booking(session, booking_id)
            event = session.get(EventRequest, booking.event_request_id)
            return jsonify(
                booking=serialize_venue_booking(session, booking),
                # SPL-80 owns what Venue Staff need in order to decide (CS-E10-S2 AC3) and which
                # event fields they may see at all (AC4). Additive: id, name and status are still
                # returned with the same values this route has always returned.
                event=decision_event_details(session, event),
                review=_review(session, booking),
            )

    @app.post("/api/venue-bookings/<int:booking_id>/approve")
    @require_roles(Role.VENUE_STAFF)
    def approve_venue_booking(booking_id: int):
        note = _approval_note()
        with Session(app.extensions["engine"]) as session:
            # Row lock: a concurrent approval or withdrawal waits here, then sees the outcome (AC7).
            booking = _booking(session, booking_id, lock=True)
            if booking.status != REQUESTED:
                abort(409, ONLY_REQUESTED)
            if session.get(EventRequest, booking.event_request_id).status != PLANNING:
                abort(409, ONLY_PLANNING)
            venue = session.get(Venue, booking.venue_id)
            try:
                _recheck_recorded_slots(session, booking)
                transition_booking_status(session, booking, APPROVED)
            except VenueOccupancyConflict as conflict:
                session.rollback()
                return jsonify(
                    error=f"{venue.name} is unavailable on {_day_name(conflict.day)} during "
                    f"{SLOT_NAMES.get(conflict.slot, conflict.slot)}.",
                    conflict={"date": conflict.day.isoformat(), "slot": conflict.slot},
                ), 409
            booking.approved_by_account_id = g.user_id
            booking.approved_at = datetime.now(SINGAPORE)
            booking.approval_note = note
            # SPL-79: the approval and its note are appended to the booking's status history.
            record_booking_transition(
                session,
                booking.id,
                action="approve",
                previous_status=REQUESTED,
                resulting_status=APPROVED,
                actor_account_id=g.user_id,
                changed_at=booking.approved_at,
                note=note,
            )
            session.commit()
            return jsonify(booking=serialize_venue_booking(session, booking))

    # SPL-82 (CS-E10-S4). Default-deny: require_roles refuses every role but Venue Staff with 403,
    # and a missing session is refused with 401 before this function runs (AC7).
    @app.post("/api/venue-bookings/<int:booking_id>/reject")
    @require_roles(Role.VENUE_STAFF)
    def reject_venue_booking(booking_id: int):
        # Validate the body first, before touching the database, so an invalid rejection can
        # never leave a half-written change behind (AC2, AC6, AC7).
        reason, alternative_suggestion = _rejection_body()
        with Session(app.extensions["engine"]) as session:
            # Row lock: a concurrent approval or withdrawal waits here, then sees Rejected (AC7).
            booking = _booking(session, booking_id, lock=True)
            # AC1: only Requested. Approved, Rejected, Withdrawn and Cancelled are all refused.
            # Deliberately no check on the event's status, unlike approval: rejecting commits no
            # venue time, so there is nothing to protect (docs/tasks/SPL-82.md).
            if booking.status != REQUESTED:
                abort(409, ONLY_REQUESTED_TO_REJECT)
            # AC4: the shared SPL-83 lifecycle rule deletes the occupancy rows for any status that
            # is not Requested or Approved, so the event, setup and turnaround slots are freed
            # here with no rejection-specific code.
            transition_booking_status(session, booking, REJECTED)
            # AC3: who, when and why are server-owned; the client only ever supplies the text.
            booking.rejected_by_account_id = g.user_id
            booking.rejected_at = datetime.now(SINGAPORE)
            booking.rejection_reason = reason
            booking.rejection_alternative_suggestion = alternative_suggestion
            # SPL-79: the rejection is appended to the booking's status history, reason as its note.
            # That history panel already shows notes, which is how the coordinator sees the
            # reason (AC5) without any new coordinator-facing screen.
            record_booking_transition(
                session,
                booking.id,
                action="reject",
                previous_status=REQUESTED,
                resulting_status=REJECTED,
                actor_account_id=g.user_id,
                changed_at=booking.rejected_at,
                note=reason,
            )
            session.commit()
            return jsonify(booking=serialize_venue_booking(session, booking))


def _booking(session: Session, booking_id: int, *, lock: bool = False) -> VenueBooking:
    if booking_id > MAX_EVENT_REQUEST_ID:
        abort(404, NOT_FOUND)
    query = select(VenueBooking).where(VenueBooking.id == booking_id)
    booking = session.scalar(query.with_for_update() if lock else query)
    if booking is None:
        abort(404, NOT_FOUND)
    return booking


def _recorded_slots(booking: VenueBooking) -> list[tuple[date, str]]:
    """The setup, event and turnaround slots recorded on the request, in time order."""

    slots = [
        (booking.setup_date, booking.setup_slot),
        *((booking.booking_date, slot) for slot in booking.event_slots or []),
        (booking.turnaround_date, booking.turnaround_slot),
    ]
    # A venue without preparation buffers records no setup or turnaround slot.
    return [(day, slot) for day, slot in slots if day and slot]


def _recheck_recorded_slots(session: Session, booking: VenueBooking) -> None:
    """AC2: no recorded slot may be held by another active booking.

    Occupancy rows exist only for Requested and Approved bookings, so any row on a recorded slot
    that is not this booking's own belongs to another active booking. Operational blocks are
    rechecked by ``transition_booking_status`` over the booking's claimed rows.
    """

    recorded = _recorded_slots(booking)
    lock_venue_slots(session, booking.venue_id, recorded)
    for day, slot in recorded:
        holder = session.scalar(
            select(VenueBookingOccupancy.booking_id).where(
                VenueBookingOccupancy.venue_id == booking.venue_id,
                VenueBookingOccupancy.day == day,
                VenueBookingOccupancy.slot == slot,
            )
        )
        if holder is not None and holder != booking.id:
            raise VenueOccupancyConflict(day, slot, source="booking")


def _approval_note() -> str | None:
    """At most an optional note; the approver, time and status are server-owned (Q110)."""

    if request.content_length in (None, 0):
        return None
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or not set(data) <= {"note"}:
        abort(400, "Approval accepts only an optional note.")
    note = data.get("note")
    if note is None:
        return None
    if not isinstance(note, str):
        abort(400, "The approval note must be text.")
    note = note.strip()
    if len(note) > MAX_NOTE_LENGTH:
        abort(400, f"Keep the approval note to {MAX_NOTE_LENGTH} characters or fewer.")
    return note or None


def _rejection_body() -> tuple[str, str | None]:
    """A required, non-blank reason and an optional alternative suggestion; nothing else (AC2, AC6).

    The two are kept as separate fields rather than one free-text box, so a rejection cannot carry
    a suggestion with no reason, and the required reason is never buried inside optional text
    (docs/tasks/SPL-82.md).
    """

    data = request.get_json(silent=True)
    # AC6: an allowlist of exactly two keys. Sending venue_id, layout, event_slots or status is
    # refused outright, rather than silently ignored, so rejecting can never amend the request.
    if not isinstance(data, dict) or not set(data) <= {"reason", "alternative_suggestion"}:
        abort(400, "Rejection accepts only a reason and an optional alternative suggestion.")
    reason = data.get("reason")
    # AC2: "non-blank" means whitespace-only is refused too, not just an empty string.
    if not isinstance(reason, str) or not reason.strip():
        abort(400, "A rejection reason is required.")
    reason = reason.strip()
    if len(reason) > MAX_REASON_LENGTH:
        abort(400, f"Keep the rejection reason to {MAX_REASON_LENGTH} characters or fewer.")
    # AC2: the suggestion is optional. Missing, null and blank all store as null.
    suggestion = data.get("alternative_suggestion")
    if suggestion is not None:
        if not isinstance(suggestion, str):
            abort(400, "The alternative suggestion must be text.")
        suggestion = suggestion.strip() or None
        if suggestion and len(suggestion) > MAX_SUGGESTION_LENGTH:
            abort(
                400,
                f"Keep the alternative suggestion to {MAX_SUGGESTION_LENGTH} characters or fewer.",
            )
    return reason, suggestion


def _day_name(day: date) -> str:
    return f"{day.day} {day:%b %Y}"
