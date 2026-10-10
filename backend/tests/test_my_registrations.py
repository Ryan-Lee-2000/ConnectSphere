"""Acceptance coverage for SPL-117 (CS-E19-S4): an attendee sees their own registrations.

Each test carries the QA-SPL-117 case identifier it proves. The cases were published on the
QA-SPL-117 page before this story's code existed.

How to read these tests
-----------------------
- Every test builds its own fresh SQLite database (the ``app`` fixture). ``make_event`` creates a
  Confirmed event with open registration (SPL-114), and registrations are made and withdrawn
  through the real SPL-116 and SPL-118 routes, so the list reads rows exactly as attendees create
  them.
- Sign-in is simulated: a token such as "attendee" maps to a known account id (``TOKENS``).
- The clock is frozen at ``NOW`` (20 Oct 2026, 12:00 Singapore time) through the single clock
  function in app/registration_settings.py.
- "Changes after registering" (AC2, AC3) are made directly in the database, the way a
  coordinator's later edit or a cancellation would leave them.
"""

from datetime import date, datetime, time, timezone

import pytest
from app import create_app
from app import registration_settings as settings_module
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
    VenueLayout,
)
from sqlalchemy.orm import Session

ATTENDEE = "00000000-0000-0000-0000-000000001171"
SECOND_ATTENDEE = "00000000-0000-0000-0000-000000001172"
NO_REGISTRATIONS = "00000000-0000-0000-0000-000000001173"
ORGANISER = "00000000-0000-0000-0000-000000001174"
COORDINATOR = "00000000-0000-0000-0000-000000001175"
MANAGER = "00000000-0000-0000-0000-000000001176"
TOKENS = {
    "attendee": ATTENDEE,
    "second-attendee": SECOND_ATTENDEE,
    "no-registrations": NO_REGISTRATIONS,
    "organiser": ORGANISER,
    "coordinator": COORDINATOR,
    "manager": MANAGER,
}
OPENS = datetime(2026, 10, 10, 9, tzinfo=SINGAPORE)
CLOSES = datetime(2026, 11, 19, 18, tzinfo=SINGAPORE)
NOW = datetime(2026, 10, 20, 12, tzinfo=SINGAPORE)
DETAILS = {"name": "Avery Koh", "email": "avery@example.test", "contact_number": "+65 9123 4567"}
# AC4: the event fields an attendee may see. SPL-116's public view (the same allowlist SPL-115's
# list uses, without its per-attendee "registered" mark, which the registration's own status
# replaces here) plus the event's current status and its plain-language name (AC3). Asserted as an
# exact set, so adding any internal field makes TC-SPL-117-05 fail.
EVENT_FIELDS = {
    "id",
    "name",
    "description",
    "date",
    "start_time",
    "end_time",
    "venues",
    "places_remaining",
    "status",
    "status_label",
}
# The registration's own fields: what the attendee submitted, and when it was made and withdrawn.
REGISTRATION_FIELDS = {
    "id",
    "status",
    "name",
    "email",
    "contact_number",
    "special_requirements",
    "registered_at",
    "withdrawn_at",
}


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setattr(settings_module, "_now", lambda: NOW)
    app = create_app(
        {
            "TESTING": True,
            "DATABASE_URL": f"sqlite:///{tmp_path}/my-registrations.db",
            "IDENTITY_VERIFIER": TOKENS.__getitem__,
        }
    )
    engine = app.extensions["engine"]
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        organisation = Organisation(name="SPL-117 client")
        session.add(organisation)
        session.flush()
        for account_id, name, roles in (
            (ATTENDEE, "Avery Koh", [Role.ATTENDEE]),
            (SECOND_ATTENDEE, "Blake Ong", [Role.ATTENDEE]),
            (NO_REGISTRATIONS, "Cheryl Tan", [Role.ATTENDEE]),
            (ORGANISER, "Erin Goh", [Role.EVENT_ORGANISER]),
            (COORDINATOR, "Casey Lim", [Role.EVENT_COORDINATOR]),
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


def make_event(app, name, *, event_date=date(2026, 11, 20), start=time(18), venue="Harbour Hall"):
    """A Confirmed event with registration open (SPL-114) and one Approved booking."""

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
            status="confirmed",
            registration_opens_at=OPENS,
            registration_closes_at=CLOSES,
            registration_capacity=10,
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
        hall = Venue(
            name=venue,
            location="Marina Centre",
            facilities=[],
            accessibility_features=[],
            operating_slots=["AM", "PM", "NIGHT"],
            setup_buffer_slots=0,
            turnaround_buffer_slots=0,
        )
        hall.layouts = [VenueLayout(layout="theatre", capacity=200)]
        session.add(hall)
        session.flush()
        session.add(
            VenueBooking(
                event_request_id=event.id, venue_id=hall.id, status="approved", layout="theatre"
            )
        )
        session.commit()
        return event.id


def register(client, event_id, token="attendee"):
    """Register through SPL-116's route; return the registration id."""

    response = client.post(
        f"/api/event-requests/{event_id}/registrations", json=DETAILS, headers=headers(token)
    )
    assert response.status_code == 201, response.json
    return response.json["registration"]["id"]


def withdraw(client, registration_id, token="attendee"):
    """Withdraw through SPL-118's route."""

    response = client.post(f"/api/registrations/{registration_id}/withdraw", headers=headers(token))
    assert response.status_code == 200, response.json


def my_registrations(client, token="attendee"):
    return client.get("/api/my-registrations", headers=headers(token))


def open_registration(client, registration_id, token="attendee"):
    return client.get(f"/api/my-registrations/{registration_id}", headers=headers(token))


def update_event(app, event_id, **changes):
    with Session(app.extensions["engine"]) as session:
        event = session.get(EventRequest, event_id)
        for field, value in changes.items():
            setattr(event, field, value)
        session.commit()


# AC1 — Registered and Withdrawn registrations, with event details, soonest first


# TC-SPL-117-01
# SPL-117 AC-1 Test-01
def test_tc_spl_117_01_every_registration_with_its_event_soonest_first(app, client):
    # Created out of order on purpose, so the order cannot come from insertion order.
    december = make_event(app, "December dinner", event_date=date(2026, 12, 5), venue="Atrium")
    october = make_event(app, "October launch", event_date=date(2026, 10, 30))
    november = make_event(app, "November talk", event_date=date(2026, 11, 20), start=time(9))
    for event_id in (december, october, november):
        register(client, event_id)

    response = my_registrations(client)

    assert response.status_code == 200
    entries = response.json["registrations"]
    assert [entry["event"]["name"] for entry in entries] == [
        "October launch",
        "November talk",
        "December dinner",
    ]
    first = entries[0]
    assert first["registration"]["status"] == "registered"
    assert {key: first["event"][key] for key in ("date", "start_time", "end_time", "venues")} == {
        "date": "2026-10-30",
        "start_time": "18:00",
        "end_time": "22:00",
        "venues": ["Harbour Hall"],
    }
    assert entries[2]["event"]["venues"] == ["Atrium"]


# TC-SPL-117-02
# SPL-117 AC-1 Test-02
def test_tc_spl_117_02_a_withdrawn_registration_is_listed_not_hidden(app, client):
    kept = register(client, make_event(app, "Kept", event_date=date(2026, 11, 1)))
    withdrawn = register(client, make_event(app, "Withdrawn from", event_date=date(2026, 11, 2)))
    withdraw(client, withdrawn)

    entries = my_registrations(client).json["registrations"]

    listed = [(entry["registration"]["id"], entry["registration"]["status"]) for entry in entries]
    assert listed == [(kept, "registered"), (withdrawn, "withdrawn")]
    assert entries[1]["registration"]["withdrawn_at"] == "2026-10-20T12:00:00+08:00"


# AC2 — the event's current details, read when the list is opened


# TC-SPL-117-03
# SPL-117 AC-2 Test-03
def test_tc_spl_117_03_changes_after_registering_are_shown(app, client):
    event_id = make_event(app, "Harbour Lights Gala")
    register(client, event_id)
    update_event(
        app,
        event_id,
        proposed_date=date(2026, 11, 27),
        start_time=time(19),
        end_time=time(23),
        description="Moved by a week, and now starts at seven.",
    )

    (entry,) = my_registrations(client).json["registrations"]

    assert {
        key: entry["event"][key] for key in ("date", "start_time", "end_time", "description")
    } == {
        "date": "2026-11-27",
        "start_time": "19:00",
        "end_time": "23:00",
        "description": "Moved by a week, and now starts at seven.",
    }


# AC3 — the event's current status when it is no longer Confirmed


# TC-SPL-117-04
# SPL-117 AC-3 Test-04
@pytest.mark.parametrize(
    "status,label",
    [("confirmed", "Confirmed"), ("cancelled", "Cancelled"), ("postponed", "Postponed")],
)
def test_tc_spl_117_04_the_events_current_status_is_shown(app, client, status, label):
    event_id = make_event(app, "Harbour Lights Gala")
    registration_id = register(client, event_id)
    update_event(app, event_id, status=status)

    (entry,) = my_registrations(client).json["registrations"]
    opened = open_registration(client, registration_id).json

    for event in (entry["event"], opened["event"]):
        assert (event["status"], event["status_label"]) == (status, label)
    # The registration itself is untouched: still Registered, kept as a record (SPL-86 AC6).
    assert entry["registration"]["status"] == "registered"


# AC4 — opening a registration shows public details only


# TC-SPL-117-05
# SPL-117 AC-4 Test-05
def test_tc_spl_117_05_opening_one_shows_only_public_details(app, client):
    registration_id = register(client, make_event(app, "Harbour Lights Gala"))

    response = open_registration(client, registration_id)

    assert response.status_code == 200
    # Exact key sets: nothing internal can be added without this test failing.
    assert set(response.json["event"]) == EVENT_FIELDS
    assert set(response.json["registration"]) == REGISTRATION_FIELDS
    assert response.json["registration"]["email"] == DETAILS["email"]
    # The same holds for every entry in the list.
    (entry,) = my_registrations(client).json["registrations"]
    assert set(entry["event"]) == EVENT_FIELDS
    body = response.get_data(as_text=True) + my_registrations(client).get_data(as_text=True)
    for internal in ("Internal purpose", "Casey Lim", "Erin Goh", "theatre", "approved"):
        assert internal not in body


# AC5 — only the attendee's own registrations


# TC-SPL-117-06
# SPL-117 AC-5 Test-06
def test_tc_spl_117_06_only_your_own_registrations(app, client):
    event_id = make_event(app, "Harbour Lights Gala")
    mine = register(client, event_id, "attendee")
    theirs = register(client, event_id, "second-attendee")

    mine_listed = [
        entry["registration"]["id"] for entry in my_registrations(client).json["registrations"]
    ]
    theirs_listed = [
        entry["registration"]["id"]
        for entry in my_registrations(client, "second-attendee").json["registrations"]
    ]

    assert (mine_listed, theirs_listed) == ([mine], [theirs])
    # Opening someone else's registration answers exactly like one that does not exist.
    assert open_registration(client, mine).status_code == 200
    for registration_id in (theirs, 999_999, 2**31):
        refused = open_registration(client, registration_id)
        assert refused.status_code == 404, registration_id
        assert refused.json["error"] == "Registration not found."


# TC-SPL-117-07
# SPL-117 AC-5 Test-07
def test_tc_spl_117_07_attendees_only_and_an_empty_list(app, client):
    registration_id = register(client, make_event(app, "Harbour Lights Gala"))

    # An attendee with no registrations gets an empty list, not an error.
    empty = my_registrations(client, "no-registrations")
    assert (empty.status_code, empty.json) == (200, {"registrations": []})
    # And the attendee with one sees it, so the refusals below cannot pass on a missing route.
    assert len(my_registrations(client).json["registrations"]) == 1

    for token in ("organiser", "coordinator", "manager"):
        assert my_registrations(client, token).status_code == 403, token
        assert open_registration(client, registration_id, token).status_code == 403, token
    assert my_registrations(client, None).status_code == 401
    assert open_registration(client, registration_id, None).status_code == 401
