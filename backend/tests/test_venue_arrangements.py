"""Acceptance coverage for SPL-131: several independent venue bookings for one event.

Each test carries the QA-SPL-131 case identifier it proves (BB = black-box, WB = white-box).
Expected values come from the Jira acceptance criteria and the client answers (Week 7 change 3,
Q109, Q119, Q131, Q110, Q60), not from the implementation. Concurrency and the migration are
proved on PostgreSQL in test_venue_arrangements_postgres.py.
"""

from datetime import date, datetime, time, timezone

import pytest
import test_venue_booking_requests as base
from app.models import (
    EventCoordinatorAssignment,
    EventRequest,
    Venue,
    VenueBooking,
    VenueBookingOccupancy,
    VenueBookingStatusHistory,
    VenueOperationalBlock,
)
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_venue_booking_requests import (
    COORDINATOR,
    EVENT_DATE,
    NON_PLANNING_STATUSES,
    OTHER_COORDINATOR,
    add_venue,
    count,
    headers,
    make_event,
    occupancy,
    request_booking,
    seed_booking,
)

app = base.app
client = base.client

BREAKOUT_LAYOUTS = (("classroom", 30), ("boardroom", 12))


# Helpers ------------------------------------------------------------------------------------


def breakout(app, name="Breakout Room", **overrides):
    """A small room: classroom for 30, no PA system, same location and access as the hall."""

    options = {"layouts": BREAKOUT_LAYOUTS, "facilities": ("Projector",), "setup": 0}
    options.update(overrides)
    return add_venue(app, name, turnaround=0, **options)


def exact(app):
    app.config["EXACT_VENUE_TIMING_ENABLED"] = True


def exact_venue(app, name="Harbour Hall", *, setup=30, turnaround=45, **options):
    venue_id = add_venue(app, name, **options)
    with Session(app.extensions["engine"]) as session:
        venue = session.get(Venue, venue_id)
        venue.setup_minutes = setup
        venue.turnaround_minutes = turnaround
        venue.operating_intervals = [[0, 1440]]
        venue.timing_revision = 1
        session.commit()
    return venue_id


def exact_request(client, event_id, venue_id, start="10:00", end="12:00", **extra):
    body = {"date": EVENT_DATE.isoformat(), "start_time": start, "end_time": end}
    return request_booking(
        client, event_id, venue_id, venue_revision=1, **{"layout": "theatre", **body, **extra}
    )


def booking_row(app, booking_id):
    with Session(app.extensions["engine"]) as session:
        booking = session.get(VenueBooking, booking_id)
        return {
            column.key: getattr(booking, column.key) for column in VenueBooking.__mapper__.columns
        }


def history(app, booking_id):
    with Session(app.extensions["engine"]) as session:
        return session.scalars(
            select(VenueBookingStatusHistory)
            .where(VenueBookingStatusHistory.booking_id == booking_id)
            .order_by(VenueBookingStatusHistory.id)
        ).all()


def claims(app, booking_id):
    with Session(app.extensions["engine"]) as session:
        return {
            (row.day, row.slot, row.kind)
            for row in session.scalars(
                select(VenueBookingOccupancy).where(VenueBookingOccupancy.booking_id == booking_id)
            )
        }


def approve(client, booking_id):
    return client.post(
        f"/api/venue-bookings/{booking_id}/approve", json={}, headers=headers("venue-staff")
    )


def cancel(
    client,
    event_id,
    booking_id,
    reason="Plenary moved to the auditorium.",
    token="coordinator",
    body=None,
):
    return client.post(
        f"/api/event-requests/{event_id}/venue-bookings/{booking_id}/cancel",
        json={"reason": reason} if body is None else body,
        headers=headers(token),
    )


def status(client, event_id, token="coordinator"):
    return client.get(
        f"/api/event-requests/{event_id}/venue-booking-status", headers=headers(token)
    )


def set_event(app, event_id, **values):
    with Session(app.extensions["engine"]) as session:
        event = session.get(EventRequest, event_id)
        for key, value in values.items():
            setattr(event, key, value)
        session.commit()


def two_venue_event(app, client, *, approve_first=False):
    """Coastal Forum (150) with the hall Requested (or Approved) and a breakout for 20."""

    event_id = make_event(app)
    hall, room = add_venue(app), breakout(app)
    first = request_booking(client, event_id, hall)
    assert first.status_code == 201, first.json
    if approve_first:
        assert approve(client, first.json["booking"]["id"]).status_code == 200
    second = request_booking(client, event_id, room, layout="classroom", attendee_count=20)
    assert second.status_code == 201, second.json
    return event_id, hall, room, first.json["booking"]["id"], second.json["booking"]["id"]


# AC1 - adding another venue ------------------------------------------------------------------


# TC-SPL-131-01 (BB) AC1: a second venue while the first is Requested
def test_tc_spl_131_01_second_venue_while_first_requested(app, client):
    event_id, hall = make_event(app), add_venue(app)
    first = request_booking(client, event_id, hall).json["booking"]
    before = booking_row(app, first["id"])

    second = request_booking(client, event_id, breakout(app), layout="classroom", attendee_count=20)

    assert second.status_code == 201, second.json
    assert second.json["booking"]["event_request_id"] == event_id
    assert second.json["booking"]["id"] != first["id"]
    assert booking_row(app, first["id"]) == before
    assert count(app, VenueBooking, VenueBooking.event_request_id == event_id) == 2


# TC-SPL-131-02 (BB) AC1: a second venue while the first is Approved
def test_tc_spl_131_02_second_venue_while_first_approved(app, client):
    event_id, hall = make_event(app), add_venue(app)
    first = request_booking(client, event_id, hall).json["booking"]
    assert approve(client, first["id"]).status_code == 200
    before, held = booking_row(app, first["id"]), claims(app, first["id"])

    second = request_booking(client, event_id, breakout(app), layout="classroom", attendee_count=20)

    assert second.status_code == 201, second.json
    assert booking_row(app, first["id"]) == before
    assert claims(app, first["id"]) == held


