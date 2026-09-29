"""Acceptance coverage for SPL-82 (CS-E10-S4): reject a venue-booking request with a reason.

Each test carries the QA-SPL-82 case identifier it proves. Expected values come from the story's
acceptance criteria and its two recorded judgement calls (docs/tasks/SPL-82.md): the reason and the
alternative suggestion are separate fields, and rejection does not recheck the event's status.
"""

from datetime import date, datetime, time, timedelta, timezone

import pytest
from app import create_app
from app.event_requests import SINGAPORE
from app.models import (
    Account,
    AccountRole,
    Base,
    EventCoordinatorAssignment,
    EventRequest,
    Organisation,
    Role,
    Venue,
    VenueBooking,
    VenueBookingOccupancy,
    VenueBookingStatusHistory,
    VenueLayout,
)
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

COORDINATOR = "00000000-0000-0000-0000-000000000821"
OTHER_COORDINATOR = "00000000-0000-0000-0000-000000000826"
ORGANISER = "00000000-0000-0000-0000-000000000822"
VENUE_STAFF = "00000000-0000-0000-0000-000000000823"
MANAGER = "00000000-0000-0000-0000-000000000824"
TOKENS = {
    "coordinator": COORDINATOR,
    "other-coordinator": OTHER_COORDINATOR,
    "organiser": ORGANISER,
    "venue-staff": VENUE_STAFF,
    "manager": MANAGER,
}
EVENT_DATE = date(2026, 10, 14)
HARBOUR_CLAIM = {
    (EVENT_DATE, "AM", "setup"),
    (EVENT_DATE, "PM", "event"),
    (EVENT_DATE, "NIGHT", "turnaround"),
}
REASON = "Harbour Hall's PA system is under repair that week."
SUGGESTION = "The Riverside Room is free the same afternoon."
REQUEST_COLUMNS = (
    "event_request_id",
    "venue_id",
    "layout",
    "expected_attendance",
    "booking_date",
    "event_slots",
    "setup_date",
    "setup_slot",
    "turnaround_date",
    "turnaround_slot",
    "requested_by_account_id",
    "requested_at",
)


@pytest.fixture
def app(tmp_path):
    app = create_app(
        {
            "TESTING": True,
            "DATABASE_URL": f"sqlite:///{tmp_path}/booking-rejection.db",
            "IDENTITY_VERIFIER": TOKENS.__getitem__,
        }
    )
    engine = app.extensions["engine"]
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        organisation = Organisation(name="SPL-82 client")
        session.add(organisation)
        session.flush()
        for account_id, name, role in (
            (COORDINATOR, "Casey Lim", Role.EVENT_COORDINATOR),
            (OTHER_COORDINATOR, "Taylor Tan", Role.EVENT_COORDINATOR),
            (ORGANISER, "Devon Lee", Role.EVENT_ORGANISER),
            (VENUE_STAFF, "Valerie Tan", Role.VENUE_STAFF),
            (MANAGER, "Morgan Ong", Role.EVENT_OPERATIONS_MANAGER),
        ):
            session.add(Account(id=account_id, display_name=name, organisation_id=organisation.id))
            session.add(AccountRole(account_id=account_id, role=role.value))
        session.commit()
        app.config["ORGANISATION_ID"] = organisation.id
    yield app
    engine.dispose()


@pytest.fixture
def client(app):
    return app.test_client()


def make_event(app, name="Coastal Forum", *, day=EVENT_DATE, start=time(13), end=time(18)):
    with Session(app.extensions["engine"]) as session:
        event = EventRequest(
            organiser_account_id=ORGANISER,
            organisation_id=app.config["ORGANISATION_ID"],
            name=name,
            purpose="Community planning",
            proposed_date=day,
            start_time=start,
            end_time=end,
            expected_attendance=150,
            required_facilities=["Projector"],
            accessibility_needs=["Step-free access"],
            location_preference="Marina Centre",
            status="planning",
        )
        session.add(event)
        session.flush()
        session.add(
            EventCoordinatorAssignment(
                event_request_id=event.id,
                coordinator_account_id=COORDINATOR,
                assigned_by_account_id=MANAGER,
                assigned_at=datetime(2026, 9, 20, 9, tzinfo=timezone.utc),
            )
        )
        session.commit()
        return event.id


