"""Acceptance coverage for SPL-115 (CS-E19-S2): an attendee sees the events open for registration.

Each test carries the QA-SPL-115 case identifier it proves. The cases were published on the
QA-SPL-115 page before this story's code existed.

How to read these tests
-----------------------
- Every test builds its own fresh SQLite database (the ``app`` fixture) with the same accounts
  SPL-116's tests use. Sign-in is simulated: a token such as "attendee" maps to an account id.
- ``make_event`` creates one event with the settings SPL-114 stores (open time, close time,
  capacity) and, by default, one Approved booking at Harbour Hall. Each test only changes what it
  is about.
- The clock is frozen at ``NOW`` (20 Oct 2026, 12:00 Singapore time) through the single clock
  function in app/registration_settings.py, so "is it open?" means the same thing here as when
  registering (SPL-116).
- Every "left out" test also checks that an open event in the same response *is* listed, so an
  empty list (or a missing route) can never make a test pass.
"""

from datetime import date, datetime, time, timedelta, timezone

import pytest
from app import create_app
from app import registration_settings as settings_module
from app.event_requests import SINGAPORE
from app.models import (
    Account,
    AccountRole,
    Base,
    EventCoordinatorAssignment,
    EventRegistration,
    EventRequest,
    Organisation,
    Role,
    Venue,
    VenueBooking,
    VenueLayout,
)
from sqlalchemy.orm import Session

ATTENDEE = "00000000-0000-0000-0000-000000001151"
SECOND_ATTENDEE = "00000000-0000-0000-0000-000000001152"
ORGANISER_AND_ATTENDEE = "00000000-0000-0000-0000-000000001153"
ORGANISER = "00000000-0000-0000-0000-000000001154"
COORDINATOR = "00000000-0000-0000-0000-000000001155"
VENUE_STAFF = "00000000-0000-0000-0000-000000001156"
TECHNICAL_SUPPORT = "00000000-0000-0000-0000-000000001157"
MANAGER = "00000000-0000-0000-0000-000000001158"
TOKENS = {
    "attendee": ATTENDEE,
    "second-attendee": SECOND_ATTENDEE,
    "organiser-and-attendee": ORGANISER_AND_ATTENDEE,
    "organiser": ORGANISER,
    "coordinator": COORDINATOR,
    "venue-staff": VENUE_STAFF,
    "technical-support": TECHNICAL_SUPPORT,
    "manager": MANAGER,
}
OPENS = datetime(2026, 10, 10, 9, tzinfo=SINGAPORE)
CLOSES = datetime(2026, 11, 19, 18, tzinfo=SINGAPORE)
# "Now" for every test unless a test moves the clock: inside the registration period.
NOW = datetime(2026, 10, 20, 12, tzinfo=SINGAPORE)
# AC3: the only fields an attendee may see. Asserted as an exact set, so adding any internal field
# (a coordinator, an organiser contact, a booking id) to the list makes TC-SPL-115-05 fail.
PUBLIC_FIELDS = {
    "id",
    "name",
    "description",
    "date",
    "start_time",
    "end_time",
    "venues",
    "places_remaining",
    "registered",
}


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setattr(settings_module, "_now", lambda: NOW)
    app = create_app(
        {
            "TESTING": True,
            "DATABASE_URL": f"sqlite:///{tmp_path}/open-registrations.db",
            "IDENTITY_VERIFIER": TOKENS.__getitem__,
        }
    )
    engine = app.extensions["engine"]
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        organisation = Organisation(name="SPL-115 client")
        session.add(organisation)
        session.flush()
        for account_id, name, roles in (
            (ATTENDEE, "Avery Koh", [Role.ATTENDEE]),
            (SECOND_ATTENDEE, "Blake Ong", [Role.ATTENDEE]),
            (ORGANISER_AND_ATTENDEE, "Devon Lee", [Role.EVENT_ORGANISER, Role.ATTENDEE]),
            (ORGANISER, "Erin Goh", [Role.EVENT_ORGANISER]),
            (COORDINATOR, "Casey Lim", [Role.EVENT_COORDINATOR]),
            (VENUE_STAFF, "Valerie Tan", [Role.VENUE_STAFF]),
            (TECHNICAL_SUPPORT, "Taylor Goh", [Role.TECHNICAL_SUPPORT_STAFF]),
            (MANAGER, "Morgan Ong", [Role.EVENT_OPERATIONS_MANAGER]),
        ):
            session.add(Account(id=account_id, display_name=name, organisation_id=organisation.id))
            for role in roles:
                session.add(AccountRole(account_id=account_id, role=role.value))
        session.commit()
        app.config["ORGANISATION_ID"] = organisation.id
    yield app
    engine.dispose()