# TC-SPL-131-03 (BB) AC1/AC10: requesting is refused outside Planning
@pytest.mark.parametrize("event_status", NON_PLANNING_STATUSES)
def test_tc_spl_131_03_no_request_outside_planning(app, client, event_status):
    event_id = make_event(app, status=event_status)

    response = request_booking(client, event_id, add_venue(app))

    assert response.status_code == 409
    assert "Planning" in response.json["error"]
    assert count(app, VenueBooking) == 0


# TC-SPL-131-04 (BB) AC1 boundary: three and four bookings, each independent
def test_tc_spl_131_04_several_venues(app, client):
    event_id = make_event(app)
    rooms = [add_venue(app)] + [breakout(app, f"Breakout {n}") for n in range(1, 4)]

    ids = []
    for index, room in enumerate(rooms):
        extra = {} if index == 0 else {"layout": "classroom", "attendee_count": 25}
        response = request_booking(client, event_id, room, **extra)
        assert response.status_code == 201, response.json
        ids.append(response.json["booking"]["id"])

    assert len(set(ids)) == 4
    assert [item["booking"]["id"] for item in status(client, event_id).json["bookings"]] == ids


# TC-SPL-131-05 (BB) AC1 in 15-minute mode: a second exact booking at another venue
def test_tc_spl_131_05_second_exact_booking(app, client):
    exact(app)
    event_id = make_event(app, start=time(10), end=time(12))
    hall, room = exact_venue(app), exact_venue(app, "Studio One", layouts=BREAKOUT_LAYOUTS)

    assert exact_request(client, event_id, hall).status_code == 201
    second = exact_request(client, event_id, room, layout="classroom", attendee_count=20)

    assert second.status_code == 201, second.json
    assert second.json["booking"]["timing"]["event"]["start"] == "2026-10-14T10:00:00+08:00"


# AC2 - what each booking records -------------------------------------------------------------


# TC-SPL-131-06 (BB) AC2: omitted values default to the event's attendance and facilities
def test_tc_spl_131_06_defaults_come_from_the_event(app, client):
    event_id = make_event(app, attendance=150)

    booking = request_booking(client, event_id, add_venue(app)).json["booking"]

    assert booking["expected_attendance"] == 150
    assert booking["required_facilities"] == ["Projector"]
    assert booking_row(app, booking["id"])["required_facilities"] == ["Projector"]


# TC-SPL-131-07 (BB) AC2 boundary: the attendee count is 1..event attendance, a whole number
@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (1, 201),
        (150, 201),
        (151, 400),
        (0, 400),
        (-5, 400),
        (True, 400),
        ("20", 400),
        (20.5, 400),
        (None, 400),
    ],
)
def test_tc_spl_131_07_attendee_count_boundaries(app, client, value, expected):
    event_id = make_event(app, attendance=150)

    response = request_booking(client, event_id, add_venue(app), attendee_count=value)

    assert response.status_code == expected, response.json
    if expected == 201:
        assert response.json["booking"]["expected_attendance"] == value
    else:
        assert count(app, VenueBooking) == 0


# TC-SPL-131-08 (BB) AC2: facilities are validated, trimmed and de-duplicated
@pytest.mark.parametrize(
    "value",
    ["Projector", [""], ["  "], [3], [None], ["x"] * 0 + [f"F{n}" for n in range(31)], ["x" * 101]],
)
def test_tc_spl_131_08_facilities_rejected(app, client, value):
    event_id = make_event(app)

    response = request_booking(client, event_id, add_venue(app), required_facilities=value)

    assert response.status_code == 400, response.json
    assert count(app, VenueBooking) == 0


def test_tc_spl_131_08_facilities_trimmed_and_unique(app, client):
    event_id = make_event(app)
    venue = add_venue(app, facilities=("Projector", "PA system"))

    response = request_booking(
        client, event_id, venue, required_facilities=[" PA system ", "pa SYSTEM", "Projector"]
    )

    assert response.status_code == 201, response.json
    assert response.json["booking"]["required_facilities"] == ["PA system", "Projector"]


def test_tc_spl_131_08_empty_facilities_and_limits_accepted(app, client):
    event_id = make_event(app)
    many = add_venue(app, facilities=tuple(f"F{n}" for n in range(30)))

    assert (
        request_booking(
            client, event_id, add_venue(app, "Bare Hall", facilities=()), required_facilities=[]
        ).status_code
        == 201
    )
    response = request_booking(
        client, event_id, many, required_facilities=[f"F{n}" for n in range(30)]
    )
    assert response.status_code == 201, response.json


# TC-SPL-131-09 (BB) AC2 15-minute mode: own times inside the saved event
@pytest.mark.parametrize(
    ("start", "end", "expected"),
    [
        ("10:30", "11:30", 201),  # inside
        ("10:00", "10:15", 201),  # one quarter-hour at the start boundary
        ("11:45", "12:00", 201),  # one quarter-hour at the end boundary
        ("09:45", "11:00", 409),  # starts before the event
        ("11:00", "12:15", 409),  # ends after the event
        ("10:10", "11:00", 400),  # not on a 15-minute boundary
        ("11:00", "11:00", 400),  # zero length
    ],
)
def test_tc_spl_131_09_own_times_within_event(app, client, start, end, expected):
    exact(app)
    event_id = make_event(app, start=time(10), end=time(12))

    response = exact_request(client, event_id, exact_venue(app), start, end)

    assert response.status_code == expected, response.json
    if expected == 201:
        assert response.json["booking"]["timing"]["event"]["start"].endswith(f"T{start}:00+08:00")
    else:
        assert count(app, VenueBooking) == 0


def test_tc_spl_131_09_other_date_refused(app, client):
    exact(app)
    event_id = make_event(app, start=time(10), end=time(12))

    response = exact_request(client, event_id, exact_venue(app), date="2026-10-15")

    assert response.status_code == 409
    assert "saved event" in response.json["error"]


# TC-SPL-131-10 (BB) AC2: setup and turnaround may extend outside the event's times
def test_tc_spl_131_10_preparation_extends_outside_event(app, client):
    exact(app)
    event_id = make_event(app, start=time(10), end=time(12))

    booking = exact_request(client, event_id, exact_venue(app)).json["booking"]

    assert booking["timing"]["event"] == {
        "start": "2026-10-14T10:00:00+08:00",
        "end": "2026-10-14T12:00:00+08:00",
    }
    assert booking["timing"]["occupied"] == {
        "start": "2026-10-14T09:30:00+08:00",
        "end": "2026-10-14T12:45:00+08:00",
    }


