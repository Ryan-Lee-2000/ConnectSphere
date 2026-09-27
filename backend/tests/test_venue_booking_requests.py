"""Acceptance coverage for SPL-77 (CS-E09-S3): request a venue booking for an approved event.

Each test carries the QA-SPL-77 case identifier it proves. The expected values come from the
story's acceptance criteria and the answered customer questions, not from the implementation.
"""

from datetime import date, datetime, time, timezone

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
    VenueLayout,
    VenueOperationalBlock,
)
from sqlalchemy import func, select
from sqlalchemy.orm import Session

COORDINATOR = "00000000-0000-0000-0000-000000000771"
OTHER_COORDINATOR = "00000000-0000-0000-0000-000000000772"
ORGANISER = "00000000-0000-0000-0000-000000000773"
VENUE_STAFF = "00000000-0000-0000-0000-000000000774"
MANAGER = "00000000-0000-0000-0000-000000000775"
TOKENS = {
    "coordinator": COORDINATOR,
    "other-coordinator": OTHER_COORDINATOR,
    "organiser": ORGANISER,
    "venue-staff": VENUE_STAFF,
    "manager": MANAGER,
}
EVENT_DATE = date(2026, 10, 14)
HARBOUR_LAYOUTS = (("theatre", 200), ("classroom", 120), ("boardroom", 150))
NON_PLANNING_STATUSES = (
    "draft",
    "submitted",
    "under_review",
    "returned_for_clarification",
    "approved",
    "confirmed",
    "completed",
    "cancelled",
    "rejected",
    "withdrawn",
    "postponed",
)


@pytest.fixture
def app(tmp_path):
    app = create_app(
        {
            "TESTING": True,
            "DATABASE_URL": f"sqlite:///{tmp_path}/booking-requests.db",
            "IDENTITY_VERIFIER": TOKENS.__getitem__,
        }
    )
    engine = app.extensions["engine"]
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        organisation = Organisation(name="SPL-77 client")
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


def make_event(
    app,
    name="Coastal Forum",
    *,
    status="planning",
    day=EVENT_DATE,
    start=time(13),
    end=time(18),
    attendance=150,
    preferred_layout=None,
    coordinator=COORDINATOR,
):
    with Session(app.extensions["engine"]) as session:
        event = EventRequest(
            organiser_account_id=ORGANISER,
            organisation_id=app.config["ORGANISATION_ID"],
            name=name,
            purpose="Community planning",
            proposed_date=day,
            start_time=start,
            end_time=end,
            expected_attendance=attendance,
            preferred_room_layout=preferred_layout,
            required_facilities=["Projector"],
            accessibility_needs=["Step-free access"],
            location_preference="Marina Centre",
            status=status,
        )
        session.add(event)
        session.flush()
        session.add(
            EventCoordinatorAssignment(
                event_request_id=event.id,
                coordinator_account_id=coordinator,
                assigned_by_account_id=MANAGER,
                assigned_at=datetime(2026, 9, 20, 9, tzinfo=timezone.utc),
            )
        )
        session.commit()
        return event.id


def add_venue(
    app,
    name="Harbour Hall",
    *,
    slots=("AM", "PM", "NIGHT"),
    setup=1,
    turnaround=1,
    layouts=HARBOUR_LAYOUTS,
    facilities=("Projector", "PA system"),
    accessibility=("Step-free access",),
    location="Level 3, Marina Centre",
):
    with Session(app.extensions["engine"]) as session:
        venue = Venue(
            name=name,
            location=location,
            facilities=list(facilities),
            accessibility_features=list(accessibility),
            operating_slots=list(slots),
            setup_buffer_slots=setup,
            turnaround_buffer_slots=turnaround,
        )
        venue.layouts = [VenueLayout(layout=layout, capacity=size) for layout, size in layouts]
        session.add(venue)
        session.commit()
        return venue.id


def seed_booking(app, event_id, venue_id, status, occupancy=()):
    """Insert a booking directly, as approval or withdrawal (other stories) would leave it."""

    with Session(app.extensions["engine"]) as session:
        booking = VenueBooking(event_request_id=event_id, venue_id=venue_id, status=status)
        session.add(booking)
        session.flush()
        for day, slot, kind in occupancy:
            session.add(
                VenueBookingOccupancy(
                    booking_id=booking.id, venue_id=venue_id, day=day, slot=slot, kind=kind
                )
            )
        session.commit()
        return booking.id


