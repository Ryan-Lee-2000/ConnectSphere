"""Acceptance coverage for SPL-81 (CS-E10-S3): approve a venue-booking request safely.

Each test carries the QA-SPL-81 case identifier it proves. Expected values come from the story's
acceptance criteria, its recorded assumptions and the answered customer questions.
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

COORDINATOR = "00000000-0000-0000-0000-000000000811"
ORGANISER = "00000000-0000-0000-0000-000000000812"
VENUE_STAFF = "00000000-0000-0000-0000-000000000813"
MANAGER = "00000000-0000-0000-0000-000000000814"
TOKENS = {
    "coordinator": COORDINATOR,
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
NOTE = "Confirmed with the hall manager"
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
            "DATABASE_URL": f"sqlite:///{tmp_path}/booking-approval.db",
            "IDENTITY_VERIFIER": TOKENS.__getitem__,
        }
    )
    engine = app.extensions["engine"]
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        organisation = Organisation(name="SPL-81 client")
        session.add(organisation)
        session.flush()
        for account_id, name, role in (
            (COORDINATOR, "Casey Lim", Role.EVENT_COORDINATOR),
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


def approve(client, booking_id, body=None, token="venue-staff", **kwargs):
    if body is not None:
        kwargs["json"] = body
    return client.post(
        f"/api/venue-bookings/{booking_id}/approve", headers=headers(token), **kwargs
    )


def review(client, booking_id, token="venue-staff"):
    return client.get(f"/api/venue-bookings/{booking_id}", headers=headers(token))


def block(client, venue_id, day, slot, reason="Ceiling repair"):
    response = client.post(
        f"/api/venues/{venue_id}/operational-blocks",
        json={"start_date": day.isoformat(), "slots": [slot], "reason": reason},
        headers=headers(),
    )
    assert response.status_code == 201, response.json
    return response.json["operational_block"]["id"]


def remove_block(client, venue_id, block_id):
    response = client.delete(
        f"/api/venues/{venue_id}/operational-blocks/{block_id}", headers=headers()
    )
    assert response.status_code == 200, response.json


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


def seed_booking(app, event_id, venue_id, status):
    with Session(app.extensions["engine"]) as session:
        booking = VenueBooking(event_request_id=event_id, venue_id=venue_id, status=status)
        session.add(booking)
        session.commit()
        return booking.id


def reassign_slot(app, booking_id, slot, to_booking_id):
    """Controlled fixture: another booking now holds one of this booking's recorded slots."""

    with Session(app.extensions["engine"]) as session:
        session.execute(
            update(VenueBookingOccupancy)
            .where(
                VenueBookingOccupancy.booking_id == booking_id,
                VenueBookingOccupancy.slot == slot,
            )
            .values(booking_id=to_booking_id)
        )
        session.commit()


def assert_still_requested(app, booking_id):
    row = stored(app, booking_id)
    assert row["status"] == "requested"
    assert row["approved_by_account_id"] is None
    assert row["approved_at"] is None
    assert row["approval_note"] is None


# AC1 — only Venue Staff, only Requested, only Planning


# TC-SPL-81-01
# SPL-81 AC-1 Test-01
def test_tc_spl_81_01_venue_staff_approve_a_requested_booking(app, client, requested):
    booking_id = requested["booking"]["id"]

    response = approve(client, booking_id, {})

    assert response.status_code == 200, response.json
    assert response.json["booking"]["status"] == "approved"
    assert stored(app, booking_id)["status"] == "approved"
    with Session(app.extensions["engine"]) as session:
        assert session.scalar(select(func.count(VenueBooking.id))) == 1
        # Q80: approving the booking does not confirm the event.
        assert session.get(EventRequest, requested["event"]).status == "planning"


# TC-SPL-81-02
# SPL-81 AC-1 Test-02
@pytest.mark.parametrize(
    ("token", "expected"),
    [("coordinator", 403), ("organiser", 403), ("manager", 403), (None, 401)],
)
def test_tc_spl_81_02_other_roles_and_no_session_are_refused(
    app, client, requested, token, expected
):
    booking_id = requested["booking"]["id"]

    assert approve(client, booking_id, {}, token=token).status_code == expected
    assert_still_requested(app, booking_id)