# TC-SPL-131-11 (BB) AC2: the preferred layout is a default, not a restriction
@pytest.mark.parametrize("mode", ["slots", "exact"])
def test_tc_spl_131_11_layout_may_differ_from_preference(app, client, mode):
    event_id = make_event(app, start=time(10), end=time(12), preferred_layout="theatre")
    if mode == "exact":
        exact(app)
        response = exact_request(
            client, event_id, exact_venue(app), layout="classroom", attendee_count=100
        )
    else:
        response = request_booking(
            client, event_id, add_venue(app), layout="classroom", attendee_count=100
        )

    assert response.status_code == 201, response.json
    assert response.json["booking"]["layout"] == "classroom"


# TC-SPL-131-12 (BB) AC2/AC10: identity, status and timing stay server-owned
@pytest.mark.parametrize(
    "extra",
    [
        {"status": "approved"},
        {"requested_by_account_id": OTHER_COORDINATOR},
        {"expected_attendance": 10},
        {"event_slots": ["AM"]},
        {"organisation_id": 99},
    ],
)
def test_tc_spl_131_12_unknown_fields_refused(app, client, extra):
    event_id = make_event(app)

    response = request_booking(client, event_id, add_venue(app), **extra)

    assert response.status_code == 400
    assert count(app, VenueBooking) == 0


# AC3 - each venue checked on its own ---------------------------------------------------------


# TC-SPL-131-13 (BB) AC3: a 30-seat room holds a 20-attendee breakout of a 150 event
def test_tc_spl_131_13_breakout_capacity_is_its_own(app, client):
    event_id = make_event(app, attendance=150)

    response = request_booking(
        client, event_id, breakout(app), layout="classroom", attendee_count=20
    )

    assert response.status_code == 201, response.json
    assert response.json["booking"]["expected_attendance"] == 20


# TC-SPL-131-14 (BB) AC3: capacities are never added together
@pytest.mark.parametrize(("attendees", "expected"), [(30, 201), (31, 409)])
def test_tc_spl_131_14_capacity_boundary_not_summed(app, client, attendees, expected):
    event_id = make_event(app, attendance=150)
    request_booking(client, event_id, add_venue(app))  # a 200-seat hall is already held

    response = request_booking(
        client, event_id, breakout(app), layout="classroom", attendee_count=attendees
    )

    assert response.status_code == expected, response.json
    if expected == 409:
        assert response.json["failed_checks"] == ["Layout and capacity"]


# TC-SPL-131-15 (BB) AC3: the booking's own facilities decide
def test_tc_spl_131_15_own_facilities(app, client):
    event_id = make_event(app)
    room = breakout(app)  # has a projector, no PA system

    refused = request_booking(
        client,
        event_id,
        room,
        layout="classroom",
        attendee_count=20,
        required_facilities=["PA system"],
    )
    accepted = request_booking(
        client, event_id, room, layout="classroom", attendee_count=20, required_facilities=[]
    )

    assert refused.status_code == 409
    assert refused.json["failed_checks"] == ["Required facilities"]
    assert accepted.status_code == 201, accepted.json
    assert accepted.json["booking"]["required_facilities"] == []


# TC-SPL-131-16 (BB) AC3: the event's accessibility needs apply to every venue
def test_tc_spl_131_16_accessibility_applies_to_every_venue(app, client):
    event_id = make_event(app)  # needs step-free access
    request_booking(client, event_id, add_venue(app))

    response = request_booking(
        client, event_id, breakout(app, accessibility=()), layout="classroom", attendee_count=20
    )

    assert response.status_code == 409
    assert response.json["failed_checks"] == ["Accessibility needs"]


# TC-SPL-131-17 (BB) AC3: the event's location preference applies to every venue
def test_tc_spl_131_17_location_applies_to_every_venue(app, client):
    event_id = make_event(app)  # prefers Marina Centre

    response = request_booking(
        client,
        event_id,
        breakout(app, location="Jurong East"),
        layout="classroom",
        attendee_count=20,
    )

    assert response.status_code == 409
    assert response.json["failed_checks"] == ["Preferred location"]


# TC-SPL-131-18 (WB) AC3: approval rechecks the booking's own count, not the event's
def test_tc_spl_131_18_exact_approval_uses_own_count(app, client):
    exact(app)
    event_id = make_event(app, start=time(10), end=time(12), attendance=150)
    room = exact_venue(app, "Studio One", layouts=BREAKOUT_LAYOUTS, setup=0, turnaround=0)
    booking = exact_request(
        client, event_id, room, "11:00", "12:00", layout="classroom", attendee_count=20
    ).json["booking"]

    assert booking["review_reasons"] == []
    assert approve(client, booking["id"]).status_code == 200

    with Session(app.extensions["engine"]) as session:  # the room is later refitted for 12
        session.get(Venue, room).layouts[0].capacity = 12
        session.commit()
    reasons = status(client, event_id).json["bookings"][0]["booking"]["review_reasons"]
    assert "The requested layout no longer holds the expected attendance." in reasons


def test_tc_spl_131_18_attendance_reduced_below_booking_share(app, client):
    exact(app)
    event_id = make_event(app, start=time(10), end=time(12), attendance=150)
    booking = exact_request(client, event_id, exact_venue(app), attendee_count=100).json["booking"]

    set_event(app, event_id, expected_attendance=80)

    reasons = status(client, event_id).json["bookings"][0]["booking"]["review_reasons"]
    assert "This booking's attendee count is above the event's expected attendance." in reasons
    assert approve(client, booking["id"]).status_code == 409


