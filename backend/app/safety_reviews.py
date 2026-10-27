"""Operational safety review and the only server-authorised path into Preparation (SPL-135)."""
# ruff: noqa: E501, E701, E702

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any

from flask import Flask, abort, g, jsonify, request
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.authorization import require_roles
from app.equipment_reservation_state import remaining_quantity
from app.event_confirmation import (
    confirmation_readiness_for,
    derive_confirmation_readiness,
    lock_for_confirmation,
)
from app.event_requests import SINGAPORE
from app.event_review import InvalidStatusTransition, transition_event_status
from app.models import (
    EquipmentRequirement,
    EventCoordinatorAssignment,
    EventRequest,
    Role,
    SafetyReview,
    Venue,
    VenueBooking,
)
from app.notifications import add_safety_decision_notice

MAX_REASON_LENGTH = 2000
PLAN_FIELDS = ("emergency_access", "equipment_placement", "crowd_movement", "venue_restrictions")


def register_safety_review_routes(app: Flask) -> None:
    @app.get("/api/safety-reviews")
    @require_roles(Role.SAFETY_OFFICER)
    def safety_review_queue():
        with Session(app.extensions["engine"]) as session:
            candidates = session.scalars(
                select(SafetyReview)
                .where(SafetyReview.status == "submitted")
                .options(
                    joinedload(SafetyReview.event_request)
                    .selectinload(EventRequest.venue_bookings)
                    .joinedload(VenueBooking.venue),
                    joinedload(SafetyReview.event_request)
                    .selectinload(EventRequest.venue_bookings)
                    .joinedload(VenueBooking.venue)
                    .selectinload(Venue.layouts),
                    joinedload(SafetyReview.event_request)
                    .selectinload(EventRequest.equipment_requirements)
                    .joinedload(EquipmentRequirement.catalogue_type),
                    joinedload(SafetyReview.event_request)
                    .selectinload(EventRequest.equipment_requirements)
                    .selectinload(EquipmentRequirement.reservations),
                )
                .order_by(SafetyReview.submitted_at)
            ).all()
            # A coordinator may resubmit after an arrangement changes. Retain the evidence, but
            # show Safety only the newest review for each event so an obsolete submission cannot
            # be decided by mistake.
            newest = {review.event_request_id: review.id for review in candidates}
            rows = [review for review in candidates if newest[review.event_request_id] == review.id]
            return jsonify(reviews=[_queue_item(row) for row in rows])

    @app.get("/api/event-requests/<int:event_request_id>/safety-review")
    @require_roles(Role.EVENT_COORDINATOR, Role.EVENT_OPERATIONS_MANAGER, Role.SAFETY_OFFICER)
    def read_safety_review(event_request_id: int):
        with Session(app.extensions["engine"]) as session:
            event = _visible_event(session, event_request_id)
            review = _latest_review(session, event.id)
            # SPL-136 AC4: `review` is the convenient latest-item alias; `reviews` deliberately
            # includes that item as the complete newest-first accountable history.  The UI omits
            # reviews[0] from its "previous" list rather than asking API clients to reconstruct it.
            reviews = _review_history(session, event.id)
            return jsonify(
                event=_event_context(event),
                review=_serialize_review(review, event),
                reviews=[_serialize_review(item, event) for item in reviews],
            )

    @app.post("/api/event-requests/<int:event_request_id>/safety-review")
    @require_roles(Role.EVENT_COORDINATOR)
    def submit_safety_review(event_request_id: int):
        plan = _plan_from_request()
        with Session(app.extensions["engine"]) as session:
            event = _assigned_event(session, event_request_id)
            if event.status != "confirmed":
                abort(409, "Safety information can be submitted only for a confirmed event.")
            readiness = confirmation_readiness_for(event)
            if not readiness["ready"]:
                abort(409, "Resolve the current venue and essential technical arrangements first.")
            latest = _latest_review(session, event.id)
            if (
                latest is not None
                and latest.status == "submitted"
                and latest.arrangement_fingerprint == _fingerprint(event)
            ):
                abort(409, "This arrangement already has a safety review awaiting a decision.")
            if (
                latest is not None
                and latest.status == "approved"
                and latest.arrangement_fingerprint == _fingerprint(event)
                and latest.plan == plan
            ):
                abort(409, "The current safety plan is already approved.")
            now = datetime.now(SINGAPORE)
            review = SafetyReview(
                event_request_id=event.id,
                plan=plan,
                arrangement_fingerprint=_fingerprint(event),
                status="submitted",
                submitted_by_account_id=g.user_id,
                submitted_at=now,
            )
            session.add(review)
            session.commit()
            session.refresh(review)
            return jsonify(
                review=_serialize_review(review, event), message="Safety review submitted."
            )

    @app.post("/api/safety-reviews/<int:review_id>/decision")
    @require_roles(Role.SAFETY_OFFICER)
    def decide_safety_review(review_id: int):
        body = request.get_json(silent=True) or {}
        decision = body.get("decision")
        if decision not in {"approved", "changes_requested", "rejected"}:
            abort(400, "Choose Approve, Request changes, or Reject.")
        reason = _reason(body.get("reason"), required=decision != "approved")
        with Session(app.extensions["engine"]) as session:
            review = session.scalar(
                select(SafetyReview).where(SafetyReview.id == review_id).with_for_update()
            )
            if review is None:
                abort(404, "Safety review not found.")
            event = session.scalar(
                select(EventRequest)
                .where(EventRequest.id == review.event_request_id)
                .with_for_update()
            )
            if review.status != "submitted" or event.status != "confirmed":
                abort(409, "This safety review is no longer awaiting a decision.")
            if review.arrangement_fingerprint != _fingerprint(event):
                abort(
                    409,
                    "The arrangements changed. The coordinator must submit a new safety review.",
                )
            now = datetime.now(SINGAPORE)
            review.status, review.decision_reason = decision, reason
            review.decided_by_account_id, review.decided_at = g.user_id, now
            if decision != "approved":
                try:
                    transition_event_status(
                        session,
                        event_request_id=event.id,
                        action="safety_rework",
                        actor_account_id=g.user_id,
                        changed_at=now,
                    )
                except InvalidStatusTransition:
                    session.rollback()
                    abort(409, "This event can no longer return to Planning.")
            add_safety_decision_notice(session, event, review=review)
            session.commit()
            session.refresh(event)
            session.refresh(review)
            return jsonify(
                event={"id": event.id, "status": event.status},
                review=_serialize_review(review, event),
            )

    @app.post("/api/event-requests/<int:event_request_id>/begin-preparation")
    @require_roles(Role.EVENT_COORDINATOR)
    def begin_preparation(event_request_id: int):
        with Session(app.extensions["engine"]) as session:
            # Reuse the confirmation gate's locking order. A Safety approval is not a permanent
            # bypass: an approved venue can later be flagged for review, or an essential line can
            # become unresolved while the event remains Confirmed.
            event, bookings, lines = lock_for_confirmation(session, event_request_id, g.user_id)
            review = _latest_review(session, event.id, lock=True)
            if event.status != "confirmed" or review is None or review.status != "approved":
                abort(409, "Safety approval is required before Preparation can begin.")
            readiness = derive_confirmation_readiness(session, bookings, lines)
            if not readiness["ready"]:
                session.rollback()
                return jsonify(
                    error="Resolve the current venue and essential technical arrangements first.",
                    blockers=readiness["blockers"],
                ), 409
            if review.arrangement_fingerprint != _fingerprint(event):
                abort(409, "The approved safety review is no longer current. Submit a new review.")
            try:
                transition_event_status(
                    session,
                    event_request_id=event.id,
                    action="begin_preparation",
                    actor_account_id=g.user_id,
                    changed_at=datetime.now(SINGAPORE),
                )
            except InvalidStatusTransition:
                session.rollback()
                abort(409, "Preparation can begin only from Confirmed.")
            session.commit()
            return jsonify(
                event={"id": event.id, "status": "preparing"}, message="Preparation has begun."
            )