# TC-SPL-81-03
# SPL-81 AC-1 Test-03
@pytest.mark.parametrize("status", ["approved", "rejected", "withdrawn", "cancelled"])
def test_tc_spl_81_03_only_a_requested_booking_is_approvable(app, client, requested, status):
    booking_id = requested["booking"]["id"]
    set_booking_status(app, booking_id, status)
    before = snapshot(app, booking_id)

    response = approve(client, booking_id, {"note": NOTE})

    assert response.status_code == 409
    assert response.json["error"] == "Only a Requested venue-booking request can be approved."
    assert snapshot(app, booking_id) == before


# TC-SPL-81-04
# SPL-81 AC-1 Test-04
@pytest.mark.parametrize("status", ["confirmed", "completed", "cancelled", "postponed"])
def test_tc_spl_81_04_event_must_be_in_planning(app, client, requested, status):
    booking_id = requested["booking"]["id"]
    set_event_status(app, requested["event"], status)

    response = approve(client, booking_id, {})

    assert response.status_code == 409
    assert response.json["error"] == (
        "The event must be in Planning for its venue booking to be approved."
    )
    assert_still_requested(app, booking_id)
    assert {row[1:] for row in occupancy_rows(app, booking_id)} == HARBOUR_CLAIM


# TC-SPL-81-05
# SPL-81 AC-1 Test-05
def test_tc_spl_81_05_unknown_booking_is_refused(app, client, requested):
    unknown = approve(client, 999999, {})
    out_of_range = approve(client, 2**31, {})

    assert unknown.status_code == out_of_range.status_code == 404
    assert unknown.json == out_of_range.json
    assert_still_requested(app, requested["booking"]["id"])


# AC2 — recheck every recorded slot; the request's own slots do not conflict


# TC-SPL-81-06
# SPL-81 AC-2 Test-06
def test_tc_spl_81_06_own_and_adjacent_slots_are_not_conflicts(app, client, requested):
    next_day = make_event(app, "Harbour Talk", day=EVENT_DATE + timedelta(days=1), start=time(13))
    neighbour = request_booking(client, next_day, requested["venue"])
    assert neighbour.status_code == 201, neighbour.json  # holds 15 Oct AM, PM and NIGHT

    response = approve(client, requested["booking"]["id"], {})

    assert response.status_code == 200, response.json


# TC-SPL-81-06 — a venue with no preparation buffers records only the event slot
# SPL-81 AC-2 Test-06
def test_tc_spl_81_06_venue_without_preparation_slots_is_approved(app, client):
    event_id, venue_id = make_event(app), add_venue(app, "Studio One")
    with Session(app.extensions["engine"]) as session:
        session.execute(
            update(Venue)
            .where(Venue.id == venue_id)
            .values(setup_buffer_slots=0, turnaround_buffer_slots=0)
        )
        session.commit()
    created = request_booking(client, event_id, venue_id)
    assert created.status_code == 201, created.json
    booking = created.json["booking"]
    assert (booking["setup"], booking["turnaround"]) == (None, None)

    response = approve(client, booking["id"], {})

    assert response.status_code == 200, response.json
    assert {row[1:] for row in occupancy_rows(app, booking["id"])} == {(EVENT_DATE, "PM", "event")}


# TC-SPL-81-07
# SPL-81 AC-2 Test-07
@pytest.mark.parametrize("slot", ["AM", "PM", "NIGHT"])
def test_tc_spl_81_07_operational_block_on_any_slot_refuses(app, client, requested, slot):
    booking_id = requested["booking"]["id"]
    block(client, requested["venue"], EVENT_DATE, slot)

    response = approve(client, booking_id, {})

    assert response.status_code == 409
    assert response.json["conflict"] == {"date": EVENT_DATE.isoformat(), "slot": slot}
    assert_still_requested(app, booking_id)


# TC-SPL-81-08
# SPL-81 AC-2 Test-08
@pytest.mark.parametrize("other_status", ["requested", "approved"])
def test_tc_spl_81_08_other_active_booking_on_a_slot_refuses(app, client, requested, other_status):
    booking_id = requested["booking"]["id"]
    other = seed_booking(app, make_event(app, "Harbour Talk"), requested["venue"], other_status)
    reassign_slot(app, booking_id, "NIGHT", other)

    response = approve(client, booking_id, {})

    assert response.status_code == 409
    assert response.json["conflict"] == {"date": EVENT_DATE.isoformat(), "slot": "NIGHT"}
    assert response.json["error"] == "Harbour Hall is unavailable on 14 Oct 2026 during Night."
    assert_still_requested(app, booking_id)


