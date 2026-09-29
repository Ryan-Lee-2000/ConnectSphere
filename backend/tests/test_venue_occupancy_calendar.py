"""Acceptance coverage for SPL-88 (CS-E11-S1): view venue occupancy on a calendar.

Each test carries the QA-SPL-88 case identifier it proves. Expected values come from the story's
acceptance criteria and its four recorded judgement calls (docs/tasks/SPL-88.md): multi-reason
precedence, preparation slots follow occupancy kind not booking status, the three authorised roles,
the 31-day range cap, and no occupant identity in the response.
"""

from datetime import date, datetime, time, timezone

import pytest
from app import create_app
from app.models import (
    Account,
    AccountRole,
    Base,
    EventRequest,
    Organisation,
    Role,
    Venue,
    VenueBooking,
    VenueBookingOccupancy,
    VenueLayout,
    VenueOperationalBlock,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

VENUE_STAFF = "00000000-0000-0000-0000-000000000881"
COORDINATOR = "00000000-0000-0000-0000-000000000882"
MANAGER = "00000000-0000-0000-0000-000000000883"
ORGANISER = "00000000-0000-0000-0000-000000000884"
ATTENDEE = "00000000-0000-0000-0000-000000000885"
TOKENS = {
    "venue-staff": VENUE_STAFF,
    "coordinator": COORDINATOR,
    "manager": MANAGER,
    "organiser": ORGANISER,
    "attendee": ATTENDEE,
}
DAY = date(2026, 10, 14)
NAME = "Coastal Forum"
ORG_NAME = "Northstar Community Partners"


@pytest.fixture
def app(tmp_path):
    app = create_app(
        {
            "TESTING": True,
            "DATABASE_URL": f"sqlite:///{tmp_path}/occupancy-calendar.db",
            "IDENTITY_VERIFIER": TOKENS.__getitem__,
        }
    )
    engine = app.extensions["engine"]
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        organisation = Organisation(name=ORG_NAME)
        session.add(organisation)
        session.flush()
        for account_id, name, role in (
            (VENUE_STAFF, "Valerie Tan", Role.VENUE_STAFF),
            (COORDINATOR, "Casey Lim", Role.EVENT_COORDINATOR),
            (MANAGER, "Morgan Ong", Role.EVENT_OPERATIONS_MANAGER),
            (ORGANISER, "Devon Lee", Role.EVENT_ORGANISER),
            (ATTENDEE, "Ari Koh", Role.ATTENDEE),
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


def add_venue(app, name="Harbour Hall", operating_slots=("AM", "PM", "NIGHT")):
    with Session(app.extensions["engine"]) as session:
        venue = Venue(
            name=name,
            location="Level 3, Marina Centre",
            operating_slots=list(operating_slots),
            setup_buffer_slots=1,
            turnaround_buffer_slots=1,
        )
        venue.layouts = [VenueLayout(layout="theatre", capacity=200)]
        session.add(venue)
        session.commit()
        return venue.id


def make_event(app, name=NAME):
    with Session(app.extensions["engine"]) as session:
        event = EventRequest(
            organiser_account_id=ORGANISER,
            organisation_id=app.config["ORGANISATION_ID"],
            name=name,
            purpose="Community planning",
            proposed_date=DAY,
            start_time=time(13),
            end_time=time(18),
            expected_attendance=150,
            status="planning",
        )
        session.add(event)
        session.commit()
        return event.id


def seed_booking(app, venue_id, event_id, status, day=DAY, slot="PM"):
    """A booking with one event-slot occupancy row, no preparation."""

    with Session(app.extensions["engine"]) as session:
        booking = VenueBooking(
            event_request_id=event_id, venue_id=venue_id, status=status, layout="theatre"
        )
        session.add(booking)
        session.flush()
        session.add(
            VenueBookingOccupancy(
                booking_id=booking.id, venue_id=venue_id, day=day, slot=slot, kind="event"
            )
        )
        session.commit()
        return booking.id


def seed_preparation(app, venue_id, booking_id, day=DAY, slot="AM", kind="setup"):
    with Session(app.extensions["engine"]) as session:
        session.add(
            VenueBookingOccupancy(
                booking_id=booking_id, venue_id=venue_id, day=day, slot=slot, kind=kind
            )
        )
        session.commit()


def add_block(app, venue_id, day=DAY, slots=("PM",), reason="Ceiling repair"):
    with Session(app.extensions["engine"]) as session:
        session.add(
            VenueOperationalBlock(
                venue_id=venue_id,
                start_date=day,
                end_date=day,
                slots=list(slots),
                reason=reason,
                created_by_account_id=VENUE_STAFF,
                created_at=datetime(2026, 9, 20, 9, tzinfo=timezone.utc),
            )
        )
        session.commit()


def headers(token="venue-staff"):
    return {"Authorization": f"Bearer {token}"} if token else {}


def occupancy(client, venue_id, start=DAY, end=DAY, token="venue-staff"):
    return client.get(
        f"/api/venues/{venue_id}/occupancy?start_date={start.isoformat()}&end_date={end.isoformat()}",
        headers=headers(token),
    )


def day_entry(response, day=DAY):
    return next(entry for entry in response.json["days"] if entry["date"] == day.isoformat())


def slot_entry(response, slot, day=DAY):
    return next(item for item in day_entry(response, day)["slots"] if item["slot"] == slot)


def row_counts(app):
    with Session(app.extensions["engine"]) as session:
        return (
            session.query(VenueBooking).count(),
            session.query(VenueBookingOccupancy).count(),
            session.query(VenueOperationalBlock).count(),
        )


# AC1 — select a venue and a date or range


# TC-SPL-88-01
def test_tc_spl_88_01_venue_staff_retrieve_a_single_day(app, client):
    venue_id = add_venue(app)

    response = occupancy(client, venue_id)

    assert response.status_code == 200, response.json
    assert len(response.json["days"]) == 1
    entry = response.json["days"][0]
    assert entry["date"] == DAY.isoformat()
    assert {item["slot"] for item in entry["slots"]} == {"AM", "PM", "NIGHT"}


# TC-SPL-88-02
def test_tc_spl_88_02_a_range_returns_one_entry_per_day_in_order(app, client):
    venue_id = add_venue(app)
    end = date(2026, 10, 20)

    response = occupancy(client, venue_id, start=DAY, end=end)

    assert response.status_code == 200, response.json
    dates = [entry["date"] for entry in response.json["days"]]
    assert dates == [date.fromordinal(DAY.toordinal() + offset).isoformat() for offset in range(7)]


# AC2 / AC3 — the five occupancy states


# TC-SPL-88-03
def test_tc_spl_88_03_an_untouched_slot_is_available(app, client):
    venue_id = add_venue(app)

    response = occupancy(client, venue_id)

    for item in day_entry(response)["slots"]:
        assert item["status"] == "available"
        assert item["reasons"] == []


# TC-SPL-88-04
def test_tc_spl_88_04_a_requested_bookings_event_slot_is_requested(app, client):
    venue_id = add_venue(app)
    event_id = make_event(app)
    seed_booking(app, venue_id, event_id, "requested")

    response = occupancy(client, venue_id)

    item = slot_entry(response, "PM")
    assert item["status"] == "requested"
    assert [reason["key"] for reason in item["reasons"]] == ["booking"]


# TC-SPL-88-05
def test_tc_spl_88_05_an_approved_bookings_event_slot_is_booked(app, client):
    venue_id = add_venue(app)
    event_id = make_event(app)
    seed_booking(app, venue_id, event_id, "approved")

    response = occupancy(client, venue_id)

    assert slot_entry(response, "PM")["status"] == "booked"


# TC-SPL-88-06
def test_tc_spl_88_06_a_preparation_slot_is_preparation(app, client):
    venue_id = add_venue(app)
    event_id = make_event(app)
    booking_id = seed_booking(app, venue_id, event_id, "approved")
    seed_preparation(app, venue_id, booking_id, slot="AM", kind="setup")

    response = occupancy(client, venue_id)

    item = slot_entry(response, "AM")
    assert item["status"] == "preparation"
    assert [reason["key"] for reason in item["reasons"]] == ["preparation"]


# TC-SPL-88-07
def test_tc_spl_88_07_a_blocked_slot_with_no_booking_is_blocked(app, client):
    venue_id = add_venue(app)
    add_block(app, venue_id, slots=("NIGHT",))

    response = occupancy(client, venue_id)

    item = slot_entry(response, "NIGHT")
    assert item["status"] == "blocked"
    assert [reason["key"] for reason in item["reasons"]] == ["block"]


# TC-SPL-88-08
@pytest.mark.parametrize("status", ["rejected", "withdrawn", "cancelled"])
def test_tc_spl_88_08_terminal_bookings_hold_no_slot(app, client, status):
    venue_id = add_venue(app)
    event_id = make_event(app)
    with Session(app.extensions["engine"]) as session:
        booking = VenueBooking(
            event_request_id=event_id, venue_id=venue_id, status=status, layout="theatre"
        )
        session.add(booking)
        session.commit()

    response = occupancy(client, venue_id)

    assert slot_entry(response, "PM")["status"] == "available"


# AC4 — multi-reason precedence (first judgement call)


# TC-SPL-88-09
def test_tc_spl_88_09_booked_and_blocked_shows_blocked_with_both_reasons(app, client):
    venue_id = add_venue(app)
    event_id = make_event(app)
    seed_booking(app, venue_id, event_id, "approved")
    add_block(app, venue_id, slots=("PM",))

    response = occupancy(client, venue_id)

    item = slot_entry(response, "PM")
    assert item["status"] == "blocked"
    assert {reason["key"] for reason in item["reasons"]} == {"booking", "block"}


# TC-SPL-88-10
def test_tc_spl_88_10_requested_and_blocked_shows_blocked(app, client):
    venue_id = add_venue(app)
    event_id = make_event(app)
    seed_booking(app, venue_id, event_id, "requested")
    add_block(app, venue_id, slots=("PM",))

    response = occupancy(client, venue_id)

    item = slot_entry(response, "PM")
    assert item["status"] == "blocked"
    assert {reason["key"] for reason in item["reasons"]} == {"booking", "block"}


def test_tc_spl_88_10_two_bookings_cannot_share_a_slot_so_only_a_block_can_coincide(app, client):
    """The precedence list only ever fires between a booking and a block.

    `venue_booking_occupancy` is UNIQUE on (venue_id, occupancy_date, slot), which is SPL-83's
    double-booking guarantee enforced by the database. So a slot can hold at most one occupancy row
    — Requested, Booked and Preparation are mutually exclusive by construction and can never
    compete for precedence. Only an operational block, which lives in its own table with no such
    constraint, can coincide with a booking. This test pins that invariant so the precedence rule
    is not mistaken for something broader than it is.
    """

    venue_id = add_venue(app)
    booked_slot = seed_booking(app, venue_id, make_event(app), "requested", slot="PM")
    other_booking = seed_booking(
        app, venue_id, make_event(app, "Harbour Talk"), "requested", slot="NIGHT"
    )

    with pytest.raises(IntegrityError):
        seed_preparation(app, venue_id, other_booking, slot="PM", kind="turnaround")

    assert booked_slot is not None
    assert slot_entry(occupancy(client, venue_id), "PM")["status"] == "requested"


# TC-SPL-88-11 — second judgement call
def test_tc_spl_88_11_preparation_of_a_requested_booking_is_still_preparation(app, client):
    venue_id = add_venue(app)
    event_id = make_event(app)
    booking_id = seed_booking(app, venue_id, event_id, "requested")
    seed_preparation(app, venue_id, booking_id, slot="AM", kind="setup")

    response = occupancy(client, venue_id)

    assert slot_entry(response, "AM")["status"] == "preparation"


# AC5 — unsupported slots


# TC-SPL-88-12
def test_tc_spl_88_12_unsupported_slot_is_not_operated(app, client):
    venue_id = add_venue(app, operating_slots=("AM", "PM"))

    response = occupancy(client, venue_id)

    item = slot_entry(response, "NIGHT")
    assert item["status"] == "not_operated"
    assert item["reasons"] == []
    assert slot_entry(response, "AM")["status"] == "available"


# AC6 — reading changes nothing


# TC-SPL-88-13
def test_tc_spl_88_13_reading_twice_changes_nothing(app, client):
    venue_id = add_venue(app)
    event_id = make_event(app)
    seed_booking(app, venue_id, event_id, "requested")
    add_block(app, venue_id, slots=("NIGHT",))
    before = row_counts(app)

    first = occupancy(client, venue_id)
    second = occupancy(client, venue_id)

    # Non-vacuous: both reads must actually succeed, not just agree while both fail.
    assert first.status_code == second.status_code == 200, (first.json, second.json)
    assert first.json == second.json
    assert row_counts(app) == before


# AC7 — empty venue is Available


# TC-SPL-88-14
def test_tc_spl_88_14_empty_venue_is_available_throughout(app, client):
    venue_id = add_venue(app)

    response = occupancy(client, venue_id, start=DAY, end=date(2026, 10, 16))

    for entry in response.json["days"]:
        for item in entry["slots"]:
            assert item["status"] == "available"


# AC8 — only the three authorised roles (third judgement call)


# TC-SPL-88-15
@pytest.mark.parametrize(
    ("token", "expected"),
    [("organiser", 403), ("attendee", 403), (None, 401)],
)
def test_tc_spl_88_15_unauthorised_roles_are_refused(app, client, token, expected):
    venue_id = add_venue(app)

    assert occupancy(client, venue_id, token=token).status_code == expected
    # Non-vacuous: each intended role genuinely succeeds in the same run.
    for allowed in ("venue-staff", "coordinator", "manager"):
        assert occupancy(client, venue_id, token=allowed).status_code == 200


# Fourth judgement call — maximum range


# TC-SPL-88-16
def test_tc_spl_88_16_range_is_bounded_to_31_days(app, client):
    venue_id = add_venue(app)

    at_limit = occupancy(client, venue_id, start=DAY, end=date.fromordinal(DAY.toordinal() + 30))
    assert at_limit.status_code == 200, at_limit.json
    assert len(at_limit.json["days"]) == 31

    over_limit = occupancy(client, venue_id, start=DAY, end=date.fromordinal(DAY.toordinal() + 31))
    assert over_limit.status_code == 400

    backwards = occupancy(client, venue_id, start=date.fromordinal(DAY.toordinal() + 1), end=DAY)
    assert backwards.status_code == 400


# Fifth judgement call — no occupant identity


# TC-SPL-88-17
def test_tc_spl_88_17_no_occupant_identity_anywhere_in_the_body(app, client):
    venue_id = add_venue(app)
    event_id = make_event(app)
    seed_booking(app, venue_id, event_id, "requested")

    response = occupancy(client, venue_id)

    # Non-vacuous: the response must actually carry the booking (a 403 body would also lack names).
    assert response.status_code == 200, response.json
    assert slot_entry(response, "PM")["status"] == "requested"
    body_text = str(response.json)
    assert NAME not in body_text
    assert ORG_NAME not in body_text
    assert COORDINATOR not in body_text
    assert ORGANISER not in body_text


# AC1 / robustness


# TC-SPL-88-18
def test_tc_spl_88_18_unknown_venue_is_refused(app, client):
    assert occupancy(client, 999999).status_code == 404
    assert occupancy(client, 2**31).status_code == 404


# TC-SPL-88-19
def test_tc_spl_88_19_malformed_or_missing_dates_are_refused(app, client):
    venue_id = add_venue(app)

    assert client.get(f"/api/venues/{venue_id}/occupancy", headers=headers()).status_code == 400
    assert (
        client.get(
            f"/api/venues/{venue_id}/occupancy?start_date=not-a-date&end_date={DAY.isoformat()}",
            headers=headers(),
        ).status_code
        == 400
    )
    assert (
        client.get(
            f"/api/venues/{venue_id}/occupancy?start_date={DAY.isoformat()}", headers=headers()
        ).status_code
        == 400
    )


# TC-SPL-88-20
def test_tc_spl_88_15_the_manager_can_also_read_the_venue_picker_list(app, client):
    """The calendar is useless to a role that cannot see venue names to choose between.

    SPL-88 widens the read-only `/api/venues` listing (id, name, location only) to the Event
    Operations Manager for this reason. Recorded here rather than in test_venues.py because the
    need comes from this story.
    """

    add_venue(app)

    response = client.get("/api/venues", headers=headers("manager"))

    assert response.status_code == 200, response.json
    assert [venue["name"] for venue in response.json["venues"]] == ["Harbour Hall"]
    # Unchanged for the roles the catalogue already served, and still closed to attendees.
    assert client.get("/api/venues", headers=headers("venue-staff")).status_code == 200
    assert client.get("/api/venues", headers=headers("coordinator")).status_code == 200
    assert client.get("/api/venues", headers=headers("attendee")).status_code == 403


# TC-SPL-88-20
def test_tc_spl_88_20_reasons_follow_the_shared_key_label_detail_shape(app, client):
    venue_id = add_venue(app)
    add_block(app, venue_id, slots=("PM",), reason="Ceiling repair")

    response = occupancy(client, venue_id)

    reason = slot_entry(response, "PM")["reasons"][0]
    assert set(reason) == {"key", "label", "detail"}
    assert reason["key"] == "block"
