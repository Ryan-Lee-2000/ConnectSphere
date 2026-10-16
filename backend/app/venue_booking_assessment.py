"""Reassess active venue commitments after exact timing configuration changes (SPL-130)."""

from datetime import datetime, timezone
from typing import Any

from flask import Flask, abort, g, jsonify
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.authorization import require_roles
from app.event_requests import SINGAPORE
from app.models import (
    ACTIVE_BOOKING_STATUSES,
    Account,
    EventCoordinatorAssignment,
    EventRequest,
    Role,
    Venue,
    VenueBooking,
    VenueBookingReviewFinding,
    VenueOperationalBlock,
)
from app.venue_timing import Interval, legacy_slot_interval, opening_covers

TIMING_REASON_TYPES = {
    "overlap",
    "outside_operating_hours",
    "unresolved_historical_timing",
}


def register_venue_booking_assessment_routes(app: Flask) -> None:
    @app.get("/api/venue-bookings/timing-reviews")
    @require_roles(Role.VENUE_STAFF)
    def list_timing_reviews():
        with Session(app.extensions["engine"]) as session:
            bookings = session.scalars(
                select(VenueBooking)
                .where(
                    VenueBooking.status.in_(ACTIVE_BOOKING_STATUSES),
                    VenueBooking.review_findings.any(
                        VenueBookingReviewFinding.resolved_at.is_(None)
                    ),
                )
                .order_by(VenueBooking.review_marked_at, VenueBooking.id)
            ).all()
            return jsonify(
                reviews=[serialize_affected_booking(session, booking) for booking in bookings],
                count=len(bookings),
            )

    @app.post("/api/venue-bookings/<int:booking_id>/timing-review")
    @require_roles(Role.VENUE_STAFF)
    def resolve_timing_review(booking_id: int):
        with Session(app.extensions["engine"]) as session:
            from app.exact_venue_bookings import lock_booking

            booking = lock_booking(session, booking_id)
            if booking is None or booking.status not in ACTIVE_BOOKING_STATUSES:
                abort(404, "Active venue booking not found.")
            venue = session.get(Venue, booking.venue_id)
            event = session.get(EventRequest, booking.event_request_id)
            current, timing = _current_occupancy(venue, event)
            if current is None or timing is None:
                abort(
                    409,
                    "Supply valid exact event times and venue timing before clearing review.",
                )

            current_reasons = _reasons_for_booking(
                session,
                venue,
                booking,
                event,
                current,
                {booking.id: current},
                include_peer_intervals=True,
            )
            blocking = [reason for reason in current_reasons if reason[1] in TIMING_REASON_TYPES]
            if blocking:
                abort(409, "Current timing checks still fail: " + "; ".join(r[2] for r in blocking))

            assessed_at = datetime.now(timezone.utc)
            # Explicit review can convert a legacy commitment only from trusted event and venue
            # records. No client-supplied identity or interval is accepted.
            booking.exact_timing = timing
            from app.exact_venue_bookings import requirements

            booking.reviewed_requirements = requirements(event)
            findings = session.scalars(
                select(VenueBookingReviewFinding).where(
                    VenueBookingReviewFinding.booking_id == booking.id,
                    VenueBookingReviewFinding.reason_type.in_(TIMING_REASON_TYPES),
                    VenueBookingReviewFinding.resolved_at.is_(None),
                )
            ).all()
            for finding in findings:
                finding.resolved_at = assessed_at
                finding.resolved_by_account_id = g.user_id
                finding.last_assessed_at = assessed_at
            booking.requires_review = _has_other_active_findings(session, booking.id, findings)
            session.commit()
            return jsonify(review=serialize_review(session, booking))