# TC-SPL-81-09
# SPL-81 AC-2 Test-09
def test_tc_spl_81_09_inactive_bookings_and_removed_blocks_do_not_conflict(app, client, requested):
    removed = block(client, requested["venue"], EVENT_DATE, "PM")
    remove_block(client, requested["venue"], removed)
    for status in ("withdrawn", "rejected"):
        seed_booking(app, make_event(app, f"Released {status}"), requested["venue"], status)

    response = approve(client, requested["booking"]["id"], {})

    assert response.status_code == 200, response.json


# TC-SPL-81-10
# SPL-81 AC-2 Test-10
def test_tc_spl_81_10_recheck_uses_recorded_slots(app, client, requested):
    booking_id = requested["booking"]["id"]
    before = occupancy_rows(app, booking_id)
    with Session(app.extensions["engine"]) as session:
        session.execute(
            update(Venue).where(Venue.id == requested["venue"]).values(setup_buffer_slots=0)
        )
        session.commit()

    response = approve(client, booking_id, {})

    assert response.status_code == 200, response.json
    assert occupancy_rows(app, booking_id) == before
    assert {row[1:] for row in before} == HARBOUR_CLAIM


# AC3 — conflict refused, stays Requested, names the Singapore date and slot


# TC-SPL-81-11
# SPL-81 AC-3 Test-11
@pytest.mark.parametrize(
    ("start", "end", "blocked_day", "blocked_slot", "words"),
    [
        (time(13), time(18), EVENT_DATE, "PM", "14 Oct 2026 during PM"),
        # Q123: an AM event's setup is the previous day's Night slot.
        (time(8), time(12), EVENT_DATE - timedelta(days=1), "NIGHT", "13 Oct 2026 during Night"),
    ],
)
def test_tc_spl_81_11_refusal_names_singapore_date_and_slot(
    app, client, start, end, blocked_day, blocked_slot, words
):
    event_id, venue_id = make_event(app, start=start, end=end), add_venue(app)
    created = request_booking(client, event_id, venue_id)
    assert created.status_code == 201, created.json
    block(client, venue_id, blocked_day, blocked_slot)

    response = approve(client, created.json["booking"]["id"], {})

    assert response.status_code == 409
    assert response.json["error"] == f"Harbour Hall is unavailable on {words}."
    assert response.json["conflict"] == {"date": blocked_day.isoformat(), "slot": blocked_slot}


# AC4 — Approved, with approver, time and optional note


# TC-SPL-81-13
# SPL-81 AC-4 Test-13
def test_tc_spl_81_13_approval_records_actor_time_and_note(app, client, requested):
    booking_id = requested["booking"]["id"]
    before = stored(app, booking_id)
    started = datetime.now(SINGAPORE)

    response = approve(client, booking_id, {"note": NOTE})

    finished = datetime.now(SINGAPORE)
    assert response.status_code == 200, response.json
    booking = response.json["booking"]
    assert booking["approved_by"] == {"id": VENUE_STAFF, "name": "Valerie Tan"}
    assert booking["approval_note"] == NOTE
    approved_at = datetime.fromisoformat(booking["approved_at"])
    assert approved_at.utcoffset() == timedelta(hours=8)
    assert started - timedelta(seconds=1) <= approved_at <= finished + timedelta(seconds=1)
    row = stored(app, booking_id)
    assert row["approved_by_account_id"] == VENUE_STAFF
    assert row["approval_note"] == NOTE
    assert row["approved_at"] is not None
    for column in REQUEST_COLUMNS:
        assert row[column] == before[column], column
    status = client.get(
        f"/api/event-requests/{requested['event']}/venue-booking-status",
        headers=headers("coordinator"),
    ).json
    assert status["current_status"] == {"status": "approved", "label": "Approved"}
    assert [
        (entry["status"], entry["actor"]["name"], entry["note"]) for entry in status["history"]
    ] == [
        ("requested", "Casey Lim", None),
        ("approved", "Valerie Tan", NOTE),
    ]