def add_venue(app, name="Harbour Hall"):
    with Session(app.extensions["engine"]) as session:
        venue = Venue(
            name=name,
            location="Level 3, Marina Centre",
            facilities=["Projector", "PA system"],
            accessibility_features=["Step-free access"],
            operating_slots=["AM", "PM", "NIGHT"],
            setup_buffer_slots=1,
            turnaround_buffer_slots=1,
        )
        venue.layouts = [VenueLayout(layout="theatre", capacity=200)]
        session.add(venue)
        session.commit()
        return venue.id


def headers(token="venue-staff"):
    return {"Authorization": f"Bearer {token}"} if token else {}


def request_booking(client, event_id, venue_id):
    return client.post(
        f"/api/event-requests/{event_id}/venue-bookings",
        json={"venue_id": venue_id, "layout": "theatre"},
        headers=headers("coordinator"),
    )


def reject(client, booking_id, body=None, token="venue-staff", **kwargs):
    if body is not None:
        kwargs["json"] = body
    return client.post(f"/api/venue-bookings/{booking_id}/reject", headers=headers(token), **kwargs)


def latest(client, event_id, token="coordinator"):
    return client.get(
        f"/api/event-requests/{event_id}/venue-bookings/latest", headers=headers(token)
    )


def read_for_coordinator(client, event_id, booking_id, token="coordinator"):
    return client.get(
        f"/api/event-requests/{event_id}/venue-bookings/{booking_id}", headers=headers(token)
    )


@pytest.fixture
def requested(app, client):
    """The booking under test: Coastal Forum at Harbour Hall, Requested through SPL-77."""

    event_id, venue_id = make_event(app), add_venue(app)
    response = request_booking(client, event_id, venue_id)
    assert response.status_code == 201, response.json
    return {"event": event_id, "venue": venue_id, "booking": response.json["booking"]}


def stored(app, booking_id):
    with Session(app.extensions["engine"]) as session:
        booking = session.get(VenueBooking, booking_id)
        return {column.key: getattr(booking, column.key) for column in booking.__mapper__.columns}


def occupancy_rows(app, booking_id):
    with Session(app.extensions["engine"]) as session:
        return sorted(
            (row.id, row.day, row.slot, row.kind)
            for row in session.scalars(
                select(VenueBookingOccupancy).where(VenueBookingOccupancy.booking_id == booking_id)
            )
        )


def history(app, booking_id):
    with Session(app.extensions["engine"]) as session:
        return [
            (row.action, row.resulting_status, row.actor_account_id, row.note)
            for row in session.scalars(
                select(VenueBookingStatusHistory)
                .where(VenueBookingStatusHistory.booking_id == booking_id)
                .order_by(VenueBookingStatusHistory.changed_at, VenueBookingStatusHistory.id)
            )
        ]


def snapshot(app, booking_id):
    return {
        "booking": stored(app, booking_id),
        "occupancy": occupancy_rows(app, booking_id),
        "history": history(app, booking_id),
    }


def set_booking_status(app, booking_id, status):
    with Session(app.extensions["engine"]) as session:
        session.execute(
            update(VenueBooking).where(VenueBooking.id == booking_id).values(status=status)
        )
        session.commit()


def set_event_status(app, event_id, status):
    with Session(app.extensions["engine"]) as session:
        session.execute(
            update(EventRequest).where(EventRequest.id == event_id).values(status=status)
        )
        session.commit()


def assert_still_requested(app, booking_id):
    row = stored(app, booking_id)
    assert row["status"] == "requested"
    assert row["rejected_by_account_id"] is None
    assert row["rejected_at"] is None
    assert row["rejection_reason"] is None
    assert row["rejection_alternative_suggestion"] is None


# AC1 / AC7 — only Venue Staff, only Requested


