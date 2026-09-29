"""PostgreSQL evidence for SPL-82 (CS-E10-S4): rejection frees occupancy on a real server.

SQLite and PostgreSQL agree on this behaviour, but SPL-80's queue already needed a dedicated
PostgreSQL case for a database-specific difference, so this one runs the same real-server check
here rather than assume SQLite's result generalises. This case runs only under `npm run integration`
(INTEGRATION_DATABASE_URL). It builds its own throw-away database, migrates it with Alembic, and
drops it afterwards.
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
    EventCoordinatorAssignment,
    EventRequest,
    Organisation,
    Role,
    Venue,
    VenueBooking,
    VenueBookingOccupancy,
    VenueLayout,
)
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

pytestmark = pytest.mark.skipif(
    not os.getenv("INTEGRATION_DATABASE_URL"),
    reason="Run npm run integration with disposable PostgreSQL",
)


@pytest.fixture
def pg_url():
    server = make_url(os.environ["INTEGRATION_DATABASE_URL"])
    name = f"spl82_{uuid.uuid4().hex[:12]}"
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
    """One Venue Staff account, one Planning event and its Requested booking holding one slot."""

    ids = {name: str(uuid.uuid4()) for name in ("venue-staff", "organiser")}
    with Session(engine) as session:
        organisation = Organisation(name=f"SPL-82 client {uuid.uuid4()}")
        session.add(organisation)
        session.flush()
        for name, role in (
            ("venue-staff", Role.VENUE_STAFF),
            ("organiser", Role.EVENT_ORGANISER),
        ):
            session.add(Account(id=ids[name], display_name=name, organisation_id=organisation.id))
            session.add(AccountRole(account_id=ids[name], role=role.value))
        session.flush()
        planning_event = EventRequest(
            organiser_account_id=ids["organiser"],
            organisation_id=organisation.id,
            name="Rejection proof",
            purpose="PostgreSQL occupancy check",
            proposed_date=date(2026, 10, 14),
            start_time=time(13),
            end_time=time(18),
            expected_attendance=100,
            status="planning",
        )
        venue = Venue(
            name="Race Hall",
            operating_slots=["AM", "PM", "NIGHT"],
            setup_buffer_slots=0,
            turnaround_buffer_slots=0,
        )
        venue.layouts = [VenueLayout(layout="theatre", capacity=200)]
        session.add_all([planning_event, venue])
        session.flush()
        session.add(
            EventCoordinatorAssignment(
                event_request_id=planning_event.id,
                coordinator_account_id=ids["organiser"],
                assigned_by_account_id=ids["organiser"],
                assigned_at=datetime(2026, 9, 20, 9, tzinfo=timezone.utc),
            )
        )
        booking = VenueBooking(
            event_request_id=planning_event.id, venue_id=venue.id, status="requested"
        )
        session.add(booking)
        session.flush()
        session.add(
            VenueBookingOccupancy(
                booking_id=booking.id,
                venue_id=venue.id,
                day=date(2026, 10, 14),
                slot="PM",
                kind="event",
            )
        )
        session.commit()
        return ids, booking.id


# TC-SPL-82-17
def test_tc_spl_82_17_rejection_frees_occupancy_on_postgresql(engine, pg_url):
    ids, booking_id = _seed(engine)
    app = create_app(
        {"TESTING": True, "DATABASE_URL": pg_url, "IDENTITY_VERIFIER": ids.__getitem__}
    )
    try:
        response = app.test_client().post(
            f"/api/venue-bookings/{booking_id}/reject",
            json={"reason": "Venue unavailable that week."},
            headers={"Authorization": "Bearer venue-staff"},
        )
    finally:
        app.extensions["engine"].dispose()

    assert response.status_code == 200, response.json
    assert response.json["booking"]["status"] == "rejected"
    with Session(engine) as session:
        booking = session.get(VenueBooking, booking_id)
        assert booking.status == "rejected"
        assert booking.rejection_reason == "Venue unavailable that week."
        assert (
            session.scalar(
                select(func.count(VenueBookingOccupancy.id)).where(
                    VenueBookingOccupancy.booking_id == booking_id
                )
            )
            == 0
        )