# TC-SPL-81-14
# SPL-81 AC-4 Test-14
@pytest.mark.parametrize(
    ("kwargs", "stored_note"),
    [
        ({}, None),
        ({"json": {}}, None),
        ({"json": {"note": None}}, None),
        ({"json": {"note": "   "}}, None),
        ({"json": {"note": "x" * 1000}}, "x" * 1000),
        ({"json": {"note": f"  {NOTE}  "}}, NOTE),
    ],
)
def test_tc_spl_81_14_note_is_optional_and_bounded(app, client, requested, kwargs, stored_note):
    booking_id = requested["booking"]["id"]

    response = approve(client, booking_id, **kwargs)

    assert response.status_code == 200, response.json
    assert stored(app, booking_id)["approval_note"] == stored_note


# TC-SPL-81-14
# SPL-81 AC-4 Test-14
@pytest.mark.parametrize(
    "body",
    [
        {"note": "x" * 1001},
        {"note": 5},
        {"status": "approved"},
        {"approved_by_account_id": VENUE_STAFF},
        {"booking_date": "2026-10-15"},
        {"requires_review": False},
        {"note": NOTE, "layout": "boardroom"},
        ["note"],
    ],
)
def test_tc_spl_81_14_nothing_else_can_be_supplied(app, client, requested, body):
    booking_id = requested["booking"]["id"]
    before = snapshot(app, booking_id)

    response = approve(client, booking_id, body)

    assert response.status_code == 400
    assert snapshot(app, booking_id) == before


# AC5 — slots stay occupied after approval


# TC-SPL-81-15
# SPL-81 AC-5 Test-15
def test_tc_spl_81_15_approved_slots_stay_occupied(app, client, requested):
    assert approve(client, requested["booking"]["id"], {}).status_code == 200
    other = make_event(app, "Harbour Talk")

    for slot in ("AM", "PM", "NIGHT"):
        found = client.get(
            f"/api/event-requests/{other}/available-venues?date={EVENT_DATE.isoformat()}&slot={slot}",
            headers=headers("coordinator"),
        )
        assert found.status_code == 200, found.json
        assert "Harbour Hall" not in {venue["name"] for venue in found.json["venues"]}, slot
    refused = request_booking(client, other, requested["venue"])
    assert refused.status_code == 409
    assert refused.json["conflict"]["date"] == EVENT_DATE.isoformat()


# TC-SPL-81-16
# SPL-81 AC-5 Test-16
def test_tc_spl_81_16_occupancy_rows_are_kept_as_they_were(app, client, requested):
    booking_id = requested["booking"]["id"]
    before = occupancy_rows(app, booking_id)

    assert approve(client, booking_id, {}).status_code == 200

    assert occupancy_rows(app, booking_id) == before
    assert {row[1:] for row in before} == HARBOUR_CLAIM


# AC6 — a refused approval changes nothing


# TC-SPL-81-17
# SPL-81 AC-6 Test-17
@pytest.mark.parametrize(
    "refusal",
    [
        "wrong-role",
        "no-session",
        "event-not-planning",
        "operational-block",
        "booking-conflict",
        "invalid-note",
        "unknown-field",
    ],
)
def test_tc_spl_81_17_refusals_change_nothing(app, client, requested, refusal):
    booking_id = requested["booking"]["id"]
    token, body = "venue-staff", {"note": NOTE}
    if refusal == "wrong-role":
        token = "coordinator"
    elif refusal == "no-session":
        token = None
    elif refusal == "event-not-planning":
        set_event_status(app, requested["event"], "cancelled")
    elif refusal == "operational-block":
        block(client, requested["venue"], EVENT_DATE, "PM")
    elif refusal == "booking-conflict":
        other = seed_booking(app, make_event(app, "Harbour Talk"), requested["venue"], "approved")
        reassign_slot(app, booking_id, "AM", other)
    elif refusal == "invalid-note":
        body = {"note": "x" * 1001}
    else:
        body = {"note": NOTE, "status": "approved"}
    before = snapshot(app, booking_id)

    response = approve(client, booking_id, body, token=token)

    assert not 200 <= response.status_code < 300
    assert snapshot(app, booking_id) == before


