"""PostgreSQL evidence for SPL-116 and SPL-118: racing for the last place, double submits, and
withdrawing the same registration twice at once.

SQLite cannot run two transactions against each other, so these cases run only under
`npm run integration` (INTEGRATION_DATABASE_URL), on a throw-away PostgreSQL database built with
the real Alembic migrations.

How a race is staged
--------------------
SPL-116: each request runs in its own thread with its own test client, so each gets its own
database connection. A ``threading.Barrier`` holds the threads until both are ready, then releases
them at the same instant. If the route did not lock the event row, both could count "1 place left"
and both register; with the lock, the second waits, then sees the event is full.

SPL-118 uses the stricter ``ordered_race`` (shared with SPL-137/138): the first withdrawal is
held just before it commits, and the test *proves* the second one is waiting on a PostgreSQL lock
before releasing the first. Without the row lock the second would not wait, and the test fails.
"""

import os
import subprocess
import sys
import threading
import uuid
from datetime import date, datetime, time, timedelta

import pytest
from app import create_app
from app import registration_settings as settings_module
from app.event_requests import SINGAPORE
from app.models import (
    Account,
    AccountRole,
    EventRegistration,
    EventRequest,
    Organisation,
    Role,
    Venue,
    VenueBooking,
    VenueLayout,
)
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

pytestmark = pytest.mark.skipif(
    not os.getenv("INTEGRATION_DATABASE_URL"),
    reason="Run npm run integration with disposable PostgreSQL",
)

NOW = datetime(2026, 10, 20, 12, tzinfo=SINGAPORE)


@pytest.fixture
def pg_url():
    server = make_url(os.environ["INTEGRATION_DATABASE_URL"])
    name = f"spl116_{uuid.uuid4().hex[:12]}"
    admin = create_engine(server, isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{name}"'))
    url = server.set(database=name).render_as_string(hide_password=False)
    try:
        upgraded = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            capture_output=True,
            text=True,
            env={**os.environ, "DATABASE_URL": url},
        )
        assert upgraded.returncode == 0, upgraded.stderr
        yield url
    finally:
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()


@pytest.fixture
def scenario(pg_url, monkeypatch):
    """Two attendees and one Confirmed event whose open registration has ``capacity`` places."""

    monkeypatch.setattr(settings_module, "_now", lambda: NOW)
    tokens = {"first": str(uuid.uuid4()), "second": str(uuid.uuid4())}
    engine = create_engine(pg_url)
    with Session(engine) as session:
        organisation = Organisation(name=f"SPL-116 client {uuid.uuid4()}")
        session.add(organisation)
        session.flush()
        organiser = Account(
            id=str(uuid.uuid4()), display_name="Devon Lee", organisation_id=organisation.id
        )
        session.add(organiser)
        for token, account_id in tokens.items():
            session.add(Account(id=account_id, display_name=f"Attendee {token}"))
            session.add(AccountRole(account_id=account_id, role=Role.ATTENDEE.value))
        session.flush()
        event = EventRequest(
            organiser_account_id=organiser.id,
            organisation_id=organisation.id,
            name="Harbour Lights Gala",
            purpose="Annual fundraiser",
            proposed_date=date(2026, 11, 20),
            start_time=time(18),
            end_time=time(22),
            expected_attendance=150,
            status="confirmed",
            registration_opens_at=NOW - timedelta(days=10),
            registration_closes_at=NOW + timedelta(days=20),
            registration_capacity=1,
        )
        venue = Venue(
            name="Harbour Hall",
            operating_slots=["AM", "PM", "NIGHT"],
            setup_buffer_slots=0,
            turnaround_buffer_slots=0,
        )
        venue.layouts = [VenueLayout(layout="theatre", capacity=200)]
        session.add_all([event, venue])
        session.flush()
        session.add(
            VenueBooking(
                event_request_id=event.id, venue_id=venue.id, status="approved", layout="theatre"
            )
        )
        session.commit()
        event_id = event.id
    app = create_app({"TESTING": True, "DATABASE_URL": pg_url, "IDENTITY_VERIFIER": tokens.get})
    yield app, engine, event_id
    app.extensions["engine"].dispose()
    engine.dispose()