# TC-SPL-131-19 (WB) AC3: each venue's own setup and turnaround
def test_tc_spl_131_19_each_venue_own_preparation(app, client):
    exact(app)
    event_id = make_event(app, start=time(10), end=time(12))
    hall = exact_venue(app)  # 30 / 45 minutes
    room = exact_venue(app, "Studio One", layouts=BREAKOUT_LAYOUTS, setup=0, turnaround=15)

    hall_booking = exact_request(client, event_id, hall).json["booking"]
    room_booking = exact_request(
        client, event_id, room, "11:00", "12:00", layout="classroom", attendee_count=20
    ).json["booking"]

    assert hall_booking["timing"]["occupied"]["start"] == "2026-10-14T09:30:00+08:00"
    assert room_booking["timing"]["occupied"] == {
        "start": "2026-10-14T11:00:00+08:00",
        "end": "2026-10-14T12:15:00+08:00",
    }


# AC4 - a refusal is local --------------------------------------------------------------------


def _snapshot(app, booking_id):
    return booking_row(app, booking_id), claims(app, booking_id), len(history(app, booking_id))


# TC-SPL-131-20 (BB) AC4: an unsuitable second request leaves the first unchanged
def test_tc_spl_131_20_unsuitable_request_leaves_others(app, client):
    event_id, hall = make_event(app), add_venue(app)
    first = request_booking(client, event_id, hall).json["booking"]
    before = _snapshot(app, first["id"])

    response = request_booking(
        client, event_id, breakout(app), layout="classroom", attendee_count=40
    )

    assert response.status_code == 409
    assert _snapshot(app, first["id"]) == before
    assert count(app, VenueBooking) == 1


# TC-SPL-131-21 (BB) AC4: a conflicting second request leaves the first unchanged
def test_tc_spl_131_21_conflicting_request_leaves_others(app, client):
    event_id, hall, room = make_event(app), add_venue(app), breakout(app)
    other_event = make_event(app, "Other Forum")
    assert (
        request_booking(
            client, other_event, room, layout="classroom", attendee_count=20
        ).status_code
        == 201
    )
    first = request_booking(client, event_id, hall).json["booking"]
    before = _snapshot(app, first["id"])

    response = request_booking(client, event_id, room, layout="classroom", attendee_count=20)

    assert response.status_code == 409
    assert "conflict" in response.json
    assert _snapshot(app, first["id"]) == before


# TC-SPL-131-22 (BB) AC4 15-minute mode: a block refuses only that request
def test_tc_spl_131_22_exact_block_refuses_only_that_request(app, client):
    exact(app)
    event_id = make_event(app, start=time(10), end=time(12))
    hall, room = exact_venue(app), exact_venue(app, "Studio One", layouts=BREAKOUT_LAYOUTS)
    first = exact_request(client, event_id, hall).json["booking"]
    with Session(app.extensions["engine"]) as session:
        session.add(
            VenueOperationalBlock(
                venue_id=room,
                start_date=EVENT_DATE,
                end_date=EVENT_DATE,
                slots=["AM", "PM", "NIGHT"],
                reason="Ceiling repair",
                created_by_account_id=base.VENUE_STAFF,
                created_at=datetime(2026, 9, 25, 9, tzinfo=timezone.utc),
            )
        )
        session.commit()
    before = _snapshot(app, first["id"])

    response = exact_request(client, event_id, room, layout="classroom", attendee_count=20)

    assert response.status_code == 409
    assert _snapshot(app, first["id"]) == before


# TC-SPL-131-23 (BB) AC4: a refused request writes no booking, claim or history
def test_tc_spl_131_23_refusal_writes_nothing(app, client):
    event_id = make_event(app)

    response = request_booking(
        client, event_id, breakout(app), layout="classroom", attendee_count=31
    )

    assert response.status_code == 409
    assert count(app, VenueBooking) == 0
    assert count(app, VenueBookingOccupancy) == 0
    assert count(app, VenueBookingStatusHistory) == 0


# TC-SPL-131-24 (BB) AC4: after a refusal, a valid request still succeeds
def test_tc_spl_131_24_valid_request_after_refusal(app, client):
    event_id, room = make_event(app), breakout(app)

    assert (
        request_booking(client, event_id, room, layout="classroom", attendee_count=31).status_code
        == 409
    )
    response = request_booking(client, event_id, room, layout="classroom", attendee_count=30)

    assert response.status_code == 201, response.json


# AC5 - no second hold on the same venue at an overlapping time --------------------------------


# TC-SPL-131-25 (BB) AC5 slot mode: the same venue twice is refused, for Requested and Approved
@pytest.mark.parametrize("approve_first", [False, True])
def test_tc_spl_131_25_same_venue_twice_refused(app, client, approve_first):
    event_id, hall = make_event(app), add_venue(app)
    first = request_booking(client, event_id, hall).json["booking"]
    if approve_first:
        assert approve(client, first["id"]).status_code == 200

    response = request_booking(client, event_id, hall, layout="classroom", attendee_count=20)

    assert response.status_code == 409
    assert response.json["error"].startswith(
        "This event already holds Harbour Hall at an overlapping time."
    )
    assert count(app, VenueBooking) == 1


# TC-SPL-131-26 (BB) AC5 15-minute mode: overlap on occupied time, not advertised time
@pytest.mark.parametrize(
    ("start", "end", "expected"),
    [
        ("11:00", "12:00", 409),  # advertised overlap
        ("11:00", "11:30", 409),  # advertised gap, but setup 10:30 overlaps turnaround to 10:45
        ("11:30", "13:00", 201),  # setup starts 11:00, after the first booking's 10:45
    ],
)
def test_tc_spl_131_26_same_venue_occupied_overlap(app, client, start, end, expected):
    exact(app)
    event_id = make_event(app, start=time(8), end=time(16))
    hall = exact_venue(app)
    assert exact_request(client, event_id, hall, "08:00", "10:00").status_code == 201

    response = exact_request(client, event_id, hall, start, end)

    assert response.status_code == expected, response.json
    if expected == 409:
        assert "already holds Harbour Hall" in response.json["error"]


# TC-SPL-131-27 (BB) AC5: inactive bookings never block the same venue
@pytest.mark.parametrize("inactive", ["rejected", "withdrawn", "cancelled"])
def test_tc_spl_131_27_inactive_booking_does_not_block(app, client, inactive):
    event_id, hall = make_event(app), add_venue(app)
    seed_booking(app, event_id, hall, inactive)

    response = request_booking(client, event_id, hall)

    assert response.status_code == 201, response.json