def assess_venue_bookings(
    session: Session,
    venue: Venue,
    *,
    assessed_by_account_id: str | None,
    assessed_at: datetime | None = None,
) -> int:
    """Persist every current problem without silently resolving an older reason.

    The caller holds the venue row with ``FOR UPDATE``. Exact booking creation takes a conflicting
    key-share lock, so updated rules, reassessment and protection of new allocations commit as one
    transaction.
    """

    when = assessed_at or datetime.now(timezone.utc)
    candidates = session.scalars(
        select(VenueBooking)
        .where(
            VenueBooking.venue_id == venue.id,
            VenueBooking.status.in_(ACTIVE_BOOKING_STATUSES),
        )
        .options(selectinload(VenueBooking.occupancy))
        .order_by(VenueBooking.id)
        .with_for_update()
    ).all()
    rows: list[tuple[VenueBooking, EventRequest]] = []
    current_intervals: dict[int, Interval] = {}
    for booking in candidates:
        event = session.get(EventRequest, booking.event_request_id)
        current, _ = _current_occupancy(venue, event)
        if current is not None:
            current_intervals[booking.id] = current
        if _has_not_ended(booking, event, when):
            rows.append((booking, event))

    affected = 0
    for booking, event in rows:
        current = current_intervals.get(booking.id)
        reasons = _reasons_for_booking(
            session,
            venue,
            booking,
            event,
            current,
            current_intervals,
            include_peer_intervals=False,
        )
        if not reasons:
            continue
        affected += 1
        original = _original_occupancy(booking)
        current_json = current.serialize() if current else None
        for key, reason_type, detail in reasons:
            existing = session.scalar(
                select(VenueBookingReviewFinding).where(
                    VenueBookingReviewFinding.booking_id == booking.id,
                    VenueBookingReviewFinding.finding_key == key,
                )
            )
            if existing is None:
                existing = VenueBookingReviewFinding(
                    booking_id=booking.id,
                    finding_key=key,
                    reason_type=reason_type,
                    detail=detail,
                    original_occupancy=original,
                    current_occupancy=current_json,
                    venue_timing_revision=venue.timing_revision,
                    first_assessed_at=when,
                    last_assessed_at=when,
                )
                session.add(existing)
            else:
                existing.detail = detail
                existing.current_occupancy = current_json
                existing.venue_timing_revision = venue.timing_revision
                existing.last_assessed_at = when
                existing.resolved_at = None
                existing.resolved_by_account_id = None
        booking.requires_review = True
        booking.review_marked_at = when
        booking.review_marked_by_account_id = assessed_by_account_id
    session.flush()
    return affected


def count_pending_reviews(session: Session, venue_id: int) -> int:
    """Count active venue commitments that still have at least one unresolved finding."""

    return (
        session.scalar(
            select(func.count(VenueBooking.id)).where(
                VenueBooking.venue_id == venue_id,
                VenueBooking.status.in_(ACTIVE_BOOKING_STATUSES),
                VenueBooking.review_findings.any(VenueBookingReviewFinding.resolved_at.is_(None)),
            )
        )
        or 0
    )


def resolve_operational_findings(
    session: Session,
    block: VenueOperationalBlock,
    *,
    resolved_by_account_id: str,
    resolved_at: datetime,
) -> int:
    """Resolve one removed block's findings and recompute each affected booking marker."""

    key = f"operational-block:{block.id}"
    findings = session.scalars(
        select(VenueBookingReviewFinding)
        .join(VenueBooking)
        .where(
            VenueBooking.venue_id == block.venue_id,
            VenueBookingReviewFinding.finding_key == key,
            VenueBookingReviewFinding.resolved_at.is_(None),
        )
        .with_for_update()
    ).all()
    booking_ids = {finding.booking_id for finding in findings}
    # Legacy SPL-89 rows identify only the triggering block. Include them so a database upgraded
    # from that workflow cannot retain a stale review marker if no normalized row was present.
    booking_ids.update(
        session.scalars(
            select(VenueBooking.id).where(
                VenueBooking.venue_id == block.venue_id,
                VenueBooking.review_trigger_block_id == block.id,
            )
        )
    )
    for finding in findings:
        finding.resolved_at = resolved_at
        finding.resolved_by_account_id = resolved_by_account_id
        finding.last_assessed_at = resolved_at
    session.flush()

    if not booking_ids:
        return 0
    bookings = session.scalars(
        select(VenueBooking).where(VenueBooking.id.in_(booking_ids)).with_for_update()
    ).all()
    for booking in bookings:
        remaining = active_findings(session, booking.id)
        booking.requires_review = bool(remaining)
        if booking.review_trigger_block_id == block.id:
            another_block = next(
                (finding for finding in remaining if finding.reason_type == "operational_block"),
                None,
            )
            booking.review_trigger_block_id = (
                int(another_block.finding_key.rsplit(":", 1)[1]) if another_block else None
            )
    session.flush()
    return len(findings)


