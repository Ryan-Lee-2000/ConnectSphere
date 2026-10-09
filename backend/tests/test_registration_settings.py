"""Acceptance coverage for SPL-114 (CS-E19-S1): enable registration for a Confirmed event.

Each test carries the QA-SPL-114 case identifier it proves. Expected values come from the story's
acceptance criteria and the working interpretations recorded in docs/tasks/SPL-114.md: with several
Approved bookings the largest booked layout caps capacity, and registration can be enabled whatever
the organiser's "registration required" answer was.

How to read these tests
-----------------------
- Every test builds its own fresh SQLite database (the ``app`` fixture), so tests never affect each
  other and can run in any order.
- Sign-in is simulated: a token such as "coordinator" maps to a known account id (``TOKENS``), and
  each account holds exactly one role, so every role's behaviour can be checked separately.
- The clock is frozen at ``NOW`` (7 Oct 2026, 09:00 Singapore time), and some tests move it, so
  every "is registration open yet?" answer is exact and repeatable.
- Every refusal test checks two things: the status code, and that the database is unchanged
  (``stored`` returns the saved settings and the history count).
- Refusal tests also prove a genuine success in the same test. If the route were missing, every
  call would be refused and a refusal-only test would pass for the wrong reason. This was checked:
  with the routes removed, all 61 cases fail.
"""

from datetime import date, datetime, time, timezone

import pytest
from app import create_app
from app import registration_settings as settings_module
from app.event_requests import SINGAPORE
from app.event_statuses import EVENT_REQUEST_STATUSES
from app.models import (
    Account,
    AccountRole,
    Base,
    EventCoordinatorAssignment,
    EventRegistration,
    EventRequest,
    Organisation,
    RegistrationSettingsChange,
    Role,
    Venue,
    VenueBooking,
    VenueLayout,
)
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

COORDINATOR = "00000000-0000-0000-0000-000000001141"
OTHER_COORDINATOR = "00000000-0000-0000-0000-000000001142"
ORGANISER = "00000000-0000-0000-0000-000000001143"
VENUE_STAFF = "00000000-0000-0000-0000-000000001144"
MANAGER = "00000000-0000-0000-0000-000000001145"
TECHNICAL_SUPPORT = "00000000-0000-0000-0000-000000001146"
ATTENDEE = "00000000-0000-0000-0000-000000001147"
TOKENS = {
    "coordinator": COORDINATOR,
    "other-coordinator": OTHER_COORDINATOR,
    "organiser": ORGANISER,
    "venue-staff": VENUE_STAFF,
    "manager": MANAGER,
    "technical-support": TECHNICAL_SUPPORT,
    "attendee": ATTENDEE,
}
EVENT_DATE = date(2026, 11, 20)
EVENT_START = time(18)
# "Now" for every test unless a test moves the clock: well before the event.
NOW = datetime(2026, 10, 7, 9, 0, tzinfo=SINGAPORE)
VALID = {"opens_at": "2026-10-10T09:00", "closes_at": "2026-11-19T18:00", "capacity": 100}