def add_block(app, venue_id, day, slots, *, removed=False):
    with Session(app.extensions["engine"]) as session:
        session.add(
            VenueOperationalBlock(
                venue_id=venue_id,
                start_date=day,
                end_date=day,
                slots=list(slots),
                reason="Maintenance",
                created_by_account_id=VENUE_STAFF,
                created_at=datetime(2026, 9, 25, 9, tzinfo=timezone.utc),
                removed_by_account_id=VENUE_STAFF if removed else None,
                removed_at=datetime(2026, 9, 26, 9, tzinfo=timezone.utc) if removed else None,
            )
        )
        session.commit()


def headers(token="coordinator"):
    return {"Authorization": f"Bearer {token}"} if token else {}


def request_booking(client, event_id, venue_id, layout="theatre", token="coordinator", **extra):
    return client.post(
        f"/api/event-requests/{event_id}/venue-bookings",
        json={"venue_id": venue_id, "layout": layout, **extra},
        headers=headers(token),
    )


def search(client, event_id, day, *slots):
    query = "&".join([f"date={day.isoformat()}", *(f"slot={slot}" for slot in slots)])
    response = client.get(
        f"/api/event-requests/{event_id}/available-venues?{query}", headers=headers()
    )
    assert response.status_code == 200, response.json
    return {venue["name"]: venue for venue in response.json["venues"]}


def count(app, model, *conditions):
    with Session(app.extensions["engine"]) as session:
        return session.scalar(select(func.count()).select_from(model).where(*conditions))


def occupancy(app, venue_id):
    with Session(app.extensions["engine"]) as session:
        return {
            (row.day, row.slot, row.kind)
            for row in session.scalars(
                select(VenueBookingOccupancy).where(VenueBookingOccupancy.venue_id == venue_id)
            )
        }


def nothing_written(app):
    return count(app, VenueBooking) == 0 and count(app, VenueBookingOccupancy) == 0


HARBOUR_PM_CLAIM = {
    (EVENT_DATE, "AM", "setup"),
    (EVENT_DATE, "PM", "event"),
    (EVENT_DATE, "NIGHT", "turnaround"),
}


# AC1 — only the assigned coordinator, only while the event is in Planning


# TC-SPL-77-01
def test_tc_spl_77_01_assigned_coordinator_requests_a_suitable_free_venue(app, client):
    event_id, venue_id = make_event(app), add_venue(app)

    response = request_booking(client, event_id, venue_id)

    assert response.status_code == 201, response.json
    with Session(app.extensions["engine"]) as session:
        bookings = session.scalars(select(VenueBooking)).all()
        assert [(b.event_request_id, b.venue_id, b.status) for b in bookings] == [
            (event_id, venue_id, "requested")
        ]
    assert occupancy(app, venue_id) == HARBOUR_PM_CLAIM


# TC-SPL-77-02
def test_tc_spl_77_02_unassigned_coordinator_is_refused_without_disclosure(app, client):
    event_id, venue_id = make_event(app), add_venue(app)

    not_assigned = request_booking(client, event_id, venue_id, token="other-coordinator")
    missing = request_booking(client, 999999, venue_id, token="other-coordinator")

    assert not_assigned.status_code == missing.status_code == 404
    assert not_assigned.json == missing.json
    assert "Coastal Forum" not in not_assigned.get_data(as_text=True)
    assert "Harbour Hall" not in not_assigned.get_data(as_text=True)
    assert nothing_written(app)


# TC-SPL-77-03
@pytest.mark.parametrize(
    ("token", "expected_status"),
    [("venue-staff", 403), ("organiser", 403), ("manager", 403), (None, 401)],
)
def test_tc_spl_77_03_other_roles_and_no_session_are_refused(app, client, token, expected_status):
    event_id, venue_id = make_event(app), add_venue(app)

    response = request_booking(client, event_id, venue_id, token=token)

    assert response.status_code == expected_status
    assert nothing_written(app)


# TC-SPL-77-04
@pytest.mark.parametrize("status", NON_PLANNING_STATUSES)
def test_tc_spl_77_04_events_outside_planning_are_refused(app, client, status):
    event_id, venue_id = make_event(app, status=status), add_venue(app)

    response = request_booking(client, event_id, venue_id)

    assert response.status_code == 409
    assert "Planning" in response.json["error"]
    assert nothing_written(app)