# TC-SPL-82-01
def test_tc_spl_82_01_venue_staff_reject_a_requested_booking(app, client, requested):
    booking_id = requested["booking"]["id"]

    response = reject(client, booking_id, {"reason": REASON})

    assert response.status_code == 200, response.json
    assert response.json["booking"]["status"] == "rejected"
    assert stored(app, booking_id)["status"] == "rejected"
    with Session(app.extensions["engine"]) as session:
        assert session.scalar(select(func.count(VenueBooking.id))) == 1


# TC-SPL-82-13
@pytest.mark.parametrize(
    ("token", "expected"),
    [("coordinator", 403), ("organiser", 403), ("manager", 403), (None, 401)],
)
def test_tc_spl_82_13_other_roles_and_no_session_are_refused(
    app, client, requested, token, expected
):
    booking_id = requested["booking"]["id"]

    assert reject(client, booking_id, {"reason": REASON}, token=token).status_code == expected
    assert_still_requested(app, booking_id)
    # Non-vacuous: a genuine Venue Staff rejection must still succeed in this same run.
    assert reject(client, booking_id, {"reason": REASON}).status_code == 200


# TC-SPL-82-14
@pytest.mark.parametrize("status", ["approved", "rejected", "withdrawn", "cancelled"])
def test_tc_spl_82_14_only_a_requested_booking_is_rejectable(app, client, requested, status):
    booking_id = requested["booking"]["id"]
    set_booking_status(app, booking_id, status)
    before = snapshot(app, booking_id)

    response = reject(client, booking_id, {"reason": REASON})

    assert response.status_code == 409
    assert response.json["error"] == "Only a Requested venue-booking request can be rejected."
    assert snapshot(app, booking_id) == before


# TC-SPL-82-09: the second judgement call — rejection does not recheck the event's status.
@pytest.mark.parametrize("status", ["confirmed", "completed", "cancelled", "postponed"])
def test_tc_spl_82_09_rejection_does_not_require_planning(app, client, requested, status):
    booking_id = requested["booking"]["id"]
    set_event_status(app, requested["event"], status)

    response = reject(client, booking_id, {"reason": REASON})

    assert response.status_code == 200, response.json
    assert response.json["booking"]["status"] == "rejected"


# TC-SPL-82-15
def test_tc_spl_82_15_unknown_booking_is_refused(app, client, requested):
    unknown = reject(client, 999999, {"reason": REASON})
    out_of_range = reject(client, 2**31, {"reason": REASON})

    assert unknown.status_code == out_of_range.status_code == 404
    assert unknown.json == out_of_range.json


# AC2 — a non-blank reason is required; the alternative suggestion is optional


# TC-SPL-82-02
def test_tc_spl_82_02_reason_is_required(app, client, requested):
    booking_id = requested["booking"]["id"]

    assert reject(client, booking_id, {}).status_code == 400
    assert reject(client, booking_id).status_code == 400
    assert_still_requested(app, booking_id)


# TC-SPL-82-03
@pytest.mark.parametrize("reason", ["", "   ", "\t\n"])
def test_tc_spl_82_03_blank_reason_is_refused(app, client, requested, reason):
    booking_id = requested["booking"]["id"]

    response = reject(client, booking_id, {"reason": reason})

    assert response.status_code == 400
    assert_still_requested(app, booking_id)


# TC-SPL-82-04
def test_tc_spl_82_04_reason_length_is_bounded(app, client, requested):
    booking_id = requested["booking"]["id"]

    over = reject(client, booking_id, {"reason": "x" * 1001})
    assert over.status_code == 400
    assert_still_requested(app, booking_id)

    at_limit = reject(client, booking_id, {"reason": "x" * 1000})
    assert at_limit.status_code == 200, at_limit.json