# TC-SPL-131-29 (WB) AC5: unreadable stored timing fails closed
def test_tc_spl_131_29_unreadable_timing_fails_closed(app, client):
    exact(app)
    event_id = make_event(app, start=time(8), end=time(16))
    hall = exact_venue(app)
    first = exact_request(client, event_id, hall, "08:00", "09:00").json["booking"]
    with Session(app.extensions["engine"]) as session:
        session.get(VenueBooking, first["id"]).exact_timing = {"event": {}, "occupied": {}}
        session.commit()

    response = exact_request(client, event_id, hall, "14:00", "15:00")

    assert response.status_code == 409
    assert "already holds" in response.json["error"]


def test_tc_spl_131_29_legacy_booking_at_same_venue_blocks_exact_request(app, client):
    exact(app)
    event_id = make_event(app, start=time(8), end=time(16))
    hall = exact_venue(app)
    seed_booking(app, event_id, hall, "approved")  # a slot-era booking with no exact timing

    response = exact_request(client, event_id, hall, "14:00", "15:00")

    assert response.status_code == 409
    assert "already holds" in response.json["error"]


# AC6 - changing one booking changes only that booking -----------------------------------------


# TC-SPL-131-30 (BB) AC6: approving one leaves the other Requested
def test_tc_spl_131_30_approve_one(app, client):
    event_id, _, _, hall_id, room_id = two_venue_event(app, client)
    before = _snapshot(app, room_id)

    assert approve(client, hall_id).status_code == 200

    assert _snapshot(app, room_id) == before
    assert booking_row(app, room_id)["status"] == "requested"


# TC-SPL-131-31 (BB) AC6: rejecting one releases only its time
def test_tc_spl_131_31_reject_one(app, client):
    event_id, hall, _, hall_id, room_id = two_venue_event(app, client)
    before = _snapshot(app, room_id)

    response = client.post(
        f"/api/venue-bookings/{hall_id}/reject",
        json={"reason": "Hall closed for repairs."},
        headers=headers("venue-staff"),
    )

    assert response.status_code == 200, response.json
    assert claims(app, hall_id) == set()
    assert occupancy(app, hall) == set()
    assert _snapshot(app, room_id) == before


# TC-SPL-131-32 (BB) AC6: withdrawing one leaves the other unchanged
def test_tc_spl_131_32_withdraw_one(app, client):
    event_id, _, _, hall_id, room_id = two_venue_event(app, client)
    before = _snapshot(app, hall_id)

    response = client.post(
        f"/api/event-requests/{event_id}/venue-bookings/{room_id}/withdraw", headers=headers()
    )

    assert response.status_code == 200, response.json
    assert claims(app, room_id) == set()
    assert _snapshot(app, hall_id) == before


# TC-SPL-131-33 (BB) AC6: cancelling one leaves the other unchanged
def test_tc_spl_131_33_cancel_one(app, client):
    event_id, _, _, hall_id, room_id = two_venue_event(app, client, approve_first=True)
    assert approve(client, room_id).status_code == 200
    before = _snapshot(app, room_id)

    assert cancel(client, event_id, hall_id).status_code == 200

    assert claims(app, hall_id) == set()
    assert _snapshot(app, room_id) == before
    assert booking_row(app, room_id)["status"] == "approved"


# TC-SPL-131-34 (BB) AC6/AC7 15-minute mode: cancelling releases that exact time to others
def test_tc_spl_131_34_exact_cancel_releases_time(app, client):
    exact(app)
    event_id = make_event(app, start=time(10), end=time(12))
    other_event = make_event(app, "Other Forum", start=time(10), end=time(12))
    hall = exact_venue(app)
    booking = exact_request(client, event_id, hall).json["booking"]
    assert approve(client, booking["id"]).status_code == 200
    assert exact_request(client, other_event, hall).status_code == 409

    assert cancel(client, event_id, booking["id"]).status_code == 200

    assert exact_request(client, other_event, hall).status_code == 201


# AC7 - cancel one Approved booking with a reason ----------------------------------------------


# TC-SPL-131-35 (BB) AC7: the history records the reason, who and when
def test_tc_spl_131_35_cancel_records_history(app, client):
    event_id, _, _, hall_id, _ = two_venue_event(app, client, approve_first=True)
    started = datetime.now(timezone.utc)

    response = cancel(client, event_id, hall_id, reason="  Plenary moved online.  ")

    assert response.status_code == 200, response.json
    assert response.json["booking"]["status"] == "cancelled"
    assert "Harbour Hall" in response.json["message"]
    last = history(app, hall_id)[-1]
    assert (last.action, last.previous_status, last.resulting_status) == (
        "cancel",
        "approved",
        "cancelled",
    )
    assert last.actor_account_id == COORDINATOR
    assert last.note == "Plenary moved online."
    changed_at = (
        last.changed_at
        if last.changed_at.tzinfo
        else last.changed_at.replace(tzinfo=base.SINGAPORE)
    )
    assert started <= changed_at <= datetime.now(timezone.utc)
    shown = status(client, event_id).json["bookings"][0]["history"][-1]
    assert shown["note"] == "Plenary moved online."
    assert shown["actor"]["name"] == "Casey Lim"
    assert shown["changed_at"].endswith("+08:00")


# TC-SPL-131-36 (BB) AC7: the reason is required, non-blank and at most 1,000 characters
@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ({"reason": ""}, 400),
        ({"reason": "   "}, 400),
        ({"reason": None}, 400),
        ({"reason": 42}, 400),
        ({}, 400),
        ({"reason": "Moved", "status": "cancelled"}, 400),
        ({"reason": "x" * 1001}, 400),
        ({"reason": "x" * 1000}, 200),
    ],
)
def test_tc_spl_131_36_reason_validation(app, client, body, expected):
    event_id, _, _, hall_id, _ = two_venue_event(app, client, approve_first=True)
    before = len(history(app, hall_id))

    response = cancel(client, event_id, hall_id, body=body)

    assert response.status_code == expected, response.json
    assert len(history(app, hall_id)) == before + (1 if expected == 200 else 0)