# AC2 — suitability against the saved event, and the selected layout


# TC-SPL-77-05
def test_tc_spl_77_05_unsuitable_venue_is_refused_naming_each_failed_check(app, client):
    event_id = make_event(app)
    riverside = add_venue(
        app,
        "Riverside Room",
        facilities=("Whiteboard",),
        location="Level 1, Marina Centre",
    )
    skyline = add_venue(
        app, "Skyline Terrace", facilities=(), accessibility=(), location="Rooftop, Harbour Point"
    )

    one_failure = request_booking(client, event_id, riverside)
    three_failures = request_booking(client, event_id, skyline)

    assert one_failure.status_code == three_failures.status_code == 409
    assert one_failure.json["failed_checks"] == ["Required facilities"]
    assert three_failures.json["failed_checks"] == [
        "Required facilities",
        "Accessibility needs",
        "Preferred location",
    ]
    assert "Required facilities" in one_failure.json["error"]
    assert nothing_written(app)


# TC-SPL-77-06
def test_tc_spl_77_06_venue_unable_to_host_timing_or_preparation_is_refused(app, client):
    event_id = make_event(app)
    morning_annex = add_venue(app, "Morning Annex", slots=("AM",), setup=0, turnaround=0)
    day_hall = add_venue(app, "Day Hall", slots=("AM", "PM"), setup=0, turnaround=1)

    for venue_id in (morning_annex, day_hall):
        response = request_booking(client, event_id, venue_id)
        assert response.status_code == 409
        assert response.json["failed_checks"] == ["Timing and preparation"]
    assert nothing_written(app)


# TC-SPL-77-07
@pytest.mark.parametrize(
    ("layout", "expected_status", "stored_layout"),
    [
        ("boardroom", 201, "boardroom"),  # capacity 150 == expected attendance 150
        ("classroom", 409, None),  # capacity 120 < 150
        ("banquet", 409, None),  # not a layout Harbour Hall supports
        ("Theatre", 201, "theatre"),  # the supported layout, named in another case
    ],
)
def test_tc_spl_77_07_selected_layout_capacity_boundary(
    app, client, layout, expected_status, stored_layout
):
    event_id, venue_id = make_event(app), add_venue(app)

    response = request_booking(client, event_id, venue_id, layout=layout)

    assert response.status_code == expected_status, response.json
    if expected_status == 201:
        assert response.json["booking"]["layout"] == stored_layout
    else:
        assert response.json["failed_checks"] == ["Layout and capacity"]
        assert nothing_written(app)


# TC-SPL-77-07 — SPL-77 assumption: the booked layout may differ from the preferred layout.
def test_tc_spl_77_07_selected_layout_may_differ_from_the_preferred_layout(app, client):
    event_id = make_event(app, preferred_layout="theatre")
    venue_id = add_venue(app)

    response = request_booking(client, event_id, venue_id, layout="boardroom")

    assert response.status_code == 201, response.json
    assert response.json["booking"]["layout"] == "boardroom"


# AC3 — setup and turnaround are derived from the venue, never supplied


# TC-SPL-77-08
def test_tc_spl_77_08_pm_event_derives_same_day_setup_and_turnaround(app, client):
    event_id, venue_id = make_event(app), add_venue(app)

    booking = request_booking(client, event_id, venue_id).json["booking"]

    assert booking["setup"] == {"date": "2026-10-14", "slot": "AM"}
    assert booking["event_slots"] == ["PM"]
    assert booking["turnaround"] == {"date": "2026-10-14", "slot": "NIGHT"}
    assert occupancy(app, venue_id) == HARBOUR_PM_CLAIM