def record_operational_finding(
    session: Session,
    booking: VenueBooking,
    block: VenueOperationalBlock,
    *,
    assessed_at: datetime,
) -> None:
    """Add a block-specific reason without overwriting another finding."""

    key = f"operational-block:{block.id}"
    finding = session.scalar(
        select(VenueBookingReviewFinding).where(
            VenueBookingReviewFinding.booking_id == booking.id,
            VenueBookingReviewFinding.finding_key == key,
        )
    )
    original = _original_occupancy(booking)
    detail = f"Operational block: {block.reason}"
    if finding is None:
        session.add(
            VenueBookingReviewFinding(
                booking_id=booking.id,
                finding_key=key,
                reason_type="operational_block",
                detail=detail,
                original_occupancy=original,
                current_occupancy=original if "start" in original else None,
                venue_timing_revision=booking.venue.timing_revision,
                first_assessed_at=assessed_at,
                last_assessed_at=assessed_at,
            )
        )
    else:
        finding.detail = detail
        finding.last_assessed_at = assessed_at
        finding.resolved_at = None
        finding.resolved_by_account_id = None


def active_findings(session: Session, booking_id: int) -> list[VenueBookingReviewFinding]:
    return session.scalars(
        select(VenueBookingReviewFinding)
        .where(
            VenueBookingReviewFinding.booking_id == booking_id,
            VenueBookingReviewFinding.resolved_at.is_(None),
        )
        .order_by(VenueBookingReviewFinding.first_assessed_at, VenueBookingReviewFinding.id)
    ).all()


def serialize_review(session: Session, booking: VenueBooking) -> dict[str, Any]:
    findings = active_findings(session, booking.id)
    return {
        "requires_review": booking.requires_review or bool(findings),
        "findings": [_serialize_finding(finding) for finding in findings],
    }


def serialize_affected_booking(session: Session, booking: VenueBooking) -> dict[str, Any]:
    event = session.get(EventRequest, booking.event_request_id)
    venue = session.get(Venue, booking.venue_id)
    assignment = session.scalar(
        select(EventCoordinatorAssignment).where(
            EventCoordinatorAssignment.event_request_id == event.id
        )
    )
    coordinator = (
        session.get(Account, assignment.coordinator_account_id) if assignment is not None else None
    )
    return {
        "booking_id": booking.id,
        "status": booking.status,
        "event": {
            "id": event.id,
            "name": event.name,
            "advertised_interval": _advertised_interval(event),
        },
        "venue": {"id": venue.id, "name": venue.name},
        "coordinator": (
            {"id": coordinator.id, "name": coordinator.display_name} if coordinator else None
        ),
        "findings": [
            _serialize_finding(finding) for finding in active_findings(session, booking.id)
        ],
    }


def _advertised_interval(event: EventRequest) -> dict[str, str] | None:
    try:
        from app.exact_venue_bookings import saved_event_interval

        return saved_event_interval(event).serialize()
    except ValueError:
        return None


def _serialize_finding(finding: VenueBookingReviewFinding) -> dict[str, Any]:
    return {
        "id": finding.id,
        "reason_type": finding.reason_type,
        "detail": finding.detail,
        "original_occupancy": finding.original_occupancy,
        "current_occupancy": finding.current_occupancy,
        "venue_timing_revision": finding.venue_timing_revision,
        "first_assessed_at": _timestamp(finding.first_assessed_at),
        "last_assessed_at": _timestamp(finding.last_assessed_at),
    }