# TC-SPL-82-05
def test_tc_spl_82_05_alternative_suggestion_is_optional(app, client, requested):
    with_suggestion = requested["booking"]["id"]
    response = reject(
        client, with_suggestion, {"reason": REASON, "alternative_suggestion": SUGGESTION}
    )
    assert response.status_code == 200, response.json
    assert response.json["booking"]["rejection_alternative_suggestion"] == SUGGESTION
    assert stored(app, with_suggestion)["rejection_alternative_suggestion"] == SUGGESTION

    event_id, venue_id = make_event(app, "Harbour Talk"), requested["venue"]
    other = request_booking(client, event_id, venue_id).json["booking"]["id"]
    response = reject(client, other, {"reason": REASON})
    assert response.status_code == 200, response.json
    assert response.json["booking"]["rejection_alternative_suggestion"] is None
    assert stored(app, other)["rejection_alternative_suggestion"] is None


@pytest.mark.parametrize(
    "suggestion",
    [None, "x" * 1000, "  The Riverside Room is free.  "],
    ids=["null", "at-limit", "trimmed"],
)
def test_tc_spl_82_05_alternative_suggestion_values(app, client, requested, suggestion):
    booking_id = requested["booking"]["id"]

    response = reject(client, booking_id, {"reason": REASON, "alternative_suggestion": suggestion})

    assert response.status_code == 200, response.json


def test_tc_spl_82_05_alternative_suggestion_length_is_bounded(app, client, requested):
    booking_id = requested["booking"]["id"]

    response = reject(client, booking_id, {"reason": REASON, "alternative_suggestion": "x" * 1001})

    assert response.status_code == 400
    assert_still_requested(app, booking_id)


def test_tc_spl_82_05_alternative_suggestion_must_be_text(app, client, requested):
    booking_id = requested["booking"]["id"]

    response = reject(client, booking_id, {"reason": REASON, "alternative_suggestion": 42})

    assert response.status_code == 400
    assert response.json["error"] == "The alternative suggestion must be text."
    assert_still_requested(app, booking_id)


# AC3 — a successful rejection records the reason, actor and time


# TC-SPL-82-06
def test_tc_spl_82_06_rejection_records_actor_time_and_reason(app, client, requested):
    booking_id = requested["booking"]["id"]
    before = stored(app, booking_id)
    started = datetime.now(SINGAPORE)

    response = reject(client, booking_id, {"reason": REASON})

    finished = datetime.now(SINGAPORE)
    assert response.status_code == 200, response.json
    booking = response.json["booking"]
    assert booking["rejected_by"] == {"id": VENUE_STAFF, "name": "Valerie Tan"}
    assert booking["rejection_reason"] == REASON
    rejected_at = datetime.fromisoformat(booking["rejected_at"])
    assert rejected_at.utcoffset() == timedelta(hours=8)
    assert started - timedelta(seconds=1) <= rejected_at <= finished + timedelta(seconds=1)
    row = stored(app, booking_id)
    assert row["rejected_by_account_id"] == VENUE_STAFF
    assert row["rejection_reason"] == REASON
    assert row["rejected_at"] is not None
    for column in REQUEST_COLUMNS:
        assert row[column] == before[column], column


# TC-SPL-82-07
def test_tc_spl_82_07_rejection_is_appended_to_history_with_reason_as_note(app, client, requested):
    booking_id = requested["booking"]["id"]

    assert (
        reject(
            client, booking_id, {"reason": REASON, "alternative_suggestion": SUGGESTION}
        ).status_code
        == 200
    )

    assert history(app, booking_id) == [
        ("request", "requested", COORDINATOR, None),
        ("reject", "rejected", VENUE_STAFF, REASON),
    ]


# AC4 — the rejected request's slots no longer count as occupied


# TC-SPL-82-08
def test_tc_spl_82_08_rejected_slots_are_freed(app, client, requested):
    assert reject(client, requested["booking"]["id"], {"reason": REASON}).status_code == 200
    other = make_event(app, "Harbour Talk")

    for slot in ("AM", "PM", "NIGHT"):
        found = client.get(
            f"/api/event-requests/{other}/available-venues?date={EVENT_DATE.isoformat()}&slot={slot}",
            headers=headers("coordinator"),
        )
        assert found.status_code == 200, found.json
        assert "Harbour Hall" in {venue["name"] for venue in found.json["venues"]}, slot

    reclaim = request_booking(client, other, requested["venue"])
    assert reclaim.status_code == 201, reclaim.json


