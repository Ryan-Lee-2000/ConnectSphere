"""Acceptance coverage for SPL-116 (CS-E19-S3): an attendee registers for an open event.

Each test carries the QA-SPL-116 case identifier it proves. The concurrency cases (TC-SPL-116-10
and -11) need two real transactions, so they live in test_event_registrations_postgres.py.

How to read these tests
-----------------------
- Every test builds its own fresh SQLite database (the ``app`` fixture), with one Confirmed event
  whose registration (SPL-114) is open from 10 Oct to 19 Nov 2026 and has 10 places.
- Sign-in is simulated: a token such as "attendee" maps to a known account id (``TOKENS``).
- The clock is frozen at ``NOW`` (20 Oct 2026, 12:00 Singapore time, inside the registration
  period) through the one clock function in app/registration_settings.py, which this story shares.
- Refusal tests check the status code and that nothing was saved, and also prove a genuine
  registration succeeds in the same test, so a missing route could not make them pass.
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
    EventRegistration,
    EventRequest,
    Organisation,
    Role,
    Venue,
    VenueBooking,
    VenueLayout,
)
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

ATTENDEE = "00000000-0000-0000-0000-000000001161"
SECOND_ATTENDEE = "00000000-0000-0000-0000-000000001162"
THIRD_ATTENDEE = "00000000-0000-0000-0000-000000001163"
ORGANISER_AND_ATTENDEE = "00000000-0000-0000-0000-000000001164"
ORGANISER = "00000000-0000-0000-0000-000000001165"
COORDINATOR = "00000000-0000-0000-0000-000000001166"
VENUE_STAFF = "00000000-0000-0000-0000-000000001167"
TECHNICAL_SUPPORT = "00000000-0000-0000-0000-000000001168"
MANAGER = "00000000-0000-0000-0000-000000001169"
TOKENS = {
    "attendee": ATTENDEE,
    "second-attendee": SECOND_ATTENDEE,
    "third-attendee": THIRD_ATTENDEE,
    "organiser-and-attendee": ORGANISER_AND_ATTENDEE,
    "organiser": ORGANISER,
    "coordinator": COORDINATOR,
    "venue-staff": VENUE_STAFF,
    "technical-support": TECHNICAL_SUPPORT,
    "manager": MANAGER,
}
EVENT_DATE = date(2026, 11, 20)
OPENS = datetime(2026, 10, 10, 9, tzinfo=SINGAPORE)
CLOSES = datetime(2026, 11, 19, 18, tzinfo=SINGAPORE)
# "Now" for every test unless a test moves the clock: inside the registration period.
NOW = datetime(2026, 10, 20, 12, tzinfo=SINGAPORE)
DETAILS = {"name": "Avery Koh", "email": "avery@example.test", "contact_number": "+65 9123 4567"}


@pytest.fixture
def app(tmp_path, monkeypatch):
    # One shared clock: SPL-114's ``_now`` decides what "open" means for this story too.
    monkeypatch.setattr(settings_module, "_now", lambda: NOW)
    app = create_app(
        {
            "TESTING": True,
            "DATABASE_URL": f"sqlite:///{tmp_path}/event-registrations.db",
            "IDENTITY_VERIFIER": TOKENS.__getitem__,
        }
    )
    engine = app.extensions["engine"]
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        organisation = Organisation(name="SPL-116 client")
        session.add(organisation)
        session.flush()
        for account_id, name, roles in (
            (ATTENDEE, "Avery Koh", [Role.ATTENDEE]),
            (SECOND_ATTENDEE, "Blake Ong", [Role.ATTENDEE]),
            (THIRD_ATTENDEE, "Cheryl Tan", [Role.ATTENDEE]),
            (ORGANISER_AND_ATTENDEE, "Devon Lee", [Role.EVENT_ORGANISER, Role.ATTENDEE]),
            (ORGANISER, "Erin Goh", [Role.EVENT_ORGANISER]),
            (COORDINATOR, "Casey Lim", [Role.EVENT_COORDINATOR]),
            (VENUE_STAFF, "Valerie Tan", [Role.VENUE_STAFF]),
            (TECHNICAL_SUPPORT, "Tara Ng", [Role.TECHNICAL_SUPPORT_STAFF]),
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


def make_event(app, *, capacity=10, status="confirmed", enabled=True):
    """A Confirmed event at Harbour Hall with registration open 10 Oct to 19 Nov (SPL-114)."""

    with Session(app.extensions["engine"]) as session:
        event = EventRequest(
            organiser_account_id=ORGANISER,
            organisation_id=app.config["ORGANISATION_ID"],
            name="Harbour Lights Gala",
            purpose="Annual fundraiser",
            description="An evening of music by the water.",
            proposed_date=EVENT_DATE,
            start_time=time(18),
            end_time=time(22),
            expected_attendance=150,
            status=status,
            registration_opens_at=OPENS if enabled else None,
            registration_closes_at=CLOSES if enabled else None,
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
        venue = Venue(
            name="Harbour Hall",
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
                event_request_id=event.id, venue_id=venue.id, status="approved", layout="theatre"
            )
        )
        session.commit()
        return event.id


@pytest.fixture
def event_id(app):
    return make_event(app)


def register(client, event_id, body=None, token="attendee"):
    return client.post(
        f"/api/event-requests/{event_id}/registrations",
        json=DETAILS if body is None else body,
        headers=headers(token),
    )


def registrations(app, event_id, status=None):
    """How many registrations the event has in the database, optionally of one status."""

    with Session(app.extensions["engine"]) as session:
        query = (
            select(func.count())
            .select_from(EventRegistration)
            .where(EventRegistration.event_request_id == event_id)
        )
        if status:
            query = query.where(EventRegistration.status == status)
        return session.scalar(query)


def set_clock(monkeypatch, moment):
    monkeypatch.setattr(settings_module, "_now", lambda: moment)


# AC1 — an open event with places: Registered, and places remaining drops by one


# TC-SPL-116-01
# SPL-116 AC-1 Test-01
def test_tc_spl_116_01_attendee_registers_and_takes_a_place(app, client, event_id):
    response = register(client, event_id)

    assert response.status_code == 201
    assert response.json["registration"]["status"] == "registered"
    assert response.json["event"]["places_remaining"] == 9
    with Session(app.extensions["engine"]) as session:
        saved = session.scalars(select(EventRegistration)).one()
        # Linked to the signed-in account and the event, never to ids sent by the browser.
        assert (saved.attendee_account_id, saved.event_request_id) == (ATTENDEE, event_id)
        assert saved.status == "registered"


# AC2 — required fields, the email format, and the optional special requirements


# TC-SPL-116-02
# SPL-116 AC-2 Test-02
@pytest.mark.parametrize("field", ["name", "email", "contact_number"])
@pytest.mark.parametrize("value", [None, "", "   "])
def test_tc_spl_116_02_each_required_field_is_named_when_missing(
    app, client, event_id, field, value
):
    body = {**DETAILS, field: value}
    if value is None:
        del body[field]

    response = register(client, event_id, body)

    assert response.status_code == 400
    assert response.json["field"] == field
    assert registrations(app, event_id) == 0


# TC-SPL-116-02
# SPL-116 AC-2 Test-02
@pytest.mark.parametrize(
    "body", [None, [], {**DETAILS, "status": "registered"}, {**DETAILS, "attendee_id": 1}]
)
def test_tc_spl_116_02_anything_but_the_four_details_is_refused(app, client, event_id, body):
    response = client.post(
        f"/api/event-requests/{event_id}/registrations", json=body, headers=headers()
    )

    assert response.status_code == 400
    assert registrations(app, event_id) == 0


# TC-SPL-116-03
# SPL-116 AC-2 Test-03
@pytest.mark.parametrize(
    ("email", "accepted"),
    [("a@b.co", True), ("ab.co", False), ("a@", False), ("@b.co", False), ("a b@c.co", False)],
)
def test_tc_spl_116_03_email_must_be_name_at_domain(app, client, event_id, email, accepted):
    response = register(client, event_id, {**DETAILS, "email": email})

    if accepted:
        assert response.status_code == 201
    else:
        assert response.status_code == 400
        assert response.json["field"] == "email"
        assert registrations(app, event_id) == 0


# TC-SPL-116-04
# SPL-116 AC-2 Test-04
@pytest.mark.parametrize(
    ("given", "stored"), [(None, None), ("", None), ("Wheelchair access", "Wheelchair access")]
)
def test_tc_spl_116_04_special_requirements_are_optional(app, client, event_id, given, stored):
    body = dict(DETAILS)
    if given is not None:
        body["special_requirements"] = given

    response = register(client, event_id, body)

    assert response.status_code == 201
    assert response.json["registration"]["special_requirements"] == stored


# AC3 — a full event is refused


# TC-SPL-116-05
# SPL-116 AC-3 Test-05
def test_tc_spl_116_05_the_last_place_is_taken_then_the_event_is_full(app, client):
    event_id = make_event(app, capacity=2)
    assert register(client, event_id, token="second-attendee").status_code == 201

    last_place = register(client, event_id)
    full = register(client, event_id, token="third-attendee")

    assert last_place.status_code == 201
    assert last_place.json["event"]["places_remaining"] == 0
    assert full.status_code == 409
    assert full.json["error"] == "This event is full."
    assert registrations(app, event_id) == 2


# AC4 — refused when registration is not open, or for anyone but a signed-in attendee


# TC-SPL-116-06
# SPL-116 AC-4 Test-06
@pytest.mark.parametrize(
    ("setup", "moment", "status"),
    [
        ({"enabled": False}, NOW, 404),  # never enabled: not a public event
        ({}, datetime(2026, 10, 10, 8, 59, tzinfo=SINGAPORE), 409),  # not yet open
        ({}, CLOSES, 409),  # exactly at the close
        ({}, datetime(2026, 11, 19, 19, tzinfo=SINGAPORE), 409),  # after the close
        ({"status": "postponed"}, NOW, 404),  # no longer Confirmed
        ({"status": "cancelled"}, NOW, 404),
    ],
)
def test_tc_spl_116_06_refused_while_registration_is_not_open(
    app, client, monkeypatch, setup, moment, status
):
    event_id = make_event(app, **setup)
    set_clock(monkeypatch, moment)

    response = register(client, event_id)

    assert response.status_code == status
    assert registrations(app, event_id) == 0
    # Not vacuous: an open event accepts the same attendee in the same test.
    set_clock(monkeypatch, NOW)
    assert register(client, make_event(app)).status_code == 201


# TC-SPL-116-06
# SPL-116 AC-4 Test-06
def test_tc_spl_116_06_one_minute_before_the_close_is_still_open(app, client, monkeypatch):
    event_id = make_event(app)
    set_clock(monkeypatch, datetime(2026, 11, 19, 17, 59, tzinfo=SINGAPORE))

    assert register(client, event_id).status_code == 201


# TC-SPL-116-06
# SPL-116 AC-4 Test-06
def test_tc_spl_116_06_a_hidden_event_and_an_unknown_event_look_the_same(app, client):
    hidden = register(client, make_event(app, enabled=False))
    unknown = register(client, 999999)
    out_of_range = register(client, 2**31)

    assert hidden.status_code == unknown.status_code == out_of_range.status_code == 404
    assert hidden.json == unknown.json == out_of_range.json


# TC-SPL-116-07
# SPL-116 AC-4 Test-07
@pytest.mark.parametrize(
    ("token", "status"),
    [
        (None, 401),
        ("organiser", 403),
        ("coordinator", 403),
        ("venue-staff", 403),
        ("technical-support", 403),
        ("manager", 403),
    ],
)
def test_tc_spl_116_07_only_signed_in_attendees_register(app, client, event_id, token, status):
    assert register(client, event_id, token=token).status_code == status
    assert registrations(app, event_id) == 0
    # Not vacuous: an attendee, and an organiser who is also an attendee, both succeed.
    assert register(client, event_id).status_code == 201
    assert register(client, event_id, token="organiser-and-attendee").status_code == 201


# AC5 — one Registered registration per attendee per event


# TC-SPL-116-08
# SPL-116 AC-5 Test-08
def test_tc_spl_116_08_a_second_registration_is_refused(app, client, event_id):
    assert register(client, event_id).status_code == 201

    again = register(client, event_id)

    assert again.status_code == 409
    assert again.json["error"] == "You are already registered for this event."
    assert registrations(app, event_id) == 1


# TC-SPL-116-09
# SPL-116 AC-5 Test-09
def test_tc_spl_116_09_after_withdrawing_the_attendee_can_register_again(app, client, event_id):
    assert register(client, event_id).status_code == 201
    # Withdrawn is set directly until SPL-118 adds the withdraw action.
    with Session(app.extensions["engine"]) as session:
        session.execute(update(EventRegistration).values(status="withdrawn"))
        session.commit()

    again = register(client, event_id)

    assert again.status_code == 201
    assert registrations(app, event_id, "registered") == 1
    assert registrations(app, event_id, "withdrawn") == 1  # the history is kept


# AC7 — the confirmation shows the event and the submitted details


# TC-SPL-116-12
# SPL-116 AC-7 Test-12
def test_tc_spl_116_12_the_confirmation_carries_the_event_and_the_details(app, client, event_id):
    response = register(client, event_id, {**DETAILS, "special_requirements": "Vegetarian meal"})

    assert response.json["event"] == {
        "id": event_id,
        "name": "Harbour Lights Gala",
        "description": "An evening of music by the water.",
        "date": "2026-11-20",
        "start_time": "18:00",
        "end_time": "22:00",
        "venues": ["Harbour Hall"],
        "places_remaining": 9,
    }
    registration = response.json["registration"]
    assert {key: registration[key] for key in ("name", "email", "contact_number")} == DETAILS
    assert registration["special_requirements"] == "Vegetarian meal"
    assert registration["registered_at"] == "2026-10-20T12:00:00+08:00"