def race(app, event_id, tokens):
    """Send one registration per token at the same instant; return the status codes."""

    barrier = threading.Barrier(len(tokens))
    codes = [None] * len(tokens)

    def attempt(index, token):
        client = app.test_client()
        barrier.wait()  # every thread is ready; all go together
        codes[index] = client.post(
            f"/api/event-requests/{event_id}/registrations",
            json={"name": f"Attendee {index}", "email": "a@b.co", "contact_number": "91234567"},
            headers={"Authorization": f"Bearer {token}"},
        ).status_code

    threads = [threading.Thread(target=attempt, args=pair) for pair in enumerate(tokens)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    return sorted(codes)


def registered(engine, event_id):
    with Session(engine) as session:
        return session.scalar(
            select(func.count())
            .select_from(EventRegistration)
            .where(
                EventRegistration.event_request_id == event_id,
                EventRegistration.status == "registered",
            )
        )


# TC-SPL-116-10
# SPL-116 AC-6 Test-10
def test_tc_spl_116_10_two_attendees_race_for_the_last_place(scenario):
    app, engine, event_id = scenario

    codes = race(app, event_id, ["first", "second"])

    # Exactly one takes the place; the other is told the event is full.
    assert codes == [201, 409]
    assert registered(engine, event_id) == 1


# TC-SPL-116-11
# SPL-116 AC-5 Test-11
def test_tc_spl_116_11_the_same_attendee_submitting_twice_registers_once(scenario):
    app, engine, event_id = scenario
    with Session(engine) as session:
        session.get(EventRequest, event_id).registration_capacity = 5
        session.commit()

    codes = race(app, event_id, ["first", "first"])

    assert codes == [201, 409]
    assert registered(engine, event_id) == 1


# SPL-118 (CS-E19-S5): withdrawing a registration.


def _register_first(app, event_id):
    """Register the "first" attendee through SPL-116's route and return the registration id."""

    response = app.test_client().post(
        f"/api/event-requests/{event_id}/registrations",
        json={"name": "Attendee first", "email": "a@b.co", "contact_number": "91234567"},
        headers={"Authorization": "Bearer first"},
    )
    assert response.status_code == 201, response.json
    return response.json["registration"]["id"]


# TC-SPL-118-07
# SPL-118 AC-3 Test-07
def test_tc_spl_118_07_two_simultaneous_withdrawals_free_the_place_once(scenario):
    from test_exact_venue_bookings_postgres import ordered_race

    app, engine, event_id = scenario
    registration_id = _register_first(app, event_id)

    def withdrawal(client):
        return client.post(
            f"/api/registrations/{registration_id}/withdraw",
            headers={"Authorization": "Bearer first"},
        )

    # ordered_race asserts the second request really waited on a database lock.
    first, second = ordered_race(app, withdrawal, withdrawal)

    assert first[0] == 200
    assert (second[0], second[1]["error"]) == (409, "This registration is already withdrawn.")
    # The single place (capacity 1) is free exactly once, not counted back twice.
    assert first[1]["event"]["places_remaining"] == 1
    assert registered(engine, event_id) == 0


# TC-SPL-118-10 (added while writing: the migration and the database's own rule)
# SPL-118 AC-2 Test-10
def test_tc_spl_118_10_migration_keeps_registrations_and_refuses_a_bad_time(scenario, pg_url):
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    from sqlalchemy.exc import IntegrityError

    app, engine, event_id = scenario
    registration_id = _register_first(app, event_id)
    app.extensions["engine"].dispose()
    engine.dispose()

    # Roll the migration back to its parent and forward again with a registration in the table.
    # The parent is read from the migration itself, so this keeps working when it is re-pointed.
    parent = (
        ScriptDirectory.from_config(Config("alembic.ini"))
        .get_revision("s3_registration_withdrawals")
        .down_revision
    )
    for command in (["downgrade", parent], ["upgrade", "head"]):
        moved = subprocess.run(
            [sys.executable, "-m", "alembic", *command],
            capture_output=True,
            text=True,
            env={**os.environ, "DATABASE_URL": pg_url},
        )
        assert moved.returncode == 0, moved.stderr

    row = text("SELECT status, withdrawn_at FROM event_registrations WHERE id = :id")
    with engine.connect() as connection:
        # The existing registration survives unchanged and reads as "not withdrawn".
        assert tuple(connection.execute(row, {"id": registration_id}).one()) == ("registered", None)

    # The database itself refuses a Registered row that carries a withdrawal time...
    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(
                text("UPDATE event_registrations SET withdrawn_at = now() WHERE id = :id"),
                {"id": registration_id},
            )
    # ...and accepts a proper withdrawal.
    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE event_registrations SET status = 'withdrawn', withdrawn_at = now() "
                "WHERE id = :id"
            ),
            {"id": registration_id},
        )