def _assigned_event(session: Session, event_id: int, lock: bool = False) -> EventRequest:
    query = (
        select(EventRequest)
        .join(EventCoordinatorAssignment)
        .where(
            EventRequest.id == event_id,
            EventCoordinatorAssignment.coordinator_account_id == g.user_id,
        )
    )
    if lock:
        query = query.with_for_update()
    event = session.scalar(query)
    if event is None:
        abort(404, "Assigned event not found.")
    return event


def _visible_event(session: Session, event_id: int) -> EventRequest:
    if Role.SAFETY_OFFICER.value in g.account_roles:
        event = session.get(EventRequest, event_id)
    elif Role.EVENT_COORDINATOR.value in g.account_roles:
        event = _assigned_event(session, event_id)
    else:
        event = session.get(EventRequest, event_id)
    if event is None:
        abort(404, "Event not found.")
    return event


def _plan_from_request() -> dict[str, dict[str, str | None]]:
    body = request.get_json(silent=True) or {}
    raw = body.get("plan")
    if not isinstance(raw, dict):
        abort(400, "Provide all safety-plan details.")
    plan = {}
    for field in PLAN_FIELDS:
        item = raw.get(field)
        if not isinstance(item, dict):
            abort(400, "Provide all safety-plan details.")
        value = str(item.get("value") or "").strip()
        not_applicable_reason = str(item.get("not_applicable_reason") or "").strip()
        if not value and not not_applicable_reason:
            abort(400, "Explain each safety-plan item or record why it is not applicable.")
        if len(value) > MAX_REASON_LENGTH or len(not_applicable_reason) > MAX_REASON_LENGTH:
            abort(400, "Safety-plan details are too long.")
        plan[field] = {
            "value": value or None,
            "not_applicable_reason": not_applicable_reason or None,
        }
    return plan


