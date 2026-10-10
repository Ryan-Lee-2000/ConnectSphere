"""Acceptance coverage for SPL-118 (CS-E19-S5): an attendee withdraws their registration.

Each test carries the QA-SPL-118 case identifier it proves. The cases were published on the
QA-SPL-118 page before this story's code existed. The race between two withdrawals of the same
registration (TC-SPL-118-07) needs two real transactions, so it lives in
test_event_registrations_postgres.py.

How to read these tests
-----------------------
- Every test builds its own fresh SQLite database with one Confirmed event on 20 Nov 2026 at
  18:00 Singapore time, whose registration (SPL-114) is open with 10 places.
- Registrations are made through SPL-116's real route (``register``), so each withdrawal acts on
  a registration exactly as an attendee would have created it.
- Sign-in is simulated: a token such as "attendee" maps to a known account id (``TOKENS``).
- The clock is frozen at ``NOW`` (20 Oct 2026, 12:00) through the single clock function in
  app/registration_settings.py; the "event has started" cases move it.
- Every refusal test checks that nothing changed, and also proves a genuine withdrawal succeeds
  in the same test, so a missing route could not make it pass.
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
from sqlalchemy import select
from sqlalchemy.orm import Session

ATTENDEE = "00000000-0000-0000-0000-000000001181"
SECOND_ATTENDEE = "00000000-0000-0000-0000-000000001182"
ORGANISER = "00000000-0000-0000-0000-000000001183"
COORDINATOR = "00000000-0000-0000-0000-000000001184"
MANAGER = "00000000-0000-0000-0000-000000001185"
TOKENS = {
    "attendee": ATTENDEE,
    "second-attendee": SECOND_ATTENDEE,
    "organiser": ORGANISER,
    "coordinator": COORDINATOR,
    "manager": MANAGER,
}
EVENT_DATE = date(2026, 11, 20)
# AC1's cut-off: the event's date and start time, in Singapore time.
EVENT_START = datetime(2026, 11, 20, 18, tzinfo=SINGAPORE)
OPENS = datetime(2026, 10, 10, 9, tzinfo=SINGAPORE)
CLOSES = datetime(2026, 11, 19, 18, tzinfo=SINGAPORE)
NOW = datetime(2026, 10, 20, 12, tzinfo=SINGAPORE)
DETAILS = {"name": "Avery Koh", "email": "avery@example.test", "contact_number": "+65 9123 4567"}


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setattr(settings_module, "_now", lambda: NOW)
    app = create_app(
        {
            "TESTING": True,
            "DATABASE_URL": f"sqlite:///{tmp_path}/registration-withdrawal.db",
            "IDENTITY_VERIFIER": TOKENS.__getitem__,
        }
    )
    engine = app.extensions["engine"]
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        organisation = Organisation(name="SPL-118 client")
        session.add(organisation)
        session.flush()
        for account_id, name, roles in (
            (ATTENDEE, "Avery Koh", [Role.ATTENDEE]),
            (SECOND_ATTENDEE, "Blake Ong", [Role.ATTENDEE]),
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


def make_event(app, *, capacity=10):
    """A Confirmed event at Harbour Hall, 20 Nov 18:00, with registration open (SPL-114)."""

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
            status="confirmed",
            registration_opens_at=OPENS,
            registration_closes_at=CLOSES,
            registration_capacity=capacity,
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


def register(client, event_id, token="attendee"):
    """Register through SPL-116's route and return the new registration's id."""

    response = client.post(
        f"/api/event-requests/{event_id}/registrations", json=DETAILS, headers=headers(token)
    )
    assert response.status_code == 201, response.json
    return response.json["registration"]["id"]


def withdraw(client, registration_id, token="attendee", **kwargs):
    return client.post(
        f"/api/registrations/{registration_id}/withdraw", headers=headers(token), **kwargs
    )


def stored(app, registration_id):
    """(status, withdrawn_at) as saved in the database."""

    with Session(app.extensions["engine"]) as session:
        row = session.get(EventRegistration, registration_id)
        return row.status, row.withdrawn_at


def set_clock(monkeypatch, moment):
    monkeypatch.setattr(settings_module, "_now", lambda: moment)


# AC1 — a Registered registration can be withdrawn before the event starts


# TC-SPL-118-01
# SPL-118 AC-1 Test-01
def test_tc_spl_118_01_attendee_withdraws_before_the_event_starts(app, client, event_id):
    registration_id = register(client, event_id)

    response = withdraw(client, registration_id)

    assert response.status_code == 200
    assert response.json["registration"]["id"] == registration_id
    assert response.json["registration"]["status"] == "withdrawn"


# AC2 — Withdrawn, the time recorded, and one more place


# TC-SPL-118-02
# SPL-118 AC-2 Test-02
def test_tc_spl_118_02_withdrawn_time_recorded_and_place_freed(app, client, event_id):
    registration_id = register(client, event_id)

    response = withdraw(client, registration_id)

    # The answer shows the new state and the event with its place back: 10 again, not 9.
    assert response.json["registration"]["withdrawn_at"] == "2026-10-20T12:00:00+08:00"
    assert response.json["event"]["places_remaining"] == 10
    status, withdrawn_at = stored(app, registration_id)
    assert status == "withdrawn"
    assert withdrawn_at is not None
    # The row is kept as history, not deleted.
    with Session(app.extensions["engine"]) as session:
        assert session.scalars(select(EventRegistration)).one().id == registration_id


# TC-SPL-118-03
# SPL-118 AC-2 Test-03
def test_tc_spl_118_03_the_freed_place_can_really_be_taken(app, client):
    event_id = make_event(app, capacity=1)
    first = register(client, event_id, "attendee")
    full = client.post(
        f"/api/event-requests/{event_id}/registrations",
        json=DETAILS,
        headers=headers("second-attendee"),
    )
    assert (full.status_code, full.json["error"]) == (409, "This event is full.")

    assert withdraw(client, first).status_code == 200

    # The place the first attendee gave up is usable by someone else straight away.
    register(client, event_id, "second-attendee")


# AC3 — refused, with nothing changed


# TC-SPL-118-04
# SPL-118 AC-3 Test-04
def test_tc_spl_118_04_withdrawing_twice_is_refused(app, client, event_id, monkeypatch):
    registration_id = register(client, event_id)
    first = withdraw(client, registration_id)
    assert first.status_code == 200
    recorded = stored(app, registration_id)

    # A minute later, the second attempt must not move the recorded time or free another place.
    set_clock(monkeypatch, NOW + timedelta(minutes=1))
    again = withdraw(client, registration_id)

    assert again.status_code == 409
    assert again.json["error"] == "This registration is already withdrawn."
    assert stored(app, registration_id) == recorded


# TC-SPL-118-05
# SPL-118 AC-3 Test-05
def test_tc_spl_118_05_no_withdrawal_once_the_event_has_started(app, client, event_id, monkeypatch):
    registration_id = register(client, event_id)

    # Exactly at the start time (and after it), the event has started: refused, nothing changes.
    for moment in (EVENT_START, EVENT_START + timedelta(hours=1)):
        set_clock(monkeypatch, moment)
        refused = withdraw(client, registration_id)
        assert refused.status_code == 409, moment
        assert refused.json["error"] == "This event has already started."
        assert stored(app, registration_id) == ("registered", None)

    # One minute before the start, it still succeeds.
    set_clock(monkeypatch, EVENT_START - timedelta(minutes=1))
    assert withdraw(client, registration_id).status_code == 200


# TC-SPL-118-06
# SPL-118 AC-3 Test-06
def test_tc_spl_118_06_only_your_own_registration(app, client, event_id):
    mine = register(client, event_id, "attendee")
    theirs = register(client, event_id, "second-attendee")

    # Someone else's registration answers exactly like one that does not exist, so an attendee
    # cannot discover other people's registrations by trying ids.
    for registration_id in (theirs, 999_999, 2**31):
        refused = withdraw(client, registration_id)
        assert refused.status_code == 404, registration_id
        assert refused.json["error"] == "Registration not found."
    assert stored(app, theirs) == ("registered", None)

    # Other roles are refused before anything is looked up; no session is 401.
    for token in ("organiser", "coordinator", "manager"):
        assert withdraw(client, mine, token).status_code == 403, token
    assert withdraw(client, mine, None).status_code == 401
    assert stored(app, mine) == ("registered", None)

    # And the attendee's own withdrawal succeeds in the same test.
    assert withdraw(client, mine).status_code == 200


# TC-SPL-118-06
# SPL-118 AC-3 Test-06
def test_tc_spl_118_06_the_client_cannot_set_the_outcome(app, client, event_id):
    registration_id = register(client, event_id)

    # The status and the time are server-owned: a body that tries to set them is refused.
    refused = withdraw(
        client, registration_id, json={"status": "registered", "withdrawn_at": "2020-01-01"}
    )

    assert refused.status_code == 400
    assert stored(app, registration_id) == ("registered", None)
    assert withdraw(client, registration_id, json={}).status_code == 200
