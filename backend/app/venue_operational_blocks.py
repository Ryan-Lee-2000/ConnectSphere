"""Venue operational-unavailability routes for SPL-89."""

from datetime import date, datetime, timedelta, timezone
from typing import Any

from flask import Flask, abort, g, jsonify, request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.authorization import require_roles
from app.models import (
    ACTIVE_BOOKING_STATUSES,
    Role,
    Venue,
    VenueBooking,
    VenueBookingOccupancy,
    VenueOperationalBlock,
)
from app.slots import OPERATING_SLOTS
from app.venue_slot_locks import lock_venue_slots


def operational_block_for_slot(
    session: Session, venue_id: int, day: date, slot: str
) -> VenueOperationalBlock | None:
    """Return the active block occupying one venue/date/slot, if any.

    This is the shared read boundary consumed by venue search, suitability and
    conflict-prevention stories. JSON slot membership is applied in Python so
    the rule behaves identically in SQLite tests and PostgreSQL production.
    """

    if slot not in OPERATING_SLOTS:
        raise ValueError("Unsupported operating slot.")
    candidates = session.scalars(
        select(VenueOperationalBlock)
        .where(
            VenueOperationalBlock.venue_id == venue_id,
            VenueOperationalBlock.start_date <= day,
            VenueOperationalBlock.end_date >= day,
            VenueOperationalBlock.removed_at.is_(None),
        )
        .order_by(VenueOperationalBlock.id)
    )
    return next((block for block in candidates if slot in block.slots), None)


def register_venue_operational_block_routes(app: Flask) -> None:
    @app.post("/api/venues/<int:venue_id>/operational-blocks")
    @require_roles(Role.VENUE_STAFF)
    def create_operational_block(venue_id: int):
        attributes = _block_attributes(_request_json())
        with Session(app.extensions["engine"]) as session:
            venue = _find_venue(session, venue_id)
            if unsupported := set(attributes["slots"]) - set(venue.operating_slots):
                abort(400, f"Venue does not support operating slot: {sorted(unsupported)[0]}.")
            block, affected_booking_count = record_operational_block(
                session,
                venue_id=venue_id,
                attributes=attributes,
                created_by_account_id=g.user_id,
            )
            session.commit()
            session.refresh(block)
            return (
                jsonify(
                    operational_block=_serialize_block(block),
                    affected_booking_count=affected_booking_count,
                ),
                201,
            )

    @app.get("/api/venues/<int:venue_id>/operational-blocks")
    @require_roles(Role.VENUE_STAFF)
    def list_operational_blocks(venue_id: int):
        with Session(app.extensions["engine"]) as session:
            _find_venue(session, venue_id)
            blocks = session.scalars(
                select(VenueOperationalBlock)
                .where(
                    VenueOperationalBlock.venue_id == venue_id,
                    VenueOperationalBlock.removed_at.is_(None),
                )
                .order_by(VenueOperationalBlock.start_date, VenueOperationalBlock.id)
            ).all()
            return jsonify(operational_blocks=[_serialize_block(block) for block in blocks])

    @app.delete("/api/venues/<int:venue_id>/operational-blocks/<int:block_id>")
    @require_roles(Role.VENUE_STAFF)
    def remove_operational_block(venue_id: int, block_id: int):
        with Session(app.extensions["engine"]) as session:
            block = session.scalar(
                select(VenueOperationalBlock).where(
                    VenueOperationalBlock.id == block_id,
                    VenueOperationalBlock.venue_id == venue_id,
                    VenueOperationalBlock.removed_at.is_(None),
                )
            )
            if block is None:
                abort(404, "Active operational block not found.")
            block.removed_by_account_id = g.user_id
            block.removed_at = datetime.now(timezone.utc)
            session.commit()
            session.refresh(block)
            return jsonify(operational_block=_serialize_block(block))