# TC-SPL-81-18
# SPL-81 AC-6 Test-18
def test_tc_spl_81_18_conflict_rolls_back_status_and_audit_together(app, client, requested):
    booking_id = requested["booking"]["id"]
    blocked = block(client, requested["venue"], EVENT_DATE, "NIGHT")

    assert approve(client, booking_id, {"note": "First attempt"}).status_code == 409
    assert_still_requested(app, booking_id)
    assert [entry[0] for entry in history(app, booking_id)] == ["request"]

    remove_block(client, requested["venue"], blocked)
    assert approve(client, booking_id, {"note": NOTE}).status_code == 200

    assert stored(app, booking_id)["approval_note"] == NOTE
    assert [(entry[0], entry[3]) for entry in history(app, booking_id)] == [
        ("request", None),
        ("approve", NOTE),
    ]


# Assumptions — reading for review, and requests marked for review


# TC-SPL-81-21
# SPL-81 AC-1 Test-21
def test_tc_spl_81_21_venue_staff_read_a_request_for_review(app, client, requested):
    booking_id = requested["booking"]["id"]
    before = snapshot(app, booking_id)

    response = review(client, booking_id)

    assert response.status_code == 200, response.json
    body = response.json
    # SPL-80 (CS-E10-S2 AC3) widened this payload with the fields Venue Staff need to decide.
    # The widening is additive, so this case still asserts every key SPL-81 relies on, and
    # TC-SPL-80-11 guards the same three values from SPL-80's side.
    assert {key: body["event"][key] for key in ("id", "name", "status")} == {
        "id": requested["event"],
        "name": "Coastal Forum",
        "status": "planning",
    }
    booking = body["booking"]
    assert booking["venue"] == {"id": requested["venue"], "name": "Harbour Hall"}
    assert (booking["date"], booking["event_slots"], booking["layout"]) == (
        "2026-10-14",
        ["PM"],
        "theatre",
    )
    assert booking["setup"] == {"date": "2026-10-14", "slot": "AM"}
    assert booking["turnaround"] == {"date": "2026-10-14", "slot": "NIGHT"}
    assert booking["expected_attendance"] == 150
    assert booking["requested_by"] == {"id": COORDINATOR, "name": "Casey Lim"}
    assert booking["requested_at"] == requested["booking"]["requested_at"]
    assert booking["status"] == "requested"
    assert body["review"] == {"requires_review": False, "marked_at": None, "trigger_block": None}
    assert snapshot(app, booking_id) == before


# TC-SPL-81-21
# SPL-81 AC-1 Test-21
@pytest.mark.parametrize(
    ("token", "booking", "expected"),
    [
        ("coordinator", "own", 403),
        ("organiser", "own", 403),
        ("manager", "own", 403),
        (None, "own", 401),
        ("venue-staff", 999999, 404),
        ("venue-staff", 2**31, 404),
    ],
)
def test_tc_spl_81_21_others_cannot_read_a_request_for_review(
    app, client, requested, token, booking, expected
):
    booking_id = requested["booking"]["id"] if booking == "own" else booking

    assert review(client, booking_id, token=token).status_code == expected


# TC-SPL-81-22
# SPL-81 AC-2 Test-22
def test_tc_spl_81_22_review_marker_kept_when_block_removed(app, client, requested):
    booking_id = requested["booking"]["id"]
    blocked = block(client, requested["venue"], EVENT_DATE, "PM")
    marked = stored(app, booking_id)
    assert marked["requires_review"] is True
    shown = review(client, booking_id).json["review"]
    assert shown["requires_review"] is True
    assert shown["trigger_block"]["reason"] == "Ceiling repair"

    refused = approve(client, booking_id, {})
    assert refused.status_code == 409
    assert refused.json["conflict"] == {"date": EVENT_DATE.isoformat(), "slot": "PM"}

    remove_block(client, requested["venue"], blocked)
    response = approve(client, booking_id, {})

    assert response.status_code == 200, response.json
    after = stored(app, booking_id)
    for column in (
        "requires_review",
        "review_trigger_block_id",
        "review_marked_at",
        "review_marked_by_account_id",
    ):
        assert after[column] == marked[column], column
    assert response.json["booking"]["requires_review"] is True