# TC-SPL-77-09
@pytest.mark.parametrize(
    ("start", "end", "venue", "expected"),
    [
        (
            time(7),
            time(12),
            "Harbour Hall",
            {
                (date(2026, 10, 13), "NIGHT", "setup"),
                (EVENT_DATE, "AM", "event"),
                (EVENT_DATE, "PM", "turnaround"),
            },
        ),
        (
            time(19),
            time(23),
            "Harbour Hall",
            {
                (EVENT_DATE, "PM", "setup"),
                (EVENT_DATE, "NIGHT", "event"),
                (date(2026, 10, 15), "AM", "turnaround"),
            },
        ),
        (time(13), time(18), "Plain Room", {(EVENT_DATE, "PM", "event")}),
    ],
)
def test_tc_spl_77_09_preparation_crosses_days_or_is_absent(
    app, client, start, end, venue, expected
):
    event_id = make_event(app, start=start, end=end)
    preparation = 1 if venue == "Harbour Hall" else 0
    venue_id = add_venue(app, venue, setup=preparation, turnaround=preparation)

    response = request_booking(client, event_id, venue_id)

    assert response.status_code == 201, response.json
    assert occupancy(app, venue_id) == expected


# TC-SPL-77-10
@pytest.mark.parametrize(
    "forged",
    [
        {"setup_slot": "PM"},
        {"turnaround_slot": "AM"},
        {"slots": ["NIGHT"]},
        {"date": "2026-10-20"},
        {"expected_attendance": 10},
    ],
)
def test_tc_spl_77_10_client_supplied_date_or_slots_are_refused(app, client, forged):
    event_id, venue_id = make_event(app), add_venue(app)

    response = request_booking(client, event_id, venue_id, **forged)

    assert response.status_code == 400
    assert nothing_written(app)


# AC4 — at most one active booking per event


# TC-SPL-77-11
@pytest.mark.parametrize("active_status", ["requested", "approved"])
def test_tc_spl_77_11_second_request_refused_while_one_is_active(app, client, active_status):
    event_id = make_event(app)
    harbour = add_venue(app)
    east = add_venue(app, "Harbour Hall East")
    seed_booking(
        app,
        event_id,
        harbour,
        active_status,
        occupancy=[(EVENT_DATE, slot, kind) for _, slot, kind in HARBOUR_PM_CLAIM],
    )

    response = request_booking(client, event_id, east)

    assert response.status_code == 409
    assert "already has an active venue-booking request" in response.json["error"]
    assert count(app, VenueBooking, VenueBooking.event_request_id == event_id) == 1
    assert occupancy(app, east) == set()


# TC-SPL-77-12
@pytest.mark.parametrize("inactive_status", ["withdrawn", "rejected", "cancelled"])
def test_tc_spl_77_12_inactive_earlier_booking_does_not_block(app, client, inactive_status):
    event_id, venue_id = make_event(app), add_venue(app)
    earlier = seed_booking(app, event_id, venue_id, inactive_status)

    response = request_booking(client, event_id, venue_id)

    assert response.status_code == 201, response.json
    with Session(app.extensions["engine"]) as session:
        statuses = dict(
            session.execute(
                select(VenueBooking.id, VenueBooking.status).where(
                    VenueBooking.event_request_id == event_id
                )
            ).all()
        )
    assert statuses[earlier] == inactive_status
    assert sorted(statuses.values()) == sorted([inactive_status, "requested"])
    assert occupancy(app, venue_id) == HARBOUR_PM_CLAIM


# AC5 — every slot is checked; a conflict writes nothing and names the earliest slot


# TC-SPL-77-14
def test_tc_spl_77_14_event_slot_conflict_is_refused_and_named(app, client):
    venue_id = add_venue(app)
    harbour_talk = make_event(app, "Harbour Talk")
    coastal_forum = make_event(app)
    assert request_booking(client, harbour_talk, venue_id).status_code == 201

    response = request_booking(client, coastal_forum, venue_id)

    assert response.status_code == 409
    assert response.json["error"] == "Venue is unavailable on 2026-10-14 during AM."
    assert response.json["conflict"] == {"date": "2026-10-14", "slot": "AM"}
    assert count(app, VenueBooking, VenueBooking.event_request_id == coastal_forum) == 0
    assert occupancy(app, venue_id) == HARBOUR_PM_CLAIM