def _reason(value: Any, *, required: bool) -> str | None:
    reason = str(value or "").strip()
    if required and not reason:
        abort(400, "A reason is required for this safety decision.")
    if len(reason) > MAX_REASON_LENGTH:
        abort(400, "The decision reason is too long.")
    return reason or None


def _latest_review(session: Session, event_id: int, lock: bool = False) -> SafetyReview | None:
    query = (
        select(SafetyReview)
        .where(SafetyReview.event_request_id == event_id)
        .order_by(SafetyReview.id.desc())
        .limit(1)
    )
    if lock:
        query = query.with_for_update()
    return session.scalar(query)


def _review_history(session: Session, event_id: int) -> list[SafetyReview]:
    """Return the newest-first review evidence without treating old versions as actionable."""

    return session.scalars(
        select(SafetyReview)
        .where(SafetyReview.event_request_id == event_id)
        .order_by(SafetyReview.id.desc())
    ).all()


def _fingerprint(event: EventRequest) -> str:
    # Hash every arrangement fact the Safety Officer is shown *and* the durable schedule and
    # allocation identities it approved.  The UI context intentionally stays readable, while this
    # server-side snapshot also prevents a re-confirmation from reviving approval for a changed
    # date/time or a replacement booking that happens to look the same in the interface.
    context = _event_context(event)
    # Keep the reviewer-facing context readable and complete, but hash only facts that affect
    # the safe arrangement.  Cosmetic fields such as the event name and workflow status must
    # not expire a valid approval; venue preferences must, even after other teams revalidate
    # the affected booking or equipment line.
    safety_context = {
        "expected_attendance": context["expected_attendance"],
        "accessibility_needs": context["accessibility_needs"],
        "preferred_room_layout": event.preferred_room_layout,
        "required_facilities": sorted(event.required_facilities or [], key=str.casefold),
        "location_preference": event.location_preference,
        "venues": context["venues"],
        "equipment": context["equipment"],
    }
    payload = {
        "schedule": {
            "event_id": event.id,
            "proposed_date": event.proposed_date,
            "start_time": event.start_time,
            "end_time": event.end_time,
        },
        "safety_context": safety_context,
        "bookings": [
            {
                "id": booking.id,
                "venue_id": booking.venue_id,
                "status": booking.status,
                "requires_review": booking.requires_review,
                "booking_date": booking.booking_date,
                "event_slots": booking.event_slots,
                "setup_date": booking.setup_date,
                "setup_slot": booking.setup_slot,
                "turnaround_date": booking.turnaround_date,
                "turnaround_slot": booking.turnaround_slot,
                "exact_timing": booking.exact_timing,
            }
            for booking in sorted(event.venue_bookings, key=lambda item: item.id)
            if booking.status == "approved"
        ],
        "equipment_allocations": [
            {
                "id": line.id,
                "equipment_type_id": line.equipment_type_id,
                "quantity": line.quantity,
                "status": line.status,
                "required_start_date": line.required_start_date,
                "required_end_date": line.required_end_date,
                "reservations": [
                    {
                        "id": reservation.id,
                        "equipment_type_id": reservation.equipment_type_id,
                        "quantity": reservation.quantity,
                        "commitment_start_date": reservation.commitment_start_date,
                        "commitment_end_date": reservation.commitment_end_date,
                    }
                    for reservation in sorted(line.reservations, key=lambda item: item.id)
                ],
            }
            for line in sorted(event.equipment_requirements, key=lambda item: item.id)
            if line.status != "removed"
        ],
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


def _event_context(event: EventRequest) -> dict[str, Any]:
    venues = []
    for booking in sorted(event.venue_bookings, key=lambda item: item.id):
        if booking.status != "approved":
            continue
        capacity = next(
            (
                layout.capacity
                for layout in booking.venue.layouts
                if layout.layout.casefold() == (booking.layout or "").casefold()
            ),
            None,
        )
        venues.append(
            {
                "name": booking.venue.name,
                "layout": booking.layout,
                "capacity": capacity,
                "attendance": booking.expected_attendance,
                "restrictions": event.venue_notes,
            }
        )
    equipment = [
        {
            "name": line.catalogue_type.name if line.catalogue_type else line.equipment_type,
            "required": line.quantity,
            "reserved": sum(remaining_quantity(reservation) for reservation in line.reservations),
            "essentiality": line.essentiality,
            "status": line.status,
        }
        for line in event.equipment_requirements
        if line.status != "removed"
    ]
    return {
        "id": event.id,
        "name": event.name,
        "status": event.status,
        "expected_attendance": event.expected_attendance,
        "accessibility_needs": event.accessibility_needs,
        "venues": venues,
        "equipment": equipment,
    }


def _serialize_review(review: SafetyReview | None, event: EventRequest) -> dict[str, Any] | None:
    if review is None:
        return None
    return {
        "id": review.id,
        "status": review.status,
        "plan": review.plan,
        "reason": review.decision_reason,
        "submitted_at": review.submitted_at.isoformat(),
        "decided_at": review.decided_at.isoformat() if review.decided_at else None,
        "decided_by": (
            {"id": review.decider.id, "name": review.decider.display_name}
            if review.decider
            else None
        ),
        "current": review.arrangement_fingerprint == _fingerprint(event),
    }


def _queue_item(review: SafetyReview) -> dict[str, Any]:
    event = review.event_request
    return {
        "id": review.id,
        # The decision screen consumes this exact response, so do not reduce it to a card summary.
        # Safety Officers need the same protected venue and technical evidence before deciding.
        "event": _event_context(event),
        "plan": review.plan,
        "submitted_at": review.submitted_at.isoformat(),
    }