def test_tc_spl_131_36_non_json_body_refused(app, client):
    event_id, _, _, hall_id, _ = two_venue_event(app, client, approve_first=True)

    response = client.post(
        f"/api/event-requests/{event_id}/venue-bookings/{hall_id}/cancel",
        data="reason=Moved",
        headers=headers(),
    )

    assert response.status_code == 400
    assert booking_row(app, hall_id)["status"] == "approved"


# TC-SPL-131-37 (BB) AC7: only an Approved booking can be cancelled, and only once
@pytest.mark.parametrize("booking_status", ["requested", "rejected", "withdrawn", "cancelled"])
def test_tc_spl_131_37_only_approved(app, client, booking_status):
    event_id, hall = make_event(app), add_venue(app)
    booking_id = seed_booking(app, event_id, hall, booking_status)

    response = cancel(client, event_id, booking_id)

    assert response.status_code == 409
    assert booking_row(app, booking_id)["status"] == booking_status
    assert history(app, booking_id) == []


def test_tc_spl_131_37_cancelled_exactly_once(app, client):
    event_id, _, _, hall_id, _ = two_venue_event(app, client, approve_first=True)

    assert cancel(client, event_id, hall_id).status_code == 200
    again = cancel(client, event_id, hall_id)

    assert again.status_code == 409
    assert [entry.action for entry in history(app, hall_id)].count("cancel") == 1


# TC-SPL-131-38 (BB) AC7 slot mode: the cancelled venue's time is available again
def test_tc_spl_131_38_released_slots_bookable(app, client):
    event_id, hall, _, hall_id, _ = two_venue_event(app, client, approve_first=True)
    other_event = make_event(app, "Other Forum")
    assert request_booking(client, other_event, hall).status_code == 409

    assert cancel(client, event_id, hall_id).status_code == 200

    assert occupancy(app, hall) == set()
    assert request_booking(client, other_event, hall).status_code == 201


# TC-SPL-131-39 (BB) AC7/AC10: cancelling needs the event in Planning
@pytest.mark.parametrize("event_status", ["confirmed", "cancelled", "postponed", "completed"])
def test_tc_spl_131_39_cancel_only_in_planning(app, client, event_status):
    event_id, _, _, hall_id, _ = two_venue_event(app, client, approve_first=True)
    set_event(app, event_id, status=event_status)

    response = cancel(client, event_id, hall_id)

    assert response.status_code == 409
    assert (
        response.json["error"]
        == "A venue booking can be cancelled only while the event is in Planning."
    )
    assert booking_row(app, hall_id)["status"] == "approved"


# AC8 - seeing every booking ------------------------------------------------------------------


# TC-SPL-131-41 (BB) AC8: the coordinator sees every booking with its own details and history
def test_tc_spl_131_41_status_lists_every_booking(app, client):
    event_id, _, _, hall_id, room_id = two_venue_event(app, client, approve_first=True)

    body = status(client, event_id).json

    assert [item["booking"]["id"] for item in body["bookings"]] == [hall_id, room_id]
    hall, room = body["bookings"]
    assert (hall["booking"]["venue"]["name"], hall["booking"]["expected_attendance"]) == (
        "Harbour Hall",
        150,
    )
    assert (room["booking"]["venue"]["name"], room["booking"]["expected_attendance"]) == (
        "Breakout Room",
        20,
    )
    assert hall["booking"]["event_slots"] == ["PM"] and room["booking"]["event_slots"] == ["PM"]
    assert (hall["current_status"], room["current_status"]) == (
        {"status": "approved", "label": "Approved"},
        {"status": "requested", "label": "Requested"},
    )
    assert [entry["action"] for entry in hall["history"]] == ["request", "approve"]
    assert [entry["action"] for entry in room["history"]] == ["request"]
    assert body["venue_booking_request"]["id"] == room_id  # latest-request fields kept


# TC-SPL-131-42 (BB) AC8: Venue Staff see each request separately with its own details
def test_tc_spl_131_42_queue_lists_each_request(app, client):
    event_id, _, _, hall_id, room_id = two_venue_event(app, client)

    items = client.get("/api/venue-bookings/pending", headers=headers("venue-staff")).json[
        "requests"
    ]

    by_id = {item["id"]: item for item in items}
    assert set(by_id) == {hall_id, room_id}
    assert (
        by_id[hall_id]["expected_attendance"],
        by_id[hall_id]["layout"],
        by_id[hall_id]["required_facilities"],
    ) == (150, "theatre", ["Projector"])
    assert (
        by_id[room_id]["expected_attendance"],
        by_id[room_id]["layout"],
        by_id[room_id]["required_facilities"],
    ) == (20, "classroom", ["Projector"])
    assert by_id[room_id]["event"] == {"id": event_id, "name": "Coastal Forum"}


# TC-SPL-131-43 (BB) AC8: the staff review of one request shows that booking's details
def test_tc_spl_131_43_staff_review_shows_booking_details(app, client):
    event_id = make_event(app)
    room = breakout(app)
    booking = request_booking(
        client, event_id, room, layout="classroom", attendee_count=20, required_facilities=[]
    ).json["booking"]

    body = client.get(f"/api/venue-bookings/{booking['id']}", headers=headers("venue-staff")).json

    assert body["booking"]["expected_attendance"] == 20
    assert body["booking"]["layout"] == "classroom"
    assert body["booking"]["required_facilities"] == []


# TC-SPL-131-46 (BB) AC8/AC10: a coordinator sees bookings only for events assigned to them
@pytest.mark.parametrize(
    ("token", "expected"),
    [
        ("other-coordinator", 404),
        ("manager", 403),
        ("organiser", 403),
        ("venue-staff", 403),
        (None, 401),
    ],
)
def test_tc_spl_131_46_status_privacy(app, client, token, expected):
    event_id, *_ = two_venue_event(app, client)

    response = status(client, event_id, token)

    assert response.status_code == expected
    assert "bookings" not in (response.json or {})


# AC9 - the existing single booking -----------------------------------------------------------


