"""Acceptance coverage for SPL-86 (CS-E07-S5): cancel an event and free its venues and equipment.

Each test carries the QA-SPL-86 case identifier it proves (BB = black-box, WB = white-box).
Expected values come from the Jira acceptance criteria and the client answers (Q20, Q60, Q68,
Q115, Q132), not from the implementation. Races and the migration run on PostgreSQL in
test_event_cancellation_postgres.py. Fixtures are shared with SPL-85's suite.
"""

from datetime import date, datetime, time, timedelta, timezone

import pytest
import test_event_confirmation as base
from app import event_cancellation
from app.models import (
    EquipmentRequirement,
    EquipmentReservationRelease,
    EventCoordinatorAssignment,
    EventRegistration,
    EventRequest,
    EventStatusHistory,
    Venue,
    VenueBooking,
    VenueBookingOccupancy,
    VenueBookingStatusHistory,
)
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from test_event_confirmation import (
    COORDINATOR,
    EVENT_DATE,
    LEAD,
    NOW,
    OTHER_COORDINATOR,
    add_booking,
    add_event,
    add_line,
    headers,
    reserve,
)

app = base.app
client = base.client

CANCELLABLE = (
    "submitted",
    "under_review",
    "returned_for_clarification",
    "approved",
    "planning",
    "confirmed",
    "postponed",
)
REASON = "The keynote speaker withdrew and the client called the event off."


# Helpers ------------------------------------------------------------------------------------


def cancel(client, event_id, reason=REASON, identity="coordinator", body=None):
    return client.post(
        f"/api/event-requests/{event_id}/cancel",
        json={"reason": reason} if body is None else body,
        headers=headers(identity),
    )


def count(app, model, *conditions):
    with Session(app.extensions["engine"]) as session:
        return session.scalar(select(func.count()).select_from(model).where(*conditions))


def event_row(app, event_id):
    with Session(app.extensions["engine"]) as session:
        event = session.get(EventRequest, event_id)
        return {
            "status": event.status,
            "cancelled_by": event.cancelled_by_account_id,
            "cancelled_at": event.cancelled_at,
            "reason": event.cancellation_reason,
            "history": list(
                session.scalars(
                    select(EventStatusHistory.action)
                    .where(EventStatusHistory.event_request_id == event_id)
                    .order_by(EventStatusHistory.id)
                )
            ),
        }


def bookings(app, event_id):
    with Session(app.extensions["engine"]) as session:
        return {
            booking.id: booking.status
            for booking in session.scalars(
                select(VenueBooking).where(VenueBooking.event_request_id == event_id)
            )
        }


def held(app, line_id):
    from app.equipment_reservation_state import remaining_quantity

    with Session(app.extensions["engine"]) as session:
        line = session.get(EquipmentRequirement, line_id)
        return sum(remaining_quantity(item) for item in line.reservations)


def line_status(app, line_id):
    with Session(app.extensions["engine"]) as session:
        return session.get(EquipmentRequirement, line_id).status


def everything(app, event_id):
    """The whole state cancellation may touch: event, bookings, claims, history and releases."""

    with Session(app.extensions["engine"]) as session:
        return {
            "event": event_row(app, event_id),
            "bookings": bookings(app, event_id),
            "claims": session.scalar(select(func.count()).select_from(VenueBookingOccupancy)),
            "booking_history": session.scalar(
                select(func.count()).select_from(VenueBookingStatusHistory)
            ),
            "releases": session.scalar(
                select(func.count()).select_from(EquipmentReservationRelease)
            ),
        }


def full_event(app, *, status="confirmed"):
    """An event with five bookings in every status and three kinds of equipment line."""

    event_id = add_event(app, status=status)
    ids = {
        "approved": add_booking(app, event_id, status="approved", venue_id=1),
        "requested": add_booking(app, event_id, status="requested", venue_id=2),
        "rejected": add_booking(app, event_id, status="rejected", venue_id=3),
        "withdrawn": add_booking(app, event_id, status="withdrawn", venue_id=3),
        "cancelled": add_booking(app, event_id, status="cancelled", venue_id=3),
    }
    reserved = add_line(app, event_id, quantity=4)
    reserve(app, event_id, reserved, 4)
    partial = add_line(app, event_id, quantity=4, status="partially_reserved")
    reserve(app, event_id, partial, 2)
    review = add_line(
        app,
        event_id,
        quantity=3,
        status="review_required",
        essentiality="non_essential",
        review_reason="Dates changed after reservation.",
    )
    reserve(app, event_id, review, 3, released=1)
    return event_id, ids, {"reserved": reserved, "partial": partial, "review": review}


