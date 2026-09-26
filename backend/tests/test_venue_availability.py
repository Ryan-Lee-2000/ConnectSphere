"""Acceptance coverage for SPL-71 venue availability search."""

from datetime import date, datetime, time, timezone

import pytest
from app import create_app
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
from sqlalchemy.orm import Session

COORDINATOR = "00000000-0000-0000-0000-000000000071"
OTHER_COORDINATOR = "00000000-0000-0000-0000-000000000072"
ORGANISER = "00000000-0000-0000-0000-000000000073"
VENUE_STAFF = "00000000-0000-0000-0000-000000000074"
TOKENS = {
    "coordinator": COORDINATOR,
    "other-coordinator": OTHER_COORDINATOR,
    "organiser": ORGANISER,
}
SEARCH_DATE = date(2026, 10, 12)


@pytest.fixture
def app(tmp_path):
    app = create_app(
        {
            "TESTING": True,
            "DATABASE_URL": f"sqlite:///{tmp_path}/availability.db",
            "IDENTITY_VERIFIER": TOKENS.__getitem__,
        }
    )
    engine = app.extensions["engine"]
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        organisation = Organisation(name="SPL-71 client")
        session.add(organisation)
        session.flush()
        for account_id, name, role in (
            (COORDINATOR, "Casey Coordinator", Role.EVENT_COORDINATOR),
            (OTHER_COORDINATOR, "Taylor Coordinator", Role.EVENT_COORDINATOR),
            (ORGANISER, "Devon Organiser", Role.EVENT_ORGANISER),
            (VENUE_STAFF, "Valerie Venue", Role.VENUE_STAFF),
        ):
            session.add(Account(id=account_id, display_name=name, organisation_id=organisation.id))
            session.add(AccountRole(account_id=account_id, role=role.value))
        event = EventRequest(
            organiser_account_id=ORGANISER,
            organisation_id=organisation.id,
            name="Community forum",
            purpose="Planning",
            proposed_date=SEARCH_DATE,
            start_time=time(7),
            end_time=time(18),
            expected_attendance=80,
            status="under_review",
        )
        session.add(event)
        session.flush()
        session.add(
            EventCoordinatorAssignment(
                event_request_id=event.id,
                coordinator_account_id=COORDINATOR,
                assigned_by_account_id=VENUE_STAFF,
                assigned_at=datetime.now(timezone.utc),
            )
        )
        session.commit()
        app.config["TEST_EVENT_ID"] = event.id
    yield app
    engine.dispose()


@pytest.fixture
def client(app):
    return app.test_client()


def headers(token="coordinator"):
    return {"Authorization": f"Bearer {token}"}


def add_venue(app, name, *, slots=("AM", "PM", "NIGHT"), setup=0, turnaround=0, capacity=100):
    with Session(app.extensions["engine"]) as session:
        venue = Venue(
            name=name,
            location="Singapore",
            operating_slots=list(slots),
            setup_buffer_slots=setup,
            turnaround_buffer_slots=turnaround,
        )
        venue.layouts = [VenueLayout(layout="theatre", capacity=capacity)]
        session.add(venue)
        session.commit()
        return venue.id


def search(client, event_id, query="date=2026-10-12&slot=AM&slot=PM", token="coordinator"):
    return client.get(
        f"/api/event-requests/{event_id}/available-venues?{query}", headers=headers(token)
    )


def test_tc_spl_71_01_finds_only_venues_available_for_every_selected_slot(app, client):
    available = add_venue(app, "Atlas Hall", capacity=180)
    booked = add_venue(app, "Booked Hall")
    blocked = add_venue(app, "Maintenance Hall")
    with Session(app.extensions["engine"]) as session:
        booking = VenueBooking(
            event_request_id=app.config["TEST_EVENT_ID"], venue_id=booked, status="requested"
        )
        session.add(booking)
        session.flush()
        session.add(
            VenueBookingOccupancy(
                booking_id=booking.id, venue_id=booked, day=SEARCH_DATE, slot="PM", kind="event"
            )
        )
        session.add(
            VenueOperationalBlock(
                venue_id=blocked,
                start_date=SEARCH_DATE,
                end_date=SEARCH_DATE,
                slots=["AM"],
                reason="Maintenance",
                created_by_account_id=VENUE_STAFF,
                created_at=datetime.now(timezone.utc),
            )
        )
        session.commit()

    response = search(client, app.config["TEST_EVENT_ID"])

    assert response.status_code == 200
    assert response.json == {
        "search": {"date": "2026-10-12", "slots": ["AM", "PM"]},
        "venues": [
            {
                "id": available,
                "name": "Atlas Hall",
                "location": "Singapore",
                "maximum_layout_capacity": 180,
            }
        ],
    }