def test_tc_spl_82_08_occupancy_rows_are_deleted(app, client, requested):
    booking_id = requested["booking"]["id"]
    assert occupancy_rows(app, booking_id) != []

    assert reject(client, booking_id, {"reason": REASON}).status_code == 200

    assert occupancy_rows(app, booking_id) == []


# AC5 — the assigned Event Coordinator can retrieve the outcome and reason


# TC-SPL-82-10
def test_tc_spl_82_10_assigned_coordinator_reads_the_outcome(app, client, requested):
    booking_id = requested["booking"]["id"]
    assert (
        reject(
            client, booking_id, {"reason": REASON, "alternative_suggestion": SUGGESTION}
        ).status_code
        == 200
    )

    via_latest = latest(client, requested["event"]).json["booking"]
    via_id = read_for_coordinator(client, requested["event"], booking_id).json["booking"]

    for booking in (via_latest, via_id):
        assert booking["status"] == "rejected"
        assert booking["rejected_by"] == {"id": VENUE_STAFF, "name": "Valerie Tan"}
        assert booking["rejection_reason"] == REASON
        assert booking["rejection_alternative_suggestion"] == SUGGESTION
        assert booking["rejected_at"] is not None


# TC-SPL-82-11
def test_tc_spl_82_11_unassigned_coordinator_cannot_read_it(app, client, requested):
    booking_id = requested["booking"]["id"]
    assert reject(client, booking_id, {"reason": REASON}).status_code == 200

    response = read_for_coordinator(
        client, requested["event"], booking_id, token="other-coordinator"
    )

    assert response.status_code == 404


# AC6 — Venue Staff cannot amend venue, date, layout or slots while rejecting


# TC-SPL-82-12
@pytest.mark.parametrize(
    "body",
    [
        {"reason": REASON, "venue_id": 999},
        {"reason": REASON, "layout": "banquet"},
        {"reason": REASON, "event_slots": ["AM"]},
        {"reason": REASON, "status": "approved"},
    ],
)
def test_tc_spl_82_12_nothing_else_can_be_supplied(app, client, requested, body):
    booking_id = requested["booking"]["id"]
    before = snapshot(app, booking_id)

    response = reject(client, booking_id, body)

    assert response.status_code == 400
    assert snapshot(app, booking_id) == before


# TC-SPL-82-16 — every refusal above leaves the booking, occupancy and history untouched
@pytest.mark.parametrize(
    "refusal",
    ["wrong-role", "no-session", "not-requested", "blank-reason", "too-long", "unknown-field"],
)
def test_tc_spl_82_16_refusals_change_nothing(app, client, requested, refusal):
    booking_id = requested["booking"]["id"]
    token, body = "venue-staff", {"reason": REASON}
    if refusal == "wrong-role":
        token = "coordinator"
    elif refusal == "no-session":
        token = None
    elif refusal == "not-requested":
        set_booking_status(app, booking_id, "approved")
    elif refusal == "blank-reason":
        body = {"reason": "   "}
    elif refusal == "too-long":
        body = {"reason": "x" * 1001}
    else:
        body = {"reason": REASON, "venue_id": 999}
    before = snapshot(app, booking_id)

    response = reject(client, booking_id, body, token=token)

    assert not 200 <= response.status_code < 300
    assert snapshot(app, booking_id) == before
    # Non-vacuous (Week 6): a genuine rejection on a fresh booking must still succeed in this
    # same run, or the refusal above could just be an unrouted address answering 403/404. A
    # second venue avoids colliding with the original booking's still-held slots.
    other_event, other_venue = make_event(app, "Harbour Talk"), add_venue(app, "Riverside Room")
    fresh = request_booking(client, other_event, other_venue).json["booking"]["id"]
    assert reject(client, fresh, {"reason": REASON}).status_code == 200