def queued_ids(client, path, identity, collection, key):
    response = client.get(path, headers=headers(identity))
    assert response.status_code == 200, response.json
    return [item[key] for item in response.json[collection]]


def set_status(app, event_id, status):
    with Session(app.extensions["engine"]) as session:
        session.get(EventRequest, event_id).status = status
        session.commit()


# AC1 - which events can be cancelled -------------------------------------------------------


# TC-SPL-86-01 (BB) AC1: the assigned coordinator cancels a Planning event with a reason
def test_tc_spl_86_01_assigned_coordinator_cancels_a_planning_event(app, client):
    event_id = add_event(app)

    response = cancel(client, event_id)

    assert response.status_code == 200, response.json
    assert response.json["event"]["status"] == "cancelled"
    assert response.json["event"]["status_label"] == "Cancelled"
    assert response.json["transition"]["action"] == "cancel"
    assert response.json["transition"]["previous_status"] == "planning"
    assert "venues and equipment are free" in response.json["message"]


# TC-SPL-86-02 (BB) AC1: every stage from assignment onwards (Q68)
@pytest.mark.parametrize("status", CANCELLABLE)
def test_tc_spl_86_02_every_cancellable_status(app, client, status):
    event_id = add_event(app, status=status)

    response = cancel(client, event_id)

    assert response.status_code == 200, response.json
    assert event_row(app, event_id)["status"] == "cancelled"
    assert event_row(app, event_id)["history"][-1] == "cancel"


# TC-SPL-86-03 (BB) AC1: a Confirmed event with arrangements is cancellable
def test_tc_spl_86_03_confirmed_event_with_arrangements(app, client):
    event_id = base.ready_event(app)
    assert base.confirm(client, event_id).status_code == 200

    response = cancel(client, event_id)

    assert response.status_code == 200, response.json
    assert response.json["transition"]["previous_status"] == "confirmed"


# TC-SPL-86-04 (BB) AC1 boundary: the reason is trimmed; 1 and 2,000 characters are accepted
@pytest.mark.parametrize("reason", ["x", "  Venue flooded.  ", "r" * 2000])
def test_tc_spl_86_04_reason_boundaries_accepted(app, client, reason):
    event_id = add_event(app)

    response = cancel(client, event_id, reason=reason)

    assert response.status_code == 200, response.json
    assert event_row(app, event_id)["reason"] == reason.strip()


# TC-SPL-86-05 (BB) AC1: no cancellation deadline (Q60), even on or after the event date
@pytest.mark.parametrize("offset_days", [0, -30])
def test_tc_spl_86_05_no_deadline(app, client, offset_days):
    event_id = add_event(app, status="confirmed")
    with Session(app.extensions["engine"]) as session:
        session.get(EventRequest, event_id).proposed_date = date.today() + timedelta(
            days=offset_days
        )
        session.commit()

    assert cancel(client, event_id).status_code == 200


# AC2 - what is refused ------------------------------------------------------------------------


# TC-SPL-86-06 (BB) AC2: final states are refused in plain words, and nothing changes
@pytest.mark.parametrize(
    ("status", "error"),
    [
        ("rejected", "This event is not approved and cannot be cancelled."),
        ("withdrawn", "This event is withdrawn and cannot be cancelled."),
        ("completed", "This event is completed and cannot be cancelled."),
    ],
)
def test_tc_spl_86_06_final_states_refused(app, client, status, error):
    event_id = add_event(app, status=status)
    before = event_row(app, event_id)

    response = cancel(client, event_id)

    assert response.status_code == 409
    assert response.json["error"] == error
    assert event_row(app, event_id) == before


