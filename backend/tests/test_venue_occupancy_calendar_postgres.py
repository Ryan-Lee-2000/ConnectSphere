"""PostgreSQL evidence for SPL-88 (CS-E11-S1): the calendar's status rules on a real server.

The calendar reads JSON slot membership (operational blocks) and a uniqueness-constrained occupancy
table, both of which behave differently enough between SQLite and PostgreSQL to be worth proving
here. This case runs only under `npm run integration` (INTEGRATION_DATABASE_URL). It builds its own
throw-away database, migrates it with Alembic, and drops it afterwards.
"""

import os
import subprocess
import sys
import uuid
from datetime import date, datetime, time, timezone

import pytest
from app import create_app
from app.models import (
    Account,
    AccountRole,
    EventRequest,
    Organisation,
    Role,
    Venue,
    VenueBooking,
    VenueBookingOccupancy,
    VenueLayout,
    VenueOperationalBlock,
)
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

pytestmark = pytest.mark.skipif(
    not os.getenv("INTEGRATION_DATABASE_URL"),
    reason="Run npm run integration with disposable PostgreSQL",
)

DAY = date(2026, 10, 14)


@pytest.fixture
def pg_url():
    server = make_url(os.environ["INTEGRATION_DATABASE_URL"])
    name = f"spl88_{uuid.uuid4().hex[:12]}"
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
def engine(pg_url):
    engine = create_engine(pg_url)
    yield engine
    engine.dispose()


def _seed(engine):
    """A venue whose PM slot is both booked and blocked, and whose AM slot is preparation."""

    ids = {name: str(uuid.uuid4()) for name in ("venue-staff", "organiser")}
    with Session(engine) as session:
        organisation = Organisation(name=f"SPL-88 client {uuid.uuid4()}")
        session.add(organisation)
        session.flush()
        for name, role in (("venue-staff", Role.VENUE_STAFF), ("organiser", Role.EVENT_ORGANISER)):
            session.add(Account(id=ids[name], display_name=name, organisation_id=organisation.id))
            session.add(AccountRole(account_id=ids[name], role=role.value))
        session.flush()
        event = EventRequest(
            organiser_account_id=ids["organiser"],
            organisation_id=organisation.id,
            name="Calendar proof",
            purpose="PostgreSQL occupancy check",
            proposed_date=DAY,
            start_time=time(13),
            end_time=time(18),
            expected_attendance=100,
            status="planning",
        )
        venue = Venue(
            name="Calendar Hall",
            operating_slots=["AM", "PM"],
            setup_buffer_slots=1,
            turnaround_buffer_slots=0,
        )
        venue.layouts = [VenueLayout(layout="theatre", capacity=200)]
        session.add_all([event, venue])
        session.flush()
        booking = VenueBooking(
            event_request_id=event.id, venue_id=venue.id, status="approved", layout="theatre"
        )
        session.add(booking)
        session.flush()
        session.add_all(
            [
                VenueBookingOccupancy(
                    booking_id=booking.id, venue_id=venue.id, day=DAY, slot="PM", kind="event"
                ),
                VenueBookingOccupancy(
                    booking_id=booking.id, venue_id=venue.id, day=DAY, slot="AM", kind="setup"
                ),
                VenueOperationalBlock(
                    venue_id=venue.id,
                    start_date=DAY,
                    end_date=DAY,
                    slots=["PM"],
                    reason="Ceiling repair",
                    created_by_account_id=ids["venue-staff"],
                    created_at=datetime(2026, 9, 20, 9, tzinfo=timezone.utc),
                ),
            ]
        )
        session.commit()
        return ids, venue.id


# TC-SPL-88-21
def test_tc_spl_88_21_statuses_and_precedence_hold_on_postgresql(engine, pg_url):
    ids, venue_id = _seed(engine)
    app = create_app(
        {"TESTING": True, "DATABASE_URL": pg_url, "IDENTITY_VERIFIER": ids.__getitem__}
    )
    try:
        response = app.test_client().get(
            f"/api/venues/{venue_id}/occupancy"
            f"?start_date={DAY.isoformat()}&end_date={DAY.isoformat()}",
            headers={"Authorization": "Bearer venue-staff"},
        )
    finally:
        app.extensions["engine"].dispose()

    assert response.status_code == 200, response.json
    slots = {entry["slot"]: entry for entry in response.json["days"][0]["slots"]}
    # Booked and Blocked together: the block wins the label, both reasons survive (AC2, AC4).
    assert slots["PM"]["status"] == "blocked"
    assert {reason["key"] for reason in slots["PM"]["reasons"]} == {"booking", "block"}
    # Preparation comes from the occupancy row's kind, not the booking's Approved status.
    assert slots["AM"]["status"] == "preparation"
    # A slot the venue does not operate stays distinct from Available (AC5).
    assert slots["NIGHT"]["status"] == "not_operated"
