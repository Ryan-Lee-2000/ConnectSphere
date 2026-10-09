"""Venue occupancy calendar for SPL-88 (CS-E11-S1).

Read-only throughout: SPL-88 adds no table, no column and no migration. Every value it returns is
already stored by SPL-77/SPL-83 (the occupancy rows a booking claims), SPL-87 (which of those rows
are setup or turnaround) and SPL-89 (operational blocks).

Four rules from the story shape this module, all recorded in docs/tasks/SPL-88.md and raised on the
Jira story for the team to confirm:

* **A slot can have more than one reason, so it carries a list of them and one headline status.**
  AC2 asks for a single label; AC4 says a slot with several reasons must not collapse to Available.
  Both hold by returning the most serious label plus every applicable reason.
* **Preparation is decided by the occupancy row's kind, not the booking's status.** A setup slot
  belongs to preparation whether its booking is Requested or Approved; only the booking's own event
  slots split into Requested and Booked.
* **"Authorised internal user" is the three roles that schedule venues.** Organisers and attendees
  hold no operational interest in a venue's calendar.
* **The calendar never names who holds a slot.** Coordinators see other organisations' occupancy
  here, so naming the event or organisation would repeat the disclosure SPL-80's allowlist avoids.
"""

from datetime import date, timedelta
from typing import Any

from flask import Flask, abort, jsonify, request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.authorization import require_roles
from app.models import Role, Venue, VenueBooking, VenueBookingOccupancy
from app.slots import OPERATING_SLOTS
from app.venue_operational_blocks import operational_block_for_slot

MAX_VENUE_ID = 2**31 - 1
MAX_RANGE_DAYS = 31
NOT_FOUND = "Venue not found."

AVAILABLE = "available"
NOT_OPERATED = "not_operated"
BLOCKED = "blocked"
BOOKED = "booked"
REQUESTED = "requested"
PREPARATION = "preparation"

# Most serious first. A slot shows the first status in this order that applies to it; anything not
# listed here has no occupancy at all and is Available.
STATUS_PRECEDENCE = (BLOCKED, BOOKED, REQUESTED, PREPARATION)

# The status an occupancy row implies, by the booking status and the row's own kind. Occupancy rows
# exist only for Requested and Approved bookings (SPL-83's lifecycle rule), so a row whose booking
# has since been rejected, withdrawn or cancelled is already gone by the time this reads it.
_EVENT_SLOT_STATUS = {"requested": REQUESTED, "approved": BOOKED}


def register_venue_occupancy_calendar_routes(app: Flask) -> None:
    @app.get("/api/venues/<int:venue_id>/occupancy")
    @require_roles(Role.VENUE_STAFF, Role.EVENT_COORDINATOR, Role.EVENT_OPERATIONS_MANAGER)
    def venue_occupancy_calendar(venue_id: int):
        start, end = _requested_range()
        with Session(app.extensions["engine"]) as session:
            venue = _find_venue(session, venue_id)
            if app.config["EXACT_VENUE_TIMING_ENABLED"]:
                from app.exact_venue_calendar import exact_calendar

                return jsonify(exact_calendar(session, venue, start, end))
            supported = set(venue.operating_slots or [])
            days = [
                {
                    "date": day.isoformat(),
                    "slots": [
                        _slot_entry(session, venue_id, day, slot, supported)
                        for slot in OPERATING_SLOTS
                    ],
                }
                for day in _days_in_range(start, end)
            ]
            return jsonify(
                venue={"id": venue.id, "name": venue.name},
                start_date=start.isoformat(),
                end_date=end.isoformat(),
                days=days,
            )


def _slot_entry(
    session: Session, venue_id: int, day: date, slot: str, supported: set[str]
) -> dict[str, Any]:
    """One slot's headline status and every reason behind it (AC2, AC4, AC5, AC7)."""

    # AC5: a slot the venue does not operate is its own state, never confused with Available.
    if slot not in supported:
        return {"slot": slot, "status": NOT_OPERATED, "reasons": []}

    reasons = _reasons(session, venue_id, day, slot)
    status = next(
        (
            candidate
            for candidate in STATUS_PRECEDENCE
            if candidate in {r["status"] for r in reasons}
        ),
        AVAILABLE,
    )
    return {
        "slot": slot,
        "status": status,
        "reasons": [{key: reason[key] for key in ("key", "label", "detail")} for reason in reasons],
    }


def _reasons(session: Session, venue_id: int, day: date, slot: str) -> list[dict[str, Any]]:
    """Every applicable reason, in the shared {key, label, detail} shape SPL-71/75 established.

    A slot can hold both at once: SPL-89 records a block over an existing booking and marks that
    booking for review rather than reverting it, so the booking's occupancy row survives the block.
    """

    reasons: list[dict[str, Any]] = []
    occupancy = session.scalar(
        select(VenueBookingOccupancy).where(
            VenueBookingOccupancy.venue_id == venue_id,
            VenueBookingOccupancy.day == day,
            VenueBookingOccupancy.slot == slot,
        )
    )
    if occupancy is not None:
        reasons.append(_occupancy_reason(session, occupancy))
    if block := operational_block_for_slot(session, venue_id, day, slot):
        reasons.append(
            {
                "key": "block",
                "status": BLOCKED,
                "label": "Operational block",
                "detail": block.reason,
            }
        )
    return reasons


def _occupancy_reason(session: Session, occupancy: VenueBookingOccupancy) -> dict[str, Any]:
    """Why a booking holds this slot, without naming the booking, event or organisation (AC4)."""

    if occupancy.kind != "event":
        return {
            "key": "preparation",
            "status": PREPARATION,
            "label": "Preparation",
            # Setup and turnaround are the venue's own changeover time, not the event's.
            "detail": f"Venue {occupancy.kind} time for a booking on a neighbouring slot.",
        }
    booking = session.get(VenueBooking, occupancy.booking_id)
    status = _EVENT_SLOT_STATUS[booking.status]
    return {
        "key": "booking",
        "status": status,
        "label": "Approved booking" if status == BOOKED else "Requested booking",
        "detail": (
            "The venue is committed for an approved booking."
            if status == BOOKED
            else "A venue-booking request is holding this slot while it awaits review."
        ),
    }


def _days_in_range(start: date, end: date) -> list[date]:
    return [start + timedelta(days=offset) for offset in range((end - start).days + 1)]


def _requested_range() -> tuple[date, date]:
    """A bounded Singapore date range; a single day is start == end (AC1).

    The 31-day cap keeps one request's work proportionate: every day costs three slot lookups, so an
    unbounded range would let one call scan arbitrarily far.
    """

    start = _date_argument("start_date")
    end = _date_argument("end_date")
    if end < start:
        abort(400, "The end date must not be before the start date.")
    if (end - start).days + 1 > MAX_RANGE_DAYS:
        abort(400, f"Request at most {MAX_RANGE_DAYS} days at a time.")
    return start, end


def _date_argument(name: str) -> date:
    raw = request.args.get(name)
    if not raw:
        abort(400, f"{name.replace('_', ' ').capitalize()} is required.")
    try:
        return date.fromisoformat(raw)
    except ValueError:
        abort(400, f"{name.replace('_', ' ').capitalize()} must use YYYY-MM-DD.")


def _find_venue(session: Session, venue_id: int) -> Venue:
    if venue_id > MAX_VENUE_ID:
        abort(404, NOT_FOUND)
    venue = session.get(Venue, venue_id)
    if venue is None:
        abort(404, NOT_FOUND)
    return venue
