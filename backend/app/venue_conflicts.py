"""Shared atomic venue-occupancy policy for SPL-83 consumers."""

from datetime import date
from typing import Iterable

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import (
    ACTIVE_BOOKING_STATUSES,
    BOOKING_STATUSES,
    VenueBooking,
    VenueBookingOccupancy,
)
from app.slots import VenueOccupancySlot, derive_venue_occupancy
from app.venue_operational_blocks import operational_block_for_slot
from app.venue_slot_locks import lock_venue_slots


class VenueOccupancyConflict(Exception):
    """A dated venue slot is already occupied by a booking or operational block."""

    def __init__(self, day: date, slot: str, source: str):
        self.day = day
        self.slot = slot
        self.source = source
        super().__init__(f"Venue is unavailable on {day.isoformat()} during {slot}.")


def claim_venue_occupancy(
    session: Session,
    booking: VenueBooking,
    *,
    event_slots: Iterable[tuple[date, str]],
) -> tuple[VenueOccupancySlot, ...]:
    """Claim all event and venue-required preparation slots for one active booking."""

    if booking.status not in ACTIVE_BOOKING_STATUSES:
        raise ValueError("Only Requested or Approved bookings occupy venue time.")
    from app.exact_venue_bookings import lock_venue

    venue = lock_venue(session, booking.venue_id)
    if venue is None:
        raise ValueError("Booking venue does not exist.")
    required = derive_venue_occupancy(
        event_slots,
        setup_buffer_slots=venue.setup_buffer_slots,
        turnaround_buffer_slots=venue.turnaround_buffer_slots,
    )
    lock_venue_slots(
        session,
        booking.venue_id,
        ((occupied.date, occupied.slot) for occupied in required),
    )
    for occupied in required:
        _refuse_exact_overlap(session, booking, occupied.date, occupied.slot)
        if operational_block_for_slot(session, booking.venue_id, occupied.date, occupied.slot):
            raise VenueOccupancyConflict(occupied.date, occupied.slot, source="operational_block")
        existing = session.scalar(
            select(VenueBookingOccupancy.id).where(
                VenueBookingOccupancy.venue_id == booking.venue_id,
                VenueBookingOccupancy.day == occupied.date,
                VenueBookingOccupancy.slot == occupied.slot,
            )
        )
        if existing is not None:
            raise VenueOccupancyConflict(occupied.date, occupied.slot, source="booking")
    conflicting_slot = required[0]
    try:
        with session.begin_nested():
            for occupied in required:
                conflicting_slot = occupied
                session.add(
                    VenueBookingOccupancy(
                        booking_id=booking.id,
                        venue_id=booking.venue_id,
                        day=occupied.date,
                        slot=occupied.slot,
                        kind=occupied.kind.value,
                    )
                )
                session.flush()
    except IntegrityError as exc:
        raise VenueOccupancyConflict(
            conflicting_slot.date, conflicting_slot.slot, source="booking"
        ) from exc
    return required


def occupancy_for_booking(session: Session, booking_id: int) -> tuple[VenueBookingOccupancy, ...]:
    """Return a booking's currently claimed slots in chronological slot order."""

    return tuple(
        session.scalars(
            select(VenueBookingOccupancy)
            .where(VenueBookingOccupancy.booking_id == booking_id)
            .order_by(VenueBookingOccupancy.day, VenueBookingOccupancy.id)
        )
    )


def transition_booking_status(
    session: Session, booking: VenueBooking, resulting_status: str
) -> None:
    """Apply lifecycle occupancy semantics inside the caller's transaction."""

    if resulting_status not in BOOKING_STATUSES:
        raise ValueError("Unknown venue-booking status.")
    if booking.exact_timing and resulting_status == "approved":
        from flask import abort

        from app.exact_venue_bookings import exact_review_reasons

        reasons = exact_review_reasons(session, booking)
        if reasons:
            abort(409, "; ".join(reasons))
        booking.status = resulting_status
        session.flush()
        return
    if resulting_status == "approved":
        occupied_slots = occupancy_for_booking(session, booking.id)
        if not occupied_slots:
            raise ValueError("An Approved booking must occupy venue time.")
        for occupied in occupied_slots:
            _refuse_exact_overlap(session, booking, occupied.day, occupied.slot)
            if operational_block_for_slot(session, booking.venue_id, occupied.day, occupied.slot):
                raise VenueOccupancyConflict(
                    occupied.day, occupied.slot, source="operational_block"
                )
    if resulting_status not in ACTIVE_BOOKING_STATUSES:
        session.execute(
            delete(VenueBookingOccupancy).where(VenueBookingOccupancy.booking_id == booking.id)
        )
    booking.status = resulting_status
    session.flush()


def _refuse_exact_overlap(session, booking, day, slot):
    from app.exact_venue_bookings import interval_from_json
    from app.venue_timing import legacy_slot_interval

    requested = legacy_slot_interval(day, slot)
    candidates = session.scalars(
        select(VenueBooking).where(
            VenueBooking.venue_id == booking.venue_id,
            VenueBooking.id != booking.id,
            VenueBooking.status.in_(ACTIVE_BOOKING_STATUSES),
        )
    )
    for candidate in candidates:
        if candidate.exact_timing and requested.overlaps(
            interval_from_json(candidate.exact_timing["occupied"])
        ):
            raise VenueOccupancyConflict(day, slot, source="booking")