def record_operational_block(
    session: Session,
    *,
    venue_id: int,
    attributes: dict[str, Any],
    created_by_account_id: str,
    created_at: datetime | None = None,
) -> tuple[VenueOperationalBlock, int]:
    """Create a block and atomically mark overlapping active bookings."""

    marked_at = created_at or datetime.now(timezone.utc)
    lock_venue_slots(
        session,
        venue_id,
        (
            (day, slot)
            for day in _inclusive_dates(attributes["start_date"], attributes["end_date"])
            for slot in attributes["slots"]
        ),
    )
    block = VenueOperationalBlock(
        venue_id=venue_id,
        created_by_account_id=created_by_account_id,
        created_at=marked_at,
        **attributes,
    )
    session.add(block)
    session.flush()
    affected_booking_count = _mark_overlapping_bookings_for_review(
        session,
        block,
        marked_by_account_id=created_by_account_id,
        marked_at=marked_at,
    )
    return block, affected_booking_count


def _inclusive_dates(start_date: date, end_date: date):
    day = start_date
    while day <= end_date:
        yield day
        day += timedelta(days=1)


def _request_json() -> dict[str, Any]:
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        abort(400, "A JSON object is required.")
    return data


def _mark_overlapping_bookings_for_review(
    session: Session,
    block: VenueOperationalBlock,
    *,
    marked_by_account_id: str,
    marked_at: datetime,
) -> int:
    """Persist a review marker without changing the affected booking itself."""

    bookings = session.scalars(
        select(VenueBooking)
        .join(VenueBookingOccupancy)
        .where(
            VenueBooking.venue_id == block.venue_id,
            VenueBooking.status.in_(ACTIVE_BOOKING_STATUSES),
            VenueBookingOccupancy.day >= block.start_date,
            VenueBookingOccupancy.day <= block.end_date,
            VenueBookingOccupancy.slot.in_(block.slots),
        )
        .distinct()
        .order_by(VenueBooking.id)
    ).all()
    for booking in bookings:
        booking.requires_review = True
        booking.review_trigger_block_id = block.id
        booking.review_marked_at = marked_at
        booking.review_marked_by_account_id = marked_by_account_id
    session.flush()
    return len(bookings)


def _block_attributes(data: dict[str, Any]) -> dict[str, Any]:
    unexpected = set(data) - {"start_date", "end_date", "slots", "reason"}
    if unexpected:
        abort(400, f"Unexpected operational-block field: {sorted(unexpected)[0]}.")
    start_date = _iso_date(data.get("start_date"), "Start date")
    end_date = _iso_date(data.get("end_date", data.get("start_date")), "End date")
    if end_date < start_date:
        abort(400, "End date must not be before start date.")
    slots = data.get("slots")
    if not isinstance(slots, list) or not slots:
        abort(400, "Select at least one operating slot.")
    if any(not isinstance(slot, str) or slot not in OPERATING_SLOTS for slot in slots):
        abort(400, "Operational blocks may use only supported operating slots.")
    if len(slots) != len(set(slots)):
        abort(400, "Operating slots must not contain duplicates.")
    reason = data.get("reason")
    if not isinstance(reason, str) or not reason.strip():
        abort(400, "Reason is required.")
    return {
        "start_date": start_date,
        "end_date": end_date,
        "slots": list(slots),
        "reason": reason.strip(),
    }


def _iso_date(value: Any, label: str) -> date:
    if not isinstance(value, str):
        abort(400, f"{label} must be an ISO date.")
    try:
        return date.fromisoformat(value)
    except ValueError:
        abort(400, f"{label} must be an ISO date.")


def _find_venue(session: Session, venue_id: int) -> Venue:
    venue = session.get(Venue, venue_id)
    if venue is None:
        abort(404, "Venue not found.")
    return venue


def _serialize_block(block: VenueOperationalBlock) -> dict[str, Any]:
    return {
        "id": block.id,
        "venue_id": block.venue_id,
        "start_date": block.start_date.isoformat(),
        "end_date": block.end_date.isoformat(),
        "slots": block.slots,
        "reason": block.reason,
        "created_by_account_id": block.created_by_account_id,
        "created_at": _iso_datetime(block.created_at),
        "removed_by_account_id": block.removed_by_account_id,
        "removed_at": _iso_datetime(block.removed_at) if block.removed_at else None,
    }


def _iso_datetime(value: datetime) -> str:
    """Return an explicit UTC offset even when SQLite drops timezone metadata."""

    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()