def test_tc_spl_71_02_excludes_a_venue_when_its_required_adjacent_preparation_is_unavailable(
    app, client
):
    available = add_venue(app, "Ready Hall", slots=("AM", "PM", "NIGHT"), setup=1, turnaround=1)
    setup_conflict = add_venue(
        app, "Setup Conflict Hall", slots=("AM", "PM", "NIGHT"), setup=1, turnaround=1
    )
    with Session(app.extensions["engine"]) as session:
        booking = VenueBooking(
            event_request_id=app.config["TEST_EVENT_ID"], venue_id=setup_conflict, status="approved"
        )
        session.add(booking)
        session.flush()
        session.add(
            VenueBookingOccupancy(
                booking_id=booking.id,
                venue_id=setup_conflict,
                day=date(2026, 10, 11),
                slot="NIGHT",
                kind="turnaround",
            )
        )
        session.commit()

    response = search(client, app.config["TEST_EVENT_ID"], "date=2026-10-12&slot=AM")

    assert response.status_code == 200
    assert [venue["id"] for venue in response.json["venues"]] == [available]


# TC-SPL-71-09: buffer boundaries must be checked across a Singapore calendar day.
@pytest.mark.parametrize(
    ("event_slot", "setup", "turnaround", "block_day", "block_slot"),
    [
        ("AM", 1, 0, date(2026, 10, 11), "NIGHT"),
        ("NIGHT", 0, 1, date(2026, 10, 13), "AM"),
    ],
)
def test_tc_spl_71_09_excludes_venue_when_required_cross_day_buffer_is_blocked(
    app, client, event_slot, setup, turnaround, block_day, block_slot
):
    venue = add_venue(app, "Boundary Hall", setup=setup, turnaround=turnaround)
    with Session(app.extensions["engine"]) as session:
        session.add(
            VenueOperationalBlock(
                venue_id=venue,
                start_date=block_day,
                end_date=block_day,
                slots=[block_slot],
                reason="Required buffer unavailable",
                created_by_account_id=VENUE_STAFF,
                created_at=datetime.now(timezone.utc),
            )
        )
        session.commit()

    response = search(client, app.config["TEST_EVENT_ID"], f"date=2026-10-12&slot={event_slot}")

    assert response.status_code == 200
    assert response.json == {"search": {"date": "2026-10-12", "slots": [event_slot]}, "venues": []}


def test_tc_spl_71_03_keeps_applied_search_visible_when_no_venue_is_available(app, client):
    venue = add_venue(app, "Only Hall", slots=("AM",))
    with Session(app.extensions["engine"]) as session:
        booking = VenueBooking(
            event_request_id=app.config["TEST_EVENT_ID"], venue_id=venue, status="requested"
        )
        session.add(booking)
        session.flush()
        session.add(
            VenueBookingOccupancy(
                booking_id=booking.id, venue_id=venue, day=SEARCH_DATE, slot="AM", kind="event"
            )
        )
        session.commit()

    response = search(client, app.config["TEST_EVENT_ID"], "date=2026-10-12&slot=AM")

    assert response.status_code == 200
    assert response.json == {"search": {"date": "2026-10-12", "slots": ["AM"]}, "venues": []}


# TC-SPL-71-10: operational availability applies to selected slots and required buffers.
@pytest.mark.parametrize(
    ("venue_slots", "setup", "query"),
    [
        (("AM",), 0, "date=2026-10-12&slot=AM&slot=PM"),
        (("AM", "PM"), 1, "date=2026-10-12&slot=AM"),
    ],
)
def test_tc_spl_71_10_excludes_venue_when_operating_slots_cannot_cover_event_or_buffer(
    app, client, venue_slots, setup, query
):
    add_venue(app, "Limited Operating Hall", slots=venue_slots, setup=setup)

    response = search(client, app.config["TEST_EVENT_ID"], query)

    assert response.status_code == 200
    assert response.json["venues"] == []


@pytest.mark.parametrize(
    ("query", "message"),
    [
        ("slot=AM", "Search date is required."),
        ("date=12-10-2026&slot=AM", "Search date must use YYYY-MM-DD."),
        ("date=2026-10-12", "Select at least one operating slot."),
        ("date=2026-10-12&slot=DAY", "Search uses only AM, PM or NIGHT slots."),
        ("date=2026-10-12&slot=AM&slot=AM", "Operating slots must not contain duplicates."),
    ],
)
def test_tc_spl_71_04_refuses_invalid_search_parameters_without_searching(
    app, client, query, message
):
    response = search(client, app.config["TEST_EVENT_ID"], query)
    assert response.status_code == 400
    assert response.json == {"error": message}


def test_tc_spl_71_05_enforces_assigned_coordinator_access(app, client):
    event_id = app.config["TEST_EVENT_ID"]
    assert search(client, event_id, token="other-coordinator").status_code == 404
    assert search(client, event_id, token="organiser").status_code == 403
    unauthenticated = client.get(
        f"/api/event-requests/{event_id}/available-venues?date=2026-10-12&slot=AM"
    )
    assert unauthenticated.status_code == 401