# TC-SPL-77-15
@pytest.mark.parametrize("conflict", ["setup-block", "turnaround-booking"])
def test_tc_spl_77_15_preparation_slot_conflict_refuses_atomically(app, client, conflict):
    event_id, venue_id = make_event(app), add_venue(app)
    if conflict == "setup-block":
        add_block(app, venue_id, EVENT_DATE, ["AM"])
        expected_slot, left_behind = "AM", set()
    else:
        other_event = make_event(app, "Evening Recital", start=time(19), end=time(23))
        seed_booking(
            app, other_event, venue_id, "requested", occupancy=[(EVENT_DATE, "NIGHT", "event")]
        )
        expected_slot, left_behind = "NIGHT", {(EVENT_DATE, "NIGHT", "event")}

    response = request_booking(client, event_id, venue_id)

    assert response.status_code == 409
    assert response.json["conflict"] == {"date": "2026-10-14", "slot": expected_slot}
    assert count(app, VenueBooking, VenueBooking.event_request_id == event_id) == 0
    assert occupancy(app, venue_id) == left_behind


# TC-SPL-77-16
def test_tc_spl_77_16_earliest_conflict_is_reported(app, client):
    event_id = make_event(app, start=time(7), end=time(12))
    venue_id = add_venue(app)
    add_block(app, venue_id, EVENT_DATE, ["PM"])
    add_block(app, venue_id, date(2026, 10, 13), ["NIGHT"])

    response = request_booking(client, event_id, venue_id)

    assert response.status_code == 409
    assert response.json["conflict"] == {"date": "2026-10-13", "slot": "NIGHT"}
    assert nothing_written(app)


# TC-SPL-77-17
@pytest.mark.parametrize(
    "situation",
    ["removed-block", "other-venue-booking", "non-adjacent-booking", "next-day-block"],
)
def test_tc_spl_77_17_non_conflicting_occupancy_does_not_block(app, client, situation):
    event_id, venue_id = make_event(app), add_venue(app)
    other_event = make_event(app, "Neighbour Event")
    if situation == "removed-block":
        add_block(app, venue_id, EVENT_DATE, ["PM"], removed=True)
    elif situation == "other-venue-booking":
        other_venue = add_venue(app, "Other Hall")
        seed_booking(
            app, other_event, other_venue, "requested", occupancy=[(EVENT_DATE, "PM", "event")]
        )
    elif situation == "non-adjacent-booking":
        seed_booking(
            app,
            other_event,
            venue_id,
            "requested",
            occupancy=[(date(2026, 10, 16), "PM", "event")],
        )
    else:
        add_block(app, venue_id, date(2026, 10, 15), ["PM"])

    response = request_booking(client, event_id, venue_id)

    assert response.status_code == 201, response.json
    booking_id = response.json["booking"]["id"]
    assert count(app, VenueBookingOccupancy, VenueBookingOccupancy.booking_id == booking_id) == 3


# AC6 — a Requested booking recording every field from trusted sources


# TC-SPL-77-19
def test_tc_spl_77_19_created_booking_records_every_field(app, client):
    event_id, venue_id = make_event(app), add_venue(app)
    before = datetime.now(SINGAPORE)

    response = request_booking(client, event_id, venue_id)

    after = datetime.now(SINGAPORE)
    assert response.status_code == 201, response.json
    booking = response.json["booking"]
    assert booking["event_request_id"] == event_id
    assert booking["venue"] == {"id": venue_id, "name": "Harbour Hall"}
    assert booking["date"] == "2026-10-14"
    assert booking["event_slots"] == ["PM"]
    assert booking["setup"] == {"date": "2026-10-14", "slot": "AM"}
    assert booking["turnaround"] == {"date": "2026-10-14", "slot": "NIGHT"}
    assert booking["layout"] == "theatre"
    assert booking["expected_attendance"] == 150
    assert booking["status"] == "requested"
    assert booking["requested_by"] == {"id": COORDINATOR, "name": "Casey Lim"}
    assert booking["requested_at"].endswith("+08:00")
    assert before <= datetime.fromisoformat(booking["requested_at"]) <= after
    assert booking["requires_review"] is False
    assert booking["review_trigger_block_id"] is None
    assert booking["review_marked_at"] is None

    with Session(app.extensions["engine"]) as session:
        stored = session.get(VenueBooking, booking["id"])
        assert stored.status == "requested"
        assert stored.layout == "theatre"
        assert stored.booking_date == EVENT_DATE
        assert stored.event_slots == ["PM"]
        assert (stored.setup_date, stored.setup_slot) == (EVENT_DATE, "AM")
        assert (stored.turnaround_date, stored.turnaround_slot) == (EVENT_DATE, "NIGHT")
        assert stored.expected_attendance == 150
        assert stored.requested_by_account_id == COORDINATOR
        assert stored.requested_at is not None