@pytest.fixture
def client(app):
    return app.test_client()


def headers(token="attendee"):
    return {"Authorization": f"Bearer {token}"} if token else {}


def make_event(
    app,
    name,
    *,
    event_date=date(2026, 11, 20),
    start=time(18),
    status="confirmed",
    enabled=True,
    opens=OPENS,
    closes=CLOSES,
    capacity=10,
    bookings=(("Harbour Hall", "approved"),),
):
    """One event with SPL-114's registration settings and the given venue bookings."""

    with Session(app.extensions["engine"]) as session:
        event = EventRequest(
            organiser_account_id=ORGANISER,
            organisation_id=app.config["ORGANISATION_ID"],
            name=name,
            purpose="Internal purpose an attendee must never see",
            description=f"About {name}.",
            proposed_date=event_date,
            start_time=start,
            end_time=time(22),
            expected_attendance=150,
            status=status,
            registration_opens_at=opens if enabled else None,
            registration_closes_at=closes if enabled else None,
            registration_capacity=capacity if enabled else None,
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
        for venue_name, booking_status in bookings:
            venue = Venue(
                name=venue_name,
                location="Marina Centre",
                facilities=[],
                accessibility_features=[],
                operating_slots=["AM", "PM", "NIGHT"],
                setup_buffer_slots=0,
                turnaround_buffer_slots=0,
            )
            venue.layouts = [VenueLayout(layout="theatre", capacity=200)]
            session.add(venue)
            session.flush()
            session.add(
                VenueBooking(
                    event_request_id=event.id,
                    venue_id=venue.id,
                    status=booking_status,
                    layout="theatre",
                )
            )
        session.commit()
        return event.id


def add_registration(app, event_id, account_id, status="registered"):
    """A registration row, inserted directly so each test controls exactly who holds a place."""

    with Session(app.extensions["engine"]) as session:
        session.add(
            EventRegistration(
                event_request_id=event_id,
                attendee_account_id=account_id,
                status=status,
                name="Someone",
                email="someone@example.test",
                contact_number="+65 9000 0000",
                registered_at=NOW,
            )
        )
        session.commit()


def open_events(client, token="attendee"):
    return client.get("/api/open-events", headers=headers(token))


def names(response):
    return [event["name"] for event in response.json["events"]]


def set_clock(monkeypatch, moment):
    monkeypatch.setattr(settings_module, "_now", lambda: moment)


# AC1 — only Confirmed, enabled, currently open events, earliest event date first


# TC-SPL-115-01
# SPL-115 AC-1 Test-01
def test_tc_spl_115_01_an_open_confirmed_event_is_listed(app, client):
    make_event(app, "Harbour Lights Gala")

    response = open_events(client)

    assert response.status_code == 200
    assert names(response) == ["Harbour Lights Gala"]


# TC-SPL-115-02
# SPL-115 AC-1 Test-02
@pytest.mark.parametrize(
    "excluded,clock",
    [
        # Registration never enabled (SPL-114 AC5: off by default).
        ({"enabled": False}, NOW),
        # Enabled, but the opening time has not arrived yet.
        ({"opens": NOW + timedelta(days=1), "closes": CLOSES}, NOW),
        # Exactly at the closing time: the period has ended (open means before the close).
        ({"closes": NOW}, NOW),
        # After the closing time.
        ({"closes": NOW - timedelta(minutes=1)}, NOW),
        # No longer Confirmed, even though registration is still enabled and inside its period.
        ({"status": "postponed"}, NOW),
        ({"status": "cancelled"}, NOW),
        ({"status": "completed"}, NOW),
        ({"status": "planning"}, NOW),
    ],
    ids=[
        "never-enabled",
        "before-open",
        "at-close",
        "after-close",
        "postponed",
        "cancelled",
        "completed",
        "planning",
    ],
)
def test_tc_spl_115_02_events_not_open_are_left_out(app, client, monkeypatch, excluded, clock):
    make_event(app, "Open event")
    make_event(app, "Excluded event", **excluded)
    set_clock(monkeypatch, clock)

    response = open_events(client)

    # The open event is there, so the exclusion is a real decision, not an empty list.
    assert response.status_code == 200
    assert names(response) == ["Open event"]


# TC-SPL-115-02 (boundary)
# SPL-115 AC-1 Test-02
def test_tc_spl_115_02_one_minute_before_the_close_is_still_open(app, client, monkeypatch):
    make_event(app, "Closing soon", closes=NOW + timedelta(minutes=1))

    assert names(open_events(client)) == ["Closing soon"]
    set_clock(monkeypatch, NOW + timedelta(minutes=1))
    assert names(open_events(client)) == []


# TC-SPL-115-03
# SPL-115 AC-1 Test-03
def test_tc_spl_115_03_earliest_event_date_first_then_start_time(app, client):
    # Created out of order on purpose, so the list order cannot come from insertion order.
    make_event(app, "December dinner", event_date=date(2026, 12, 5))
    make_event(app, "November evening", event_date=date(2026, 11, 20), start=time(19))
    make_event(app, "November morning", event_date=date(2026, 11, 20), start=time(9))
    make_event(app, "October launch", event_date=date(2026, 10, 30))

    assert names(open_events(client)) == [
        "October launch",
        "November morning",
        "November evening",
        "December dinner",
    ]


# AC2 — public details and places remaining


# TC-SPL-115-04
# SPL-115 AC-2 Test-04
def test_tc_spl_115_04_public_details_and_places_remaining(app, client):
    event_id = make_event(
        app,
        "Harbour Lights Gala",
        bookings=(
            ("Harbour Hall", "approved"),
            ("Bayfront Room", "approved"),
            ("Requested Annex", "requested"),
            ("Rejected Pavilion", "rejected"),
        ),
    )
    # Capacity 10: three places taken, and two Withdrawn registrations that have freed theirs.
    for account_id in (ATTENDEE, SECOND_ATTENDEE, ORGANISER_AND_ATTENDEE):
        add_registration(app, event_id, account_id)
    for account_id in (VENUE_STAFF, MANAGER):
        add_registration(app, event_id, account_id, status="withdrawn")

    (event,) = open_events(client, "second-attendee").json["events"]

    assert event == {
        "id": event_id,
        "name": "Harbour Lights Gala",
        "description": "About Harbour Lights Gala.",
        "date": "2026-11-20",
        "start_time": "18:00",
        "end_time": "22:00",
        # Only the venues the event actually holds (Approved), A to Z.
        "venues": ["Bayfront Room", "Harbour Hall"],
        "places_remaining": 7,
        "registered": True,
    }


# AC3 — no internal information


# TC-SPL-115-05
# SPL-115 AC-3 Test-05
def test_tc_spl_115_05_only_the_public_fields_are_returned(app, client):
    make_event(app, "Harbour Lights Gala")

    response = open_events(client)
    (event,) = response.json["events"]

    # An exact key set: nothing internal can be added without this test failing.
    assert set(event) == PUBLIC_FIELDS
    # And the internal values themselves never appear anywhere in the response.
    body = response.get_data(as_text=True)
    for internal in ("Internal purpose", "Casey Lim", "Erin Goh", "theatre", "approved"):
        assert internal not in body


# AC4 — events the attendee is Registered for are marked


# TC-SPL-115-06
# SPL-115 AC-4 Test-06
def test_tc_spl_115_06_registered_events_are_marked(app, client):
    registered = make_event(app, "A: registered", event_date=date(2026, 11, 1))
    withdrew = make_event(app, "B: withdrew", event_date=date(2026, 11, 2))
    someone_else = make_event(app, "C: someone else", event_date=date(2026, 11, 3))
    add_registration(app, registered, ATTENDEE)
    add_registration(app, withdrew, ATTENDEE, status="withdrawn")
    add_registration(app, someone_else, SECOND_ATTENDEE)

    marks = {event["name"]: event["registered"] for event in open_events(client).json["events"]}

    assert marks == {"A: registered": True, "B: withdrew": False, "C: someone else": False}


# AC5 — signed-in Attendee accounts only


# TC-SPL-115-07
# SPL-115 AC-5 Test-07
def test_tc_spl_115_07_only_attendees_can_see_the_list(app, client):
    make_event(app, "Harbour Lights Gala")

    # Allowed: an attendee, and an organiser who also holds the Attendee role. Checking these in
    # the same test means a missing route cannot make the refusals below pass on their own.
    for token in ("attendee", "organiser-and-attendee"):
        response = open_events(client, token)
        assert response.status_code == 200, token
        assert names(response) == ["Harbour Lights Gala"]
    for token in ("organiser", "coordinator", "venue-staff", "technical-support", "manager"):
        assert open_events(client, token).status_code == 403, token
    assert open_events(client, None).status_code == 401


# AC1 and AC2 — a full event (pending the PO's answer)


# TC-SPL-115-08
# SPL-115 AC-1 Test-08
def test_tc_spl_115_08_a_full_event_stays_listed_with_no_places(app, client):
    # Pending PO: the working interpretation is that a full event stays, showing 0 places.
    event_id = make_event(app, "Sold out", capacity=2)
    add_registration(app, event_id, SECOND_ATTENDEE)
    add_registration(app, event_id, ORGANISER_AND_ATTENDEE)

    (event,) = open_events(client).json["events"]

    assert event["name"] == "Sold out"
    assert event["places_remaining"] == 0