# TC-SPL-86-07 (BB) AC2: a Draft has no assigned coordinator and is refused
def test_tc_spl_86_07_draft_refused(app, client):
    event_id = add_event(app, status="draft")
    with Session(app.extensions["engine"]) as session:
        session.execute(
            EventCoordinatorAssignment.__table__.delete().where(
                EventCoordinatorAssignment.event_request_id == event_id
            )
        )
        session.commit()

    response = cancel(client, event_id)

    assert response.status_code == 404
    assert event_row(app, event_id)["status"] == "draft"


# TC-SPL-86-08 (BB) AC2: a blank or malformed reason is refused and nothing changes
@pytest.mark.parametrize(
    "body",
    [
        {"reason": ""},
        {"reason": "   "},
        {"reason": None},
        {"reason": 42},
        {},
        {"reason": "Moved", "status": "cancelled"},
        {"reason": "Moved", "cancelled_by_account_id": OTHER_COORDINATOR},
        {"reason": "r" * 2001},
    ],
)
def test_tc_spl_86_08_reason_refused(app, client, body):
    event_id, _, _ = full_event(app)
    before = everything(app, event_id)

    response = cancel(client, event_id, body=body)

    assert response.status_code == 400
    assert everything(app, event_id) == before


def test_tc_spl_86_08_non_json_body_refused(app, client):
    event_id = add_event(app)

    response = client.post(
        f"/api/event-requests/{event_id}/cancel", data="reason=Moved", headers=headers()
    )

    assert response.status_code == 400
    assert event_row(app, event_id)["status"] == "planning"


# TC-SPL-86-09 (BB) AC2 security: only the assigned coordinator; the Lead is refused (Q132)
@pytest.mark.parametrize(
    ("identity", "expected"),
    [
        ("other-coordinator", 404),
        ("lead", 403),
        ("organiser", 403),
        ("venue-staff", 403),
        ("technical", 403),
        (None, 401),
    ],
)
def test_tc_spl_86_09_only_the_assigned_coordinator(app, client, identity, expected):
    event_id, _, _ = full_event(app)
    before = everything(app, event_id)

    response = cancel(client, event_id, identity=identity)

    assert response.status_code == expected
    assert everything(app, event_id) == before


# TC-SPL-86-10 (BB) AC2: unknown and out-of-range events are not found
@pytest.mark.parametrize("event_id", [999999, 2**31, 10**12])
def test_tc_spl_86_10_unknown_events(client, event_id):
    assert cancel(client, event_id).status_code == 404


# TC-SPL-86-11 (BB) AC2: after reassignment, only the new coordinator can cancel
def test_tc_spl_86_11_after_reassignment(app, client):
    event_id = add_event(app)
    with Session(app.extensions["engine"]) as session:
        assignment = session.scalar(
            select(EventCoordinatorAssignment).where(
                EventCoordinatorAssignment.event_request_id == event_id
            )
        )
        assignment.coordinator_account_id = OTHER_COORDINATOR
        session.commit()

    assert cancel(client, event_id).status_code == 404
    assert event_row(app, event_id)["status"] == "planning"
    assert cancel(client, event_id, identity="other-coordinator").status_code == 200
    assert event_row(app, event_id)["cancelled_by"] == OTHER_COORDINATOR


# AC3 - what gets released -----------------------------------------------------------------------


# TC-SPL-86-12 (BB) AC3: Requested and Approved bookings become Cancelled; the rest stay
def test_tc_spl_86_12_active_bookings_cancelled_others_unchanged(app, client):
    event_id, ids, _ = full_event(app)

    response = cancel(client, event_id)

    assert response.status_code == 200, response.json
    assert sorted(response.json["released"]["venue_bookings"]) == sorted(
        [ids["approved"], ids["requested"]]
    )
    assert bookings(app, event_id) == {
        ids["approved"]: "cancelled",
        ids["requested"]: "cancelled",
        ids["rejected"]: "rejected",
        ids["withdrawn"]: "withdrawn",
        ids["cancelled"]: "cancelled",
    }


# TC-SPL-86-13 (BB) AC3: each released booking records why, by whom and when
def test_tc_spl_86_13_booking_history_records_the_cancellation(app, client):
    event_id, ids, _ = full_event(app)

    cancel(client, event_id)

    with Session(app.extensions["engine"]) as session:
        entries = session.scalars(
            select(VenueBookingStatusHistory)
            .where(VenueBookingStatusHistory.action == "cancel")
            .order_by(VenueBookingStatusHistory.booking_id)
        ).all()
    assert [entry.booking_id for entry in entries] == sorted([ids["approved"], ids["requested"]])
    assert {(entry.previous_status, entry.resulting_status) for entry in entries} == {
        ("approved", "cancelled"),
        ("requested", "cancelled"),
    }
    assert {entry.note for entry in entries} == {f"Event cancelled: {REASON}"}
    assert {entry.actor_account_id for entry in entries} == {COORDINATOR}


