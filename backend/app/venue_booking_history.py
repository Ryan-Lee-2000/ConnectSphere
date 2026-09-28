"""Append-only venue-booking status history (SPL-79).

Every action that changes a booking's status records one entry here, inside the same transaction,
so the history can never disagree with the booking. SPL-77 (request) and SPL-78 (withdraw) write
through ``record_booking_transition``; SPL-81 (approve, with note) and SPL-82 (reject, with reason)
are expected to do the same.
"""

from datetime import datetime

from sqlalchemy.orm import Session

from app.models import VenueBookingStatusHistory

BOOKING_STATUS_LABELS = {
    "requested": "Requested",
    "approved": "Approved",
    "rejected": "Rejected",
    "withdrawn": "Withdrawn",
    "cancelled": "Cancelled",
}


def booking_status_label(status: str) -> str:
    return BOOKING_STATUS_LABELS[status]


def record_booking_transition(
    session: Session,
    booking_id: int,
    *,
    action: str,
    previous_status: str | None,
    resulting_status: str,
    actor_account_id: str,
    changed_at: datetime,
    note: str | None = None,
) -> VenueBookingStatusHistory:
    """Append one status change in the caller's transaction."""

    entry = VenueBookingStatusHistory(
        booking_id=booking_id,
        action=action,
        previous_status=previous_status,
        resulting_status=resulting_status,
        actor_account_id=actor_account_id,
        changed_at=changed_at,
        note=note,
    )
    session.add(entry)
    return entry