# TC-SPL-77-20
@pytest.mark.parametrize(
    "forged",
    [
        {"status": "approved"},
        {"requested_by_account_id": OTHER_COORDINATOR},
        {"event_request_id": 12345},
        {"requires_review": True},
        {"organisation_id": 1},
    ],
)
def test_tc_spl_77_20_forged_identity_status_or_review_fields_are_refused(app, client, forged):
    event_id, venue_id = make_event(app), add_venue(app)

    response = request_booking(client, event_id, venue_id, **forged)

    assert response.status_code == 400
    assert nothing_written(app)


# AC7 — a Requested booking's slots count as occupied


# TC-SPL-77-21
def test_tc_spl_77_21_requested_slots_leave_venue_search(app, client):
    coastal_forum = make_event(app)
    harbour_talk = make_event(app, "Harbour Talk")
    venue_id = add_venue(app)
    before_pm = search(client, harbour_talk, EVENT_DATE, "PM")
    before_am = search(client, harbour_talk, EVENT_DATE, "AM")
    assert "Harbour Hall" in before_pm and "Harbour Hall" in before_am

    assert request_booking(client, coastal_forum, venue_id).status_code == 201

    assert "Harbour Hall" not in search(client, harbour_talk, EVENT_DATE, "PM")
    assert "Harbour Hall" not in search(client, harbour_talk, EVENT_DATE, "AM")


# TC-SPL-77-22
def test_tc_spl_77_22_unheld_slots_stay_available(app, client):
    coastal_forum = make_event(app)
    harbour_talk = make_event(app, "Harbour Talk", start=time(7), end=time(12))
    plain_room = add_venue(app, "Plain Room", setup=0, turnaround=0)
    assert request_booking(client, coastal_forum, plain_room).status_code == 201

    assert "Plain Room" in search(client, harbour_talk, EVENT_DATE, "AM")
    assert "Plain Room" in search(client, harbour_talk, EVENT_DATE, "NIGHT")
    assert "Plain Room" in search(client, harbour_talk, date(2026, 10, 15), "PM")
    assert request_booking(client, harbour_talk, plain_room).status_code == 201


# TC-SPL-77-02 — boundary partitions: an out-of-range event id, and an unknown venue.
def test_tc_spl_77_02_out_of_range_event_and_unknown_venue_are_not_found(app, client):
    event_id, venue_id = make_event(app), add_venue(app)
    unassigned = request_booking(client, event_id, venue_id, token="other-coordinator")

    out_of_range = request_booking(client, 2**31, venue_id)
    unknown_venue = request_booking(client, event_id, 999999)

    assert out_of_range.status_code == 404
    assert out_of_range.json == unassigned.json
    assert unknown_venue.status_code == 404
    assert unknown_venue.json == {"error": "Venue not found."}
    assert nothing_written(app)


# TC-SPL-77-06 — boundary partition: a Planning event with no recorded time cannot be assessed.
def test_tc_spl_77_06_event_without_a_recorded_time_fails_timing(app, client):
    event_id = make_event(app, start=None, end=None)
    venue_id = add_venue(app)

    response = request_booking(client, event_id, venue_id)

    assert response.status_code == 409
    assert response.json["failed_checks"] == ["Timing and preparation"]
    assert nothing_written(app)


# TC-SPL-77-20 — malformed partitions: only a positive venue id and a short, non-blank layout.
@pytest.mark.parametrize(
    "body",
    [
        {"venue_id": "1", "layout": "theatre"},
        {"venue_id": True, "layout": "theatre"},
        {"venue_id": 0, "layout": "theatre"},
        {"venue_id": 1, "layout": "   "},
        {"venue_id": 1, "layout": 7},
        {"venue_id": 1, "layout": "x" * 101},
        {"venue_id": 1},
        ["not", "an", "object"],
    ],
)
def test_tc_spl_77_20_malformed_requests_are_refused(app, client, body):
    event_id = make_event(app)
    add_venue(app)

    response = client.post(
        f"/api/event-requests/{event_id}/venue-bookings", json=body, headers=headers()
    )

    assert response.status_code == 400
    assert nothing_written(app)