# TC-SPL-131-47 (BB) AC9: a pre-SPL-131 booking is the first, with its values and history
def test_tc_spl_131_47_existing_booking_first(app, client):
    event_id, hall = make_event(app), add_venue(app)
    original = request_booking(client, event_id, hall).json["booking"]
    with Session(app.extensions["engine"]) as session:  # as the migration leaves an older row
        session.get(VenueBooking, original["id"]).required_facilities = None
        session.commit()
    original_history = [(entry.action, entry.changed_at) for entry in history(app, original["id"])]

    request_booking(client, event_id, breakout(app), layout="classroom", attendee_count=20)
    first = status(client, event_id).json["bookings"][0]

    assert first["booking"]["id"] == original["id"]
    assert first["booking"]["expected_attendance"] == 150
    assert first["booking"]["layout"] == "theatre"
    assert first["booking"]["required_facilities"] == ["Projector"]  # the event's
    assert [
        (entry.action, entry.changed_at) for entry in history(app, original["id"])
    ] == original_history


# TC-SPL-131-49 (BB) AC9: a seeded booking with no request data still lists first
def test_tc_spl_131_49_seeded_legacy_booking_listed(app, client):
    event_id, hall = make_event(app), add_venue(app)
    seeded = seed_booking(app, event_id, hall, "approved")

    request_booking(client, event_id, breakout(app), layout="classroom", attendee_count=20)
    ids = [item["booking"]["id"] for item in status(client, event_id).json["bookings"]]

    assert ids[0] == seeded and len(ids) == 2


# TC-SPL-131-50 (WB) AC9: null facilities follow the event; recorded ones do not
def test_tc_spl_131_50_facilities_fallback_only_when_unrecorded(app, client):
    event_id = make_event(app)
    legacy_id = seed_booking(app, event_id, add_venue(app), "approved")
    recorded = request_booking(
        client, event_id, breakout(app), layout="classroom", attendee_count=20
    ).json["booking"]

    set_event(app, event_id, required_facilities=["Projector", "Livestream"])
    items = {
        item["booking"]["id"]: item["booking"] for item in status(client, event_id).json["bookings"]
    }

    assert items[legacy_id]["required_facilities"] == ["Projector", "Livestream"]
    assert items[recorded["id"]]["required_facilities"] == ["Projector"]


# AC10 - who can do it ------------------------------------------------------------------------


# TC-SPL-131-52 (BB) AC10: only the assigned coordinator can cancel
@pytest.mark.parametrize(
    ("token", "expected"),
    [
        ("other-coordinator", 404),
        ("manager", 403),
        ("organiser", 403),
        ("venue-staff", 403),
        (None, 401),
    ],
)
def test_tc_spl_131_52_cancel_security(app, client, token, expected):
    event_id, _, _, hall_id, _ = two_venue_event(app, client, approve_first=True)
    before = _snapshot(app, hall_id)

    response = cancel(client, event_id, hall_id, token=token)

    assert response.status_code == expected
    assert _snapshot(app, hall_id) == before


def test_tc_spl_131_52_cancel_through_another_event_refused(app, client):
    event_id, _, _, hall_id, _ = two_venue_event(app, client, approve_first=True)
    mine = make_event(app, "My Other Event")

    for target in (mine, 999999, 10**12):
        assert cancel(client, target, hall_id).status_code == 404
    assert cancel(client, event_id, 10**12).status_code == 404
    assert booking_row(app, hall_id)["status"] == "approved"


def test_tc_spl_131_52_cancel_another_coordinators_booking_refused(app, client):
    theirs = make_event(app, "Their Event", coordinator=OTHER_COORDINATOR)
    booking_id = seed_booking(app, theirs, add_venue(app), "approved")
    mine = make_event(app, "My Event")

    assert cancel(client, mine, booking_id).status_code == 404
    assert booking_row(app, booking_id)["status"] == "approved"


# TC-SPL-131-53 (BB) AC10: request authority
@pytest.mark.parametrize(
    ("token", "expected"),
    [
        ("other-coordinator", 404),
        ("manager", 403),
        ("organiser", 403),
        ("venue-staff", 403),
        (None, 401),
    ],
)
def test_tc_spl_131_53_request_security(app, client, token, expected):
    event_id = make_event(app)
    request_booking(client, event_id, add_venue(app))

    response = request_booking(
        client, event_id, breakout(app), layout="classroom", attendee_count=20, token=token
    )

    assert response.status_code == expected
    assert count(app, VenueBooking) == 1


# TC-SPL-131-54 (BB) AC10: withdrawal keeps the SPL-78 rule after the event leaves Planning (Q60)
def test_tc_spl_131_54_withdraw_after_event_cancelled(app, client):
    event_id, _, _, hall_id, room_id = two_venue_event(app, client)
    set_event(app, event_id, status="cancelled")

    response = client.post(
        f"/api/event-requests/{event_id}/venue-bookings/{room_id}/withdraw", headers=headers()
    )

    assert response.status_code == 200, response.json
    assert booking_row(app, hall_id)["status"] == "requested"


# TC-SPL-131-55 (BB) AC10: after reassignment only the new coordinator can cancel
def test_tc_spl_131_55_reassignment(app, client):
    event_id, _, _, hall_id, _ = two_venue_event(app, client, approve_first=True)
    with Session(app.extensions["engine"]) as session:
        assignment = session.scalar(
            select(EventCoordinatorAssignment).where(
                EventCoordinatorAssignment.event_request_id == event_id
            )
        )
        assignment.coordinator_account_id = OTHER_COORDINATOR
        session.commit()

    assert cancel(client, event_id, hall_id).status_code == 404
    assert status(client, event_id).status_code == 404
    assert cancel(client, event_id, hall_id, token="other-coordinator").status_code == 200
    assert history(app, hall_id)[-1].actor_account_id == OTHER_COORDINATOR


def test_tc_spl_131_29_unconfigured_venue_timing_refused(app, client):
    exact(app)
    event_id = make_event(app, start=time(10), end=time(12))
    venue_id = add_venue(app)  # no 15-minute operating hours or preparation minutes recorded
    with Session(app.extensions["engine"]) as session:
        session.get(Venue, venue_id).timing_revision = 1
        session.commit()

    response = exact_request(client, event_id, venue_id)

    assert response.status_code == 409
    assert "Confirm venue operating hours" in response.json["error"]
    assert count(app, VenueBooking) == 0


# Review fixes (CLIVELIM01 on PR #87) ------------------------------------------------------------