@pytest.fixture
def app(tmp_path, monkeypatch):
    # Freeze the clock: the module reads the time only through ``_now``.
    monkeypatch.setattr(settings_module, "_now", lambda: NOW)
    app = create_app(
        {
            "TESTING": True,
            "DATABASE_URL": f"sqlite:///{tmp_path}/registration-settings.db",
            "IDENTITY_VERIFIER": TOKENS.__getitem__,
        }
    )
    engine = app.extensions["engine"]
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        organisation = Organisation(name="SPL-114 client")
        session.add(organisation)
        session.flush()
        for account_id, name, role in (
            (COORDINATOR, "Casey Lim", Role.EVENT_COORDINATOR),
            (OTHER_COORDINATOR, "Taylor Tan", Role.EVENT_COORDINATOR),
            (ORGANISER, "Devon Lee", Role.EVENT_ORGANISER),
            (VENUE_STAFF, "Valerie Tan", Role.VENUE_STAFF),
            (MANAGER, "Morgan Ong", Role.EVENT_OPERATIONS_MANAGER),
            (TECHNICAL_SUPPORT, "Tara Ng", Role.TECHNICAL_SUPPORT_STAFF),
            (ATTENDEE, "Avery Koh", Role.ATTENDEE),
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


def headers(token="coordinator"):
    return {"Authorization": f"Bearer {token}"} if token else {}


def make_event(app, *, status="confirmed", registration_required=True, name="Harbour Lights Gala"):
    """A Confirmed event assigned to COORDINATOR, starting 20 Nov 2026 at 18:00 Singapore time."""

    with Session(app.extensions["engine"]) as session:
        event = EventRequest(
            organiser_account_id=ORGANISER,
            organisation_id=app.config["ORGANISATION_ID"],
            name=name,
            purpose="Annual fundraiser",
            proposed_date=EVENT_DATE,
            start_time=EVENT_START,
            end_time=time(22),
            expected_attendance=150,
            registration_required=registration_required,
            status=status,
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


def add_booking(app, event_id, *, capacity=120, status="approved", name="Harbour Hall"):
    """A booking of the event on its own venue, whose booked layout holds ``capacity``."""

    with Session(app.extensions["engine"]) as session:
        venue = Venue(
            name=name,
            location="Marina Centre",
            facilities=[],
            accessibility_features=[],
            operating_slots=["AM", "PM", "NIGHT"],
            setup_buffer_slots=0,
            turnaround_buffer_slots=0,
        )
        venue.layouts = [VenueLayout(layout="theatre", capacity=capacity)]
        session.add(venue)
        session.flush()
        session.add(
            VenueBooking(
                event_request_id=event_id,
                venue_id=venue.id,
                status=status,
                layout="theatre",
                expected_attendance=150,
                booking_date=EVENT_DATE,
            )
        )
        session.commit()


@pytest.fixture
def event_id(app):
    event_id = make_event(app)
    add_booking(app, event_id)
    return event_id


def save(client, event_id, body, token="coordinator"):
    return client.put(
        f"/api/event-requests/{event_id}/registration", json=body, headers=headers(token)
    )


def read(client, event_id, token="coordinator"):
    return client.get(f"/api/event-requests/{event_id}/registration", headers=headers(token))


def stored(app, event_id):
    """The event's saved settings and history count, straight from the database."""

    with Session(app.extensions["engine"]) as session:
        event = session.get(EventRequest, event_id)
        changes = session.scalar(
            select(func.count())
            .select_from(RegistrationSettingsChange)
            .where(RegistrationSettingsChange.event_request_id == event_id)
        )
        return (
            event.registration_opens_at,
            event.registration_closes_at,
            event.registration_capacity,
            changes,
        )


def set_status(app, event_id, status):
    with Session(app.extensions["engine"]) as session:
        session.execute(
            update(EventRequest).where(EventRequest.id == event_id).values(status=status)
        )
        session.commit()


# AC1 — the assigned coordinator enables registration on a Confirmed event


# TC-SPL-114-01
# SPL-114 AC-1 Test-01
def test_tc_spl_114_01_assigned_coordinator_enables_registration(app, client, event_id):
    response = save(client, event_id, VALID)

    assert response.status_code == 200
    registration = response.json["registration"]
    assert registration["enabled"] is True
    assert registration["opens_at"] == "2026-10-10T09:00:00+08:00"
    assert registration["closes_at"] == "2026-11-19T18:00:00+08:00"
    assert registration["capacity"] == 100
    assert read(client, event_id).json["registration"] == registration


# TC-SPL-114-18
# SPL-114 AC-1 Test-18 (working interpretation, pending PO)
def test_tc_spl_114_18_enabling_ignores_the_organisers_registration_answer(app, client):
    event_id = make_event(app, registration_required=False)
    add_booking(app, event_id)

    assert save(client, event_id, VALID).status_code == 200


# AC2 — open before close, close before the event starts


# TC-SPL-114-02
# SPL-114 AC-2 Test-02
@pytest.mark.parametrize("opens_at", ["2026-11-19T18:00", "2026-11-19T19:00"])
def test_tc_spl_114_02_open_must_be_before_close(app, client, event_id, opens_at):
    response = save(client, event_id, {**VALID, "opens_at": opens_at})

    assert response.status_code == 400
    assert response.json["error"] == "Registration must open before it closes."
    assert stored(app, event_id) == (None, None, None, 0)


# TC-SPL-114-03
# SPL-114 AC-2 Test-03
@pytest.mark.parametrize("closes_at", ["2026-11-20T18:00", "2026-11-20T18:01", "2026-11-21T09:00"])
def test_tc_spl_114_03_close_must_be_before_the_event_starts(app, client, event_id, closes_at):
    response = save(client, event_id, {**VALID, "closes_at": closes_at})

    assert response.status_code == 400
    assert response.json["error"] == "Registration must close before the event starts."
    assert response.json["field"] == "closes_at"
    assert stored(app, event_id) == (None, None, None, 0)


# TC-SPL-114-03
# SPL-114 AC-2 Test-03
def test_tc_spl_114_03_one_minute_before_the_start_is_accepted(app, client, event_id):
    response = save(client, event_id, {**VALID, "closes_at": "2026-11-20T17:59"})

    assert response.status_code == 200
    assert response.json["registration"]["closes_at"] == "2026-11-20T17:59:00+08:00"


# TC-SPL-114-03
# SPL-114 AC-2 Test-03
def test_tc_spl_114_03_an_offset_time_is_read_in_its_own_zone(app, client, event_id):
    # 10:00 UTC is 18:00 in Singapore: exactly the event start, so it must be refused.
    refused = save(client, event_id, {**VALID, "closes_at": "2026-11-20T10:00:00+00:00"})
    accepted = save(client, event_id, {**VALID, "closes_at": "2026-11-20T09:59:00Z"})

    assert refused.status_code == 400
    assert accepted.status_code == 200
    assert accepted.json["registration"]["closes_at"] == "2026-11-20T17:59:00+08:00"


# TC-SPL-114-04
# SPL-114 AC-2 Test-04
@pytest.mark.parametrize(
    ("change", "field"),
    [
        ({"opens_at": None}, "opens_at"),
        ({"closes_at": None}, "closes_at"),
        ({"capacity": None}, "capacity"),
        ({"opens_at": "next Tuesday"}, "opens_at"),
        ({"closes_at": "2026-13-40T25:00"}, "closes_at"),
        ({"opens_at": 1760000000}, "opens_at"),
    ],
)
def test_tc_spl_114_04_missing_or_malformed_settings_name_the_field(
    app, client, event_id, change, field
):
    body = {**VALID, **change}
    if next(iter(change.values())) is None:
        del body[field]

    response = save(client, event_id, body)

    assert response.status_code == 400
    assert response.json["field"] == field
    assert stored(app, event_id) == (None, None, None, 0)


# TC-SPL-114-04
# SPL-114 AC-2 Test-04
@pytest.mark.parametrize("body", [None, [], {**VALID, "enabled": False}, {**VALID, "status": "x"}])
def test_tc_spl_114_04_anything_but_the_three_settings_is_refused(app, client, event_id, body):
    response = client.put(
        f"/api/event-requests/{event_id}/registration", json=body, headers=headers()
    )

    assert response.status_code == 400
    assert stored(app, event_id) == (None, None, None, 0)


# AC3 — capacity from 1 up to the booked layout's capacity


# TC-SPL-114-05
# SPL-114 AC-3 Test-05
@pytest.mark.parametrize(
    ("capacity", "accepted"),
    [
        (0, False),
        (-1, False),
        (1, True),
        (120, True),
        (121, False),
        (2.5, False),
        ("ten", False),
        (True, False),
    ],
)
def test_tc_spl_114_05_capacity_boundaries(app, client, event_id, capacity, accepted):
    response = save(client, event_id, {**VALID, "capacity": capacity})

    if accepted:
        assert response.status_code == 200
        assert response.json["registration"]["capacity"] == capacity
    else:
        assert response.status_code == 400
        assert response.json["field"] == "capacity"
        assert stored(app, event_id) == (None, None, None, 0)


# TC-SPL-114-05
# SPL-114 AC-3 Test-05
def test_tc_spl_114_05_over_capacity_names_the_layout_limit(app, client, event_id):
    response = save(client, event_id, {**VALID, "capacity": 121})

    assert response.json["error"] == (
        "Registration capacity cannot be more than 120, the booked layout's capacity."
    )


# TC-SPL-114-06
# SPL-114 AC-3 Test-06
@pytest.mark.parametrize("booking_statuses", [[], ["requested"], ["rejected", "withdrawn"]])
def test_tc_spl_114_06_no_approved_booking_means_no_capacity_to_cap(app, client, booking_statuses):
    event_id = make_event(app)
    for index, status in enumerate(booking_statuses):
        add_booking(app, event_id, status=status, name=f"Hall {index}")

    response = save(client, event_id, VALID)

    assert response.status_code == 409
    assert response.json["error"] == (
        "Registration needs an Approved venue booking to set its capacity against."
    )
    assert stored(app, event_id) == (None, None, None, 0)


# TC-SPL-114-07
# SPL-114 AC-3 Test-07 (working interpretation, pending PO)
def test_tc_spl_114_07_largest_approved_layout_caps_and_capacities_never_add_up(app, client):
    event_id = make_event(app)
    add_booking(app, event_id, capacity=80, name="Breakout Room")
    add_booking(app, event_id, capacity=200, name="Grand Ballroom")
    add_booking(app, event_id, capacity=500, status="rejected", name="Expo Hall")

    assert save(client, event_id, {**VALID, "capacity": 200}).status_code == 200
    assert save(client, event_id, {**VALID, "capacity": 201}).status_code == 400
    assert save(client, event_id, {**VALID, "capacity": 280}).status_code == 400
    assert read(client, event_id).json["registration"]["max_capacity"] == 200


# AC4 — settings can be changed later


# TC-SPL-114-08
# SPL-114 AC-4 Test-08
def test_tc_spl_114_08_a_valid_change_is_saved_and_an_invalid_one_keeps_the_old(
    app, client, event_id
):
    save(client, event_id, VALID)
    before = stored(app, event_id)

    refused = save(client, event_id, {**VALID, "closes_at": "2026-11-21T09:00"})
    assert refused.status_code == 400
    assert stored(app, event_id) == before

    changed = save(
        client,
        event_id,
        {"opens_at": "2026-10-12T09:00", "closes_at": "2026-11-18T12:00", "capacity": 90},
    )
    assert changed.status_code == 200
    registration = changed.json["registration"]
    assert (registration["opens_at"], registration["closes_at"], registration["capacity"]) == (
        "2026-10-12T09:00:00+08:00",
        "2026-11-18T12:00:00+08:00",
        90,
    )


# TC-SPL-114-09
# SPL-114 AC-4 Test-09
def test_tc_spl_114_09_a_later_close_after_the_close_has_passed_reopens(
    app, client, event_id, monkeypatch
):
    save(client, event_id, {**VALID, "closes_at": "2026-11-01T18:00"})
    monkeypatch.setattr(settings_module, "_now", lambda: datetime(2026, 11, 5, tzinfo=SINGAPORE))
    assert read(client, event_id).json["registration"]["state"] == "closed"

    response = save(client, event_id, {**VALID, "closes_at": "2026-11-15T18:00"})

    assert response.status_code == 200
    assert response.json["registration"]["state"] == "open"


# TC-SPL-114-10 (runs from SPL-116 onward, which creates registrations)
# SPL-114 AC-4 Test-10
def test_tc_spl_114_10_capacity_never_goes_below_those_registered(app, client, event_id):
    save(client, event_id, VALID)
    # Three accounts Registered (only one Registered row per account is allowed), one Withdrawn.
    with Session(app.extensions["engine"]) as session:
        for index, (account_id, status) in enumerate(
            (
                (ATTENDEE, "registered"),
                (ORGANISER, "registered"),
                (VENUE_STAFF, "registered"),
                (MANAGER, "withdrawn"),
            )
        ):
            session.add(
                EventRegistration(
                    event_request_id=event_id,
                    attendee_account_id=account_id,
                    status=status,
                    name=f"Attendee {index}",
                    email=f"attendee{index}@example.test",
                    contact_number="+65 9000 0000",
                    registered_at=NOW,
                )
            )
        session.commit()

    below = save(client, event_id, {**VALID, "capacity": 2})
    equal = save(client, event_id, {**VALID, "capacity": 3})

    assert below.status_code == 400
    assert below.json["field"] == "capacity"
    assert below.json["error"] == (
        "Registration capacity cannot be lower than the 3 attendees already registered."
    )
    # Withdrawn registrations free their place, so 3 (not 4) is the floor.
    assert equal.status_code == 200
    assert equal.json["registration"]["capacity"] == 3


# AC5 — off by default; closed until enabled and the open time is reached


# TC-SPL-114-11
# SPL-114 AC-5 Test-11
def test_tc_spl_114_11_registration_is_off_until_enabled(app, client, event_id):
    registration = read(client, event_id).json["registration"]

    assert registration["enabled"] is False
    assert registration["state"] == "off"
    assert (registration["opens_at"], registration["closes_at"], registration["capacity"]) == (
        None,
        None,
        None,
    )
    assert registration["history"] == []


# TC-SPL-114-12
# SPL-114 AC-5 Test-12
@pytest.mark.parametrize(
    ("now", "state"),
    [
        (datetime(2026, 10, 10, 8, 59, tzinfo=SINGAPORE), "not_yet_open"),
        (datetime(2026, 10, 10, 9, 0, tzinfo=SINGAPORE), "open"),
        (datetime(2026, 11, 19, 17, 59, tzinfo=SINGAPORE), "open"),
        (datetime(2026, 11, 19, 18, 0, tzinfo=SINGAPORE), "closed"),
    ],
)
def test_tc_spl_114_12_state_follows_the_clock(app, client, event_id, monkeypatch, now, state):
    save(client, event_id, VALID)
    monkeypatch.setattr(settings_module, "_now", lambda: now)

    assert read(client, event_id).json["registration"]["state"] == state


# AC6 — old and new settings, who and when recorded


# TC-SPL-114-13
# SPL-114 AC-6 Test-13
def test_tc_spl_114_13_each_save_records_old_new_who_and_when(app, client, event_id, monkeypatch):
    save(client, event_id, VALID)
    later = datetime(2026, 10, 8, 14, 30, tzinfo=SINGAPORE)
    monkeypatch.setattr(settings_module, "_now", lambda: later)
    save(client, event_id, {**VALID, "capacity": 90})

    history = read(client, event_id).json["registration"]["history"]

    assert history == [
        {
            "previous": {
                "opens_at": "2026-10-10T09:00:00+08:00",
                "closes_at": "2026-11-19T18:00:00+08:00",
                "capacity": 100,
            },
            "current": {
                "opens_at": "2026-10-10T09:00:00+08:00",
                "closes_at": "2026-11-19T18:00:00+08:00",
                "capacity": 90,
            },
            "changed_by": {"id": COORDINATOR, "name": "Casey Lim"},
            "changed_at": "2026-10-08T14:30:00+08:00",
        },
        {
            "previous": None,
            "current": {
                "opens_at": "2026-10-10T09:00:00+08:00",
                "closes_at": "2026-11-19T18:00:00+08:00",
                "capacity": 100,
            },
            "changed_by": {"id": COORDINATOR, "name": "Casey Lim"},
            "changed_at": "2026-10-07T09:00:00+08:00",
        },
    ]


# TC-SPL-114-14
# SPL-114 AC-6 Test-14
def test_tc_spl_114_14_refused_attempts_leave_the_history_unchanged(app, client, event_id):
    save(client, event_id, VALID)
    before = stored(app, event_id)

    for token, body in (
        ("coordinator", {**VALID, "opens_at": "2026-11-19T19:00"}),
        ("coordinator", {**VALID, "closes_at": "2026-11-20T18:00"}),
        ("coordinator", {**VALID, "capacity": 0}),
        ("coordinator", {**VALID, "capacity": 121}),
        ("other-coordinator", VALID),
        ("venue-staff", VALID),
    ):
        assert save(client, event_id, body, token=token).status_code >= 400

    assert stored(app, event_id) == before
    assert len(read(client, event_id).json["registration"]["history"]) == 1


# AC7 — refused for any other status or person, nothing changes


# TC-SPL-114-15
# SPL-114 AC-7 Test-15
@pytest.mark.parametrize(
    "status", [status for status in EVENT_REQUEST_STATUSES if status != "confirmed"]
)
def test_tc_spl_114_15_only_a_confirmed_event_can_enable_registration(app, client, status):
    event_id = make_event(app, status=status)
    add_booking(app, event_id)

    response = save(client, event_id, VALID)

    assert response.status_code == 409
    assert response.json["error"] == "Registration can only be set up for a Confirmed event."
    assert stored(app, event_id) == (None, None, None, 0)
    # Not vacuous: the same event succeeds once it is Confirmed.
    set_status(app, event_id, "confirmed")
    assert save(client, event_id, VALID).status_code == 200


# TC-SPL-114-15
# SPL-114 AC-7 Test-15
def test_tc_spl_114_15_a_change_after_leaving_confirmed_is_refused(app, client, event_id):
    save(client, event_id, VALID)
    before = stored(app, event_id)
    set_status(app, event_id, "postponed")

    response = save(client, event_id, {**VALID, "capacity": 90})

    assert response.status_code == 409
    assert stored(app, event_id) == before


# TC-SPL-114-16
# SPL-114 AC-7 Test-16
@pytest.mark.parametrize(
    ("token", "status"),
    [
        ("other-coordinator", 404),
        ("organiser", 403),
        ("venue-staff", 403),
        ("technical-support", 403),
        ("manager", 403),
        ("attendee", 403),
        (None, 401),
    ],
)
def test_tc_spl_114_16_only_the_assigned_coordinator(app, client, event_id, token, status):
    write = save(client, event_id, VALID, token=token)
    look = read(client, event_id, token=token)

    assert write.status_code == look.status_code == status
    assert stored(app, event_id) == (None, None, None, 0)
    # Not vacuous: the assigned coordinator succeeds on the same event straight after.
    assert save(client, event_id, VALID).status_code == 200


# TC-SPL-114-16
# SPL-114 AC-7 Test-16
def test_tc_spl_114_16_another_coordinators_event_and_an_unknown_event_look_the_same(
    app, client, event_id
):
    unassigned = save(client, event_id, VALID, token="other-coordinator")
    unknown = save(client, 999999, VALID)
    out_of_range = save(client, 2**31, VALID)

    assert unassigned.status_code == unknown.status_code == out_of_range.status_code == 404
    assert unassigned.json == unknown.json == out_of_range.json