def _reasons_for_booking(
    session: Session,
    venue: Venue,
    booking: VenueBooking,
    event: EventRequest,
    current: Interval | None,
    current_intervals: dict[int, Interval],
    *,
    include_peer_intervals: bool,
) -> list[tuple[str, str, str]]:
    reasons: list[tuple[str, str, str]] = []
    if booking.exact_timing is None or current is None:
        reasons.append(
            (
                "historical-timing",
                "unresolved_historical_timing",
                "Exact occupied times must be supplied before this historical booking "
                "can be cleared.",
            )
        )
    if current is None:
        return reasons
    if venue.operating_intervals is None or not opening_covers(current, venue.operating_intervals):
        reasons.append(
            (
                "outside-operating-hours",
                "outside_operating_hours",
                "The revised occupied interval is outside the venue's operating hours.",
            )
        )
    blocks = session.scalars(
        select(VenueOperationalBlock).where(
            VenueOperationalBlock.venue_id == venue.id,
            VenueOperationalBlock.removed_at.is_(None),
            VenueOperationalBlock.start_date <= current.end.date(),
            VenueOperationalBlock.end_date >= current.start.date(),
        )
    ).all()
    from app.venue_operational_blocks import block_overlaps

    for block in blocks:
        if block_overlaps(block, current):
            reasons.append(
                (
                    f"operational-block:{block.id}",
                    "operational_block",
                    f"Operational block: {block.reason}",
                )
            )
    peers = session.scalars(
        select(VenueBooking)
        .where(
            VenueBooking.venue_id == venue.id,
            VenueBooking.status.in_(ACTIVE_BOOKING_STATUSES),
            VenueBooking.id != booking.id,
        )
        .options(selectinload(VenueBooking.occupancy))
        .order_by(VenueBooking.id)
    ).all()
    for peer in peers:
        intervals: list[Interval] = []
        peer_event = None
        if peer.id in current_intervals:
            intervals.append(current_intervals[peer.id])
        elif include_peer_intervals:
            peer_event = session.get(EventRequest, peer.event_request_id)
            peer_current, _ = _current_occupancy(venue, peer_event)
            if peer_current is not None:
                intervals.append(peer_current)
            else:
                intervals.extend(_protected_intervals(peer))
        elif peer.exact_timing:
            intervals.extend(_protected_intervals(peer))
        if any(current.overlaps(interval) for interval in intervals):
            peer_event = peer_event or session.get(EventRequest, peer.event_request_id)
            reasons.append(
                (
                    f"overlap:{peer.id}",
                    "overlap",
                    f"The revised occupied interval overlaps {peer_event.name} "
                    f"(booking {peer.id}).",
                )
            )
    return reasons


def _current_occupancy(venue: Venue, event: EventRequest) -> tuple[Interval | None, dict | None]:
    if (
        venue.setup_minutes is None
        or venue.turnaround_minutes is None
        or venue.operating_intervals is None
    ):
        return None, None
    try:
        from app.exact_venue_availability import timing_for
        from app.exact_venue_bookings import saved_event_interval

        event_interval = saved_event_interval(event)
        return timing_for(venue, event_interval)
    except ValueError:
        return None, None


def _original_occupancy(booking: VenueBooking) -> dict[str, Any]:
    if booking.exact_timing:
        occupied = booking.exact_timing.get("occupied")
        if isinstance(occupied, dict) and {"start", "end"}.issubset(occupied):
            return {"start": occupied["start"], "end": occupied["end"]}
    return {
        "legacy_slots": [
            {"date": claim.day.isoformat(), "slot": claim.slot, "kind": claim.kind}
            for claim in booking.occupancy
        ]
    }


def _protected_intervals(booking: VenueBooking) -> list[Interval]:
    intervals: list[Interval] = []
    if booking.exact_timing:
        try:
            from app.exact_venue_bookings import interval_from_json

            intervals.append(interval_from_json(booking.exact_timing["occupied"]))
        except (KeyError, TypeError, ValueError):
            pass
    for claim in booking.occupancy:
        try:
            intervals.append(legacy_slot_interval(claim.day, claim.slot))
        except ValueError:
            pass
    return intervals


def _has_not_ended(booking: VenueBooking, event: EventRequest, when: datetime) -> bool:
    instant = when if when.tzinfo else when.replace(tzinfo=timezone.utc)
    intervals = _protected_intervals(booking)
    try:
        from app.exact_venue_bookings import saved_event_interval

        intervals.append(saved_event_interval(event))
    except ValueError:
        pass
    return not intervals or any(interval.end > instant for interval in intervals)


def _has_other_active_findings(
    session: Session,
    booking_id: int,
    resolving: list[VenueBookingReviewFinding],
) -> bool:
    resolving_ids = {finding.id for finding in resolving}
    return any(
        finding.id not in resolving_ids
        for finding in session.scalars(
            select(VenueBookingReviewFinding).where(
                VenueBookingReviewFinding.booking_id == booking_id,
                VenueBookingReviewFinding.resolved_at.is_(None),
            )
        )
    )


def _timestamp(value: datetime) -> str:
    aware = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return aware.astimezone(SINGAPORE).isoformat()