# TC-SPL-86-14 (BB) AC3: the cancelled venue's time is available to another event
def test_tc_spl_86_14_slot_time_released(app, client):
    event_id = add_event(app)
    requested = client.post(
        f"/api/event-requests/{event_id}/venue-bookings",
        json={"venue_id": 1, "layout": "theatre"},
        headers=headers(),
    )
    assert requested.status_code == 201, requested.json
    other = add_event(app)
    taken = client.post(
        f"/api/event-requests/{other}/venue-bookings",
        json={"venue_id": 1, "layout": "theatre"},
        headers=headers(),
    )
    assert taken.status_code == 409

    assert cancel(client, event_id).status_code == 200

    assert count(app, VenueBookingOccupancy) == 0
    again = client.post(
        f"/api/event-requests/{other}/venue-bookings",
        json={"venue_id": 1, "layout": "theatre"},
        headers=headers(),
    )
    assert again.status_code == 201, again.json


# TC-SPL-86-15 (BB) AC3: 15-minute bookings release their exact occupied time
def test_tc_spl_86_15_exact_time_released(app, client):
    app.config["EXACT_VENUE_TIMING_ENABLED"] = True
    with Session(app.extensions["engine"]) as session:
        venue = session.get(Venue, 1)
        venue.setup_minutes, venue.turnaround_minutes = 30, 30
        venue.operating_intervals = [[0, 1440]]
        venue.timing_revision = 1
        session.commit()
    body = {
        "venue_id": 1,
        "layout": "theatre",
        "date": EVENT_DATE.isoformat(),
        "start_time": "14:00",
        "end_time": "17:00",
        "venue_revision": 1,
    }
    event_id, other = add_event(app), add_event(app)
    first = client.post(
        f"/api/event-requests/{event_id}/venue-bookings", json=body, headers=headers()
    )
    assert first.status_code == 201, first.json
    assert (
        client.post(
            f"/api/event-requests/{other}/venue-bookings", json=body, headers=headers()
        ).status_code
        == 409
    )

    assert cancel(client, event_id).status_code == 200

    second = client.post(
        f"/api/event-requests/{other}/venue-bookings", json=body, headers=headers()
    )
    assert second.status_code == 201, second.json


# TC-SPL-86-16 (BB) AC3: every still-held unit is released, partly reserved and Review-required too
def test_tc_spl_86_16_every_held_unit_released(app, client):
    event_id, _, lines = full_event(app)
    assert (
        held(app, lines["reserved"]),
        held(app, lines["partial"]),
        held(app, lines["review"]),
    ) == (4, 2, 2)

    response = cancel(client, event_id)

    assert response.json["released"]["equipment_units"] == 8
    assert (
        held(app, lines["reserved"]),
        held(app, lines["partial"]),
        held(app, lines["review"]),
    ) == (0, 0, 0)


# TC-SPL-86-17 (WB) AC3: releases are appended to the equipment history with the reason
def test_tc_spl_86_17_releases_recorded_in_equipment_history(app, client):
    event_id, _, _ = full_event(app)

    cancel(client, event_id)

    with Session(app.extensions["engine"]) as session:
        new = session.scalars(
            select(EquipmentReservationRelease).where(
                EquipmentReservationRelease.reason == f"Event cancelled: {REASON}"
            )
        ).all()
        earlier = session.scalars(
            select(EquipmentReservationRelease).where(
                EquipmentReservationRelease.reason == "Units returned early."
            )
        ).all()
    assert sorted(item.quantity for item in new) == [2, 2, 4]
    assert {item.released_by_account_id for item in new} == {COORDINATOR}
    assert len(earlier) == 1  # the earlier Technical Support release is kept