# Reassessment covers only commitments that have not ended (SPL-130), so these use a future date.
FUTURE = date(2027, 1, 20)
INTERVALS = {
    "14-15": {"start": "2027-01-20T14:00:00+08:00", "end": "2027-01-20T15:00:00+08:00"},
    "16-17": {"start": "2027-01-20T16:00:00+08:00", "end": "2027-01-20T17:00:00+08:00"},
}


def _venue_timing(client, venue_id, *, setup=0, turnaround=0, hours=None):
    return client.patch(
        f"/api/venues/{venue_id}",
        json={
            "setup_minutes": setup,
            "turnaround_minutes": turnaround,
            "operating_intervals": hours or [[0, 1440]],
        },
        headers=headers("venue-staff"),
    )


def _future_request(client, event_id, venue_id, start, end, **extra):
    return exact_request(client, event_id, venue_id, start, end, date=FUTURE.isoformat(), **extra)


def _sub_windows(app, client):
    """One 13:00-18:00 event holding a zero-buffer hall twice: 14-15 Approved, 16-17 Requested."""

    exact(app)
    event_id = make_event(app, day=FUTURE, start=time(13), end=time(18))
    hall = exact_venue(app, setup=0, turnaround=0)
    first = _future_request(client, event_id, hall, "14:00", "15:00").json["booking"]
    assert approve(client, first["id"]).status_code == 200
    second = _future_request(client, event_id, hall, "16:00", "17:00").json["booking"]
    return event_id, hall, first["id"], second["id"]


def _findings(app, booking_id):
    from app.models import VenueBookingReviewFinding

    with Session(app.extensions["engine"]) as session:
        return sorted(
            finding.reason_type
            for finding in session.scalars(
                select(VenueBookingReviewFinding).where(
                    VenueBookingReviewFinding.booking_id == booking_id,
                    VenueBookingReviewFinding.resolved_at.is_(None),
                )
            )
        )


# TC-SPL-131-59 (WB) AC2/AC3: reassessment uses each booking's own interval, not the event's
def test_tc_spl_131_59_reassessment_uses_each_booking_interval(app, client):
    _, hall, first, second = _sub_windows(app, client)

    response = _venue_timing(client, hall, hours=[[840, 960]])  # opening hours 14:00-16:00

    assert response.status_code == 200, response.json
    assert response.json["affected_booking_count"] == 1
    assert _findings(app, first) == []  # 14:00-15:00 still fits
    assert _findings(app, second) == ["outside_operating_hours"]  # 16:00-17:00 does not
    assert booking_row(app, first)["exact_timing"]["event"] == INTERVALS["14-15"]


def test_tc_spl_131_59_peers_compared_on_their_own_intervals(app, client):
    _, hall, first, second = _sub_windows(app, client)

    # With 45 minutes either side, 13:15-15:45 and 15:15-17:45 overlap each other.
    assert _venue_timing(client, hall, setup=45, turnaround=45).json["affected_booking_count"] == 2
    assert _findings(app, first) == ["overlap"]
    assert _findings(app, second) == ["overlap"]

    # With 15 minutes they no longer overlap, so nothing is newly flagged.
    assert _venue_timing(client, hall, setup=15, turnaround=15).json["affected_booking_count"] == 0


# TC-SPL-131-60 (WB) AC2/AC6: clearing a timing review keeps the booking's own advertised time
@pytest.mark.parametrize("which", ["approved", "requested"])
def test_tc_spl_131_60_clearance_preserves_booking_interval(app, client, which):
    _, hall, first, second = _sub_windows(app, client)
    target, other, window = (
        (first, second, "14-15") if which == "approved" else (second, first, "16-17")
    )
    _venue_timing(client, hall, setup=45, turnaround=45)
    other_before = booking_row(app, other)
    refused = client.post(
        f"/api/venue-bookings/{target}/timing-review", headers=headers("venue-staff")
    )
    assert refused.status_code == 409  # still overlaps its sibling
    _venue_timing(client, hall, setup=15, turnaround=15)

    cleared = client.post(
        f"/api/venue-bookings/{target}/timing-review", headers=headers("venue-staff")
    )

    assert cleared.status_code == 200, cleared.json
    timing = booking_row(app, target)["exact_timing"]
    assert timing["event"] == INTERVALS[window]
    starts = {"14-15": "2027-01-20T13:45:00+08:00", "16-17": "2027-01-20T15:45:00+08:00"}
    assert timing["occupied"]["start"] == starts[window]
    assert _findings(app, target) == []
    other_after = booking_row(app, other)
    assert other_after["exact_timing"] == other_before["exact_timing"]
    assert other_after["status"] == other_before["status"]


# TC-SPL-131-61 (BB) AC5 of SPL-85: the organiser sees each venue's own confirmed hours
def test_tc_spl_131_61_confirmed_arrangements_show_each_booking_times(app, client):
    exact(app)
    event_id = make_event(app, day=FUTURE, start=time(13), end=time(18))
    hall = exact_venue(app, setup=0, turnaround=0)
    room = exact_venue(app, "Studio One", layouts=BREAKOUT_LAYOUTS, setup=0, turnaround=0)
    plenary = _future_request(client, event_id, hall, "13:00", "18:00").json["booking"]
    breakout_booking = _future_request(
        client, event_id, room, "14:00", "15:00", layout="classroom", attendee_count=20
    ).json["booking"]
    for booking in (plenary, breakout_booking):
        assert approve(client, booking["id"]).status_code == 200
    confirmed = client.post(f"/api/event-requests/{event_id}/confirm", headers=headers())
    assert confirmed.status_code == 200, confirmed.json

    requests = client.get("/api/event-requests", headers=headers("organiser")).json
    event = next(item for item in requests["event_requests"] if item["id"] == event_id)
    venues = {item["venue"]: item for item in event["confirmed_arrangements"]["venues"]}

    assert (venues["Harbour Hall"]["start_time"], venues["Harbour Hall"]["end_time"]) == (
        "13:00",
        "18:00",
    )
    assert (venues["Studio One"]["start_time"], venues["Studio One"]["end_time"]) == (
        "14:00",
        "15:00",
    )
    assert venues["Studio One"]["date"] == FUTURE.isoformat()