# TC-SPL-86-18 (WB) AC3: line statuses follow SPL-98 - Review Required is kept
def test_tc_spl_86_18_line_statuses_after_release(app, client):
    event_id, _, lines = full_event(app)

    cancel(client, event_id)

    assert line_status(app, lines["reserved"]) == "requested"
    assert line_status(app, lines["partial"]) == "requested"
    assert line_status(app, lines["review"]) == "review_required"


# TC-SPL-86-19 (BB) AC3: lines holding nothing, unmapped or removed lines are untouched
def test_tc_spl_86_19_lines_without_holdings_untouched(app, client):
    event_id = add_event(app)
    nothing = add_line(app, event_id, status="requested")
    unmapped = add_line(app, event_id, status="unmapped", mapped=False, essentiality="undecided")
    removed = add_line(app, event_id, status="removed")
    released = add_line(app, event_id)
    reserve(app, event_id, released, 4, released=4)

    response = cancel(client, event_id)

    assert response.status_code == 200
    assert response.json["released"]["equipment_units"] == 0
    assert [line_status(app, line) for line in (nothing, unmapped, removed, released)] == [
        "requested",
        "unmapped",
        "removed",
        "reserved",
    ]
    assert count(app, EquipmentReservationRelease) == 1


# AC4 - all or nothing ---------------------------------------------------------------------------


# TC-SPL-86-20 (WB) AC4: a failure while releasing equipment leaves everything as it was
def test_tc_spl_86_20_equipment_failure_rolls_back(app, client, monkeypatch):
    import app.equipment_releases as releases

    event_id, _, _ = full_event(app)
    before = everything(app, event_id)

    def fail(*args, **kwargs):
        raise RuntimeError("stock service unavailable")

    monkeypatch.setattr(releases, "_release_from_requirement", fail)
    with pytest.raises(RuntimeError):
        cancel(client, event_id)

    assert everything(app, event_id) == before


# TC-SPL-86-21 (WB) AC4: a failure while cancelling a booking leaves everything as it was
def test_tc_spl_86_21_booking_failure_rolls_back(app, client, monkeypatch):
    import app.venue_conflicts as conflicts

    event_id, _, _ = full_event(app)
    before = everything(app, event_id)

    def fail(*args, **kwargs):
        raise RuntimeError("booking ledger unavailable")

    monkeypatch.setattr(conflicts, "transition_booking_status", fail)
    with pytest.raises(RuntimeError):
        cancel(client, event_id)

    assert everything(app, event_id) == before


# TC-SPL-86-22 (WB) AC4: a failure after every release, before commit, keeps nothing
def test_tc_spl_86_22_failure_after_releases_rolls_back(app, client, monkeypatch):
    event_id, _, _ = full_event(app)
    before = everything(app, event_id)
    original = event_cancellation._release_equipment

    def release_then_fail(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("commit interrupted")

    monkeypatch.setattr(event_cancellation, "_release_equipment", release_then_fail)
    with pytest.raises(RuntimeError):
        cancel(client, event_id)

    assert everything(app, event_id) == before


# TC-SPL-86-23 (BB) AC4: a refused cancellation changes no booking, claim, history or release
@pytest.mark.parametrize("refusal", ["blank", "lead", "final"])
def test_tc_spl_86_23_refusals_change_nothing(app, client, refusal):
    event_id, _, _ = full_event(app, status="planning" if refusal != "final" else "completed")
    before = everything(app, event_id)

    if refusal == "blank":
        cancel(client, event_id, reason="  ")
    elif refusal == "lead":
        cancel(client, event_id, identity="lead")
    else:
        cancel(client, event_id)

    assert everything(app, event_id) == before


# AC5 - only once ------------------------------------------------------------------------------


# TC-SPL-86-24 (BB) AC5: a second cancellation is refused and releases nothing again
def test_tc_spl_86_24_second_cancellation_refused(app, client):
    event_id, _, _ = full_event(app)
    assert cancel(client, event_id).status_code == 200
    after_first = everything(app, event_id)

    again = cancel(client, event_id, reason="Second attempt")

    assert again.status_code == 409
    assert again.json["error"] == "This event is already cancelled."
    assert everything(app, event_id) == after_first
    assert event_row(app, event_id)["reason"] == REASON


# TC-SPL-86-25 (BB) AC5: the second refusal also applies to another coordinator after reassignment
def test_tc_spl_86_25_cancelled_event_stays_cancelled_for_new_coordinator(app, client):
    event_id = add_event(app)
    assert cancel(client, event_id).status_code == 200
    with Session(app.extensions["engine"]) as session:
        session.scalar(
            select(EventCoordinatorAssignment).where(
                EventCoordinatorAssignment.event_request_id == event_id
            )
        ).coordinator_account_id = OTHER_COORDINATOR
        session.commit()

    response = cancel(client, event_id, identity="other-coordinator")

    assert response.status_code == 409
    assert event_row(app, event_id)["cancelled_by"] == COORDINATOR


# AC6 - records are kept ------------------------------------------------------------------------


# TC-SPL-86-26 (BB) AC6: the event records who cancelled it, when and why, with status history
def test_tc_spl_86_26_cancellation_recorded(app, client):
    event_id = add_event(app)
    started = datetime.now(timezone.utc)

    response = cancel(client, event_id)

    row = event_row(app, event_id)
    cancelled_at = (
        row["cancelled_at"]
        if row["cancelled_at"].tzinfo
        else row["cancelled_at"].replace(tzinfo=base.SINGAPORE)
    )
    assert row["cancelled_by"] == COORDINATOR
    assert started <= cancelled_at <= datetime.now(timezone.utc)
    assert row["reason"] == REASON
    assert row["history"][-1] == "cancel"
    assert response.json["event"]["cancelled_by"]["name"] == "Casey Coordinator"
    assert response.json["event"]["cancelled_at"].endswith("+08:00")


# TC-SPL-86-27 (BB) AC6: the organiser sees Cancelled with the reason, who and when
def test_tc_spl_86_27_organiser_view(app, client):
    event_id = add_event(app)
    cancel(client, event_id)

    body = client.get("/api/event-requests", headers=headers("organiser")).json
    item = next(event for event in body["event_requests"] if event["id"] == event_id)

    assert item["status"] == "cancelled"
    assert item["cancelled_by"]["name"] == "Casey Coordinator"
    assert item["cancellation_reason"] == REASON
    assert item["cancelled_at"].endswith("+08:00")


# TC-SPL-86-28 (BB) AC6: the coordinator's detail and the Lead's supervision view show it
def test_tc_spl_86_28_coordinator_and_lead_views(app, client):
    event_id = add_event(app)
    cancel(client, event_id)

    detail = client.get(f"/api/event-requests/assigned/{event_id}", headers=headers())
    supervision = client.get("/api/event-requests/supervision", headers=headers("lead"))
    basic = client.get(f"/api/event-requests/{event_id}/basic-information", headers=headers("lead"))

    assert detail.status_code == 200
    event = detail.json["event"]
    assert (event["status"], event["cancellation_reason"]) == ("cancelled", REASON)
    listed = next(item for item in supervision.json["events"] if item["id"] == event_id)
    assert (listed["status"], listed["cancellation_reason"], listed["cancelled_by"]["name"]) == (
        "cancelled",
        REASON,
        "Casey Coordinator",
    )
    assert listed["reassignable"] is False
    assert basic.json["event"]["cancellation_reason"] == REASON


# TC-SPL-86-29 (BB) AC6: access is unchanged - no new viewer gains the event
@pytest.mark.parametrize(
    ("identity", "path", "expected"),
    [
        ("other-coordinator", "/api/event-requests/assigned/{id}", 404),
        ("organiser", "/api/event-requests/assigned/{id}", 403),
        ("venue-staff", "/api/event-requests/assigned/{id}", 403),
        ("technical", "/api/event-requests/supervision", 403),
    ],
)
def test_tc_spl_86_29_no_new_access(app, client, identity, path, expected):
    event_id = add_event(app)
    before = client.get(path.format(id=event_id), headers=headers(identity)).status_code
    cancel(client, event_id)

    after = client.get(path.format(id=event_id), headers=headers(identity)).status_code

    assert before == after == expected


# TC-SPL-86-30 (BB) AC6: bookings, equipment history and registrations are kept (Q20, Q115)
def test_tc_spl_86_30_records_retained(app, client):
    event_id, ids, lines = full_event(app)
    with Session(app.extensions["engine"]) as session:
        session.add(
            EventRegistration(
                event_request_id=event_id,
                attendee_account_id=LEAD,
                status="registered",
                name="Lee Lead",
                email="lee@example.test",
                contact_number="+65 6000 0000",
                registered_at=NOW,
            )
        )
        session.commit()

    cancel(client, event_id)

    assert len(bookings(app, event_id)) == 5
    assert count(app, EquipmentRequirement, EquipmentRequirement.event_request_id == event_id) == 3
    assert count(app, EventRegistration, EventRegistration.status == "registered") == 1
    status = client.get(f"/api/event-requests/{event_id}/venue-booking-status", headers=headers())
    listed = {item["booking"]["id"]: item for item in status.json["bookings"]}
    assert listed[ids["approved"]]["current_status"]["status"] == "cancelled"
    assert listed[ids["approved"]]["history"][-1]["note"] == f"Event cancelled: {REASON}"
    review = client.get(f"/api/venue-bookings/{ids['approved']}", headers=headers("venue-staff"))
    assert review.status_code == 200
    assert review.json["booking"]["status"] == "cancelled"


# AC7 - no longer pending -----------------------------------------------------------------------


# TC-SPL-86-31 (BB) AC7: the Venue Staff review queue drops the event's requests
def test_tc_spl_86_31_venue_queue(app, client):
    event_id, ids, _ = full_event(app)

    def queue():
        return queued_ids(client, "/api/venue-bookings/pending", "venue-staff", "requests", "id")

    assert ids["requested"] in queue()

    cancel(client, event_id)

    assert ids["requested"] not in queue()


# TC-SPL-86-32 (BB) AC7: the Technical Support review queue drops the event's lines
def test_tc_spl_86_32_equipment_review_queue(app, client):
    event_id, _, lines = full_event(app)

    def queue():
        return queued_ids(client, "/api/equipment-review-queue", "technical", "requirements", "id")

    assert lines["review"] in queue()

    cancel(client, event_id)

    assert lines["review"] not in queue()


# TC-SPL-86-33 (BB) AC7: the Technical Support availability list drops the event's lines
def test_tc_spl_86_33_equipment_availability_list(app, client):
    event_id = add_event(app)
    line = add_line(app, event_id, status="partially_reserved")
    reserve(app, event_id, line, 2)

    def listed():
        return queued_ids(
            client, "/api/equipment-availability", "technical", "assessments", "requirement_id"
        )

    assert line in listed()

    cancel(client, event_id)

    assert line not in listed()


# TC-SPL-86-34 (BB) AC7: nothing actionable remains - no new venue request or reservation
def test_tc_spl_86_34_no_further_actions(app, client):
    event_id = add_event(app)
    line = add_line(app, event_id, status="requested")
    cancel(client, event_id)

    venue = client.post(
        f"/api/event-requests/{event_id}/venue-bookings",
        json={"venue_id": 1, "layout": "theatre"},
        headers=headers(),
    )
    reservation = client.post(
        f"/api/equipment-requirements/{line}/reservations",
        json={"quantity": 1},
        headers=headers("technical"),
    )

    assert venue.status_code == 409
    assert reservation.status_code == 409


# White-box: rule table ---------------------------------------------------------------------


# TC-SPL-86-35 (WB) AC1/AC2: the shared transition rule lists exactly the cancellable statuses
def test_tc_spl_86_35_transition_rule(app):
    from app.event_review import CANCEL, TRANSITION_RULES

    rule = TRANSITION_RULES[CANCEL]
    assert set(rule.previous_status) == set(CANCELLABLE)
    assert rule.resulting_status == "cancelled"


# TC-SPL-86-43 (WB) AC2/AC4: if the shared rule refuses the event's status, nothing changes
def test_tc_spl_86_43_rule_refusal_changes_nothing(app, client, monkeypatch):
    from app.event_review import CANCEL, TRANSITION_RULES, TransitionRule

    event_id, _, _ = full_event(app, status="planning")
    before = everything(app, event_id)
    monkeypatch.setitem(
        TRANSITION_RULES,
        CANCEL,
        TransitionRule(previous_status=("submitted",), resulting_status="cancelled"),
    )

    response = cancel(client, event_id)

    assert response.status_code == 409
    assert response.json["error"] == "This event cannot be cancelled in its current status."
    assert everything(app, event_id) == before


_ = time
