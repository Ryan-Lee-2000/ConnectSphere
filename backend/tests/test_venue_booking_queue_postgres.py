"""PostgreSQL evidence for SPL-80 (CS-E10-S2): the queue's order does not depend on the database.

Runs only under `npm run integration` (INTEGRATION_DATABASE_URL). TC-SPL-80-09 proves the ordering
on SQLite; this repeats it on PostgreSQL, because the two disagree on where NULLs sort by default
and the queue must present the longest-waiting request first on both.
"""

import os
import uuid
from datetime import date, datetime, time, timezone

import pytest
from app import create_app
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
)
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

pytestmark = pytest.mark.skipif(
    not os.getenv("INTEGRATION_DATABASE_URL"),
    reason="Run npm run integration with disposable PostgreSQL",
)

COORDINATOR = "00000000-0000-0000-0000-000000000801"
ORGANISER = "00000000-0000-0000-0000-000000000802"
VENUE_STAFF = "00000000-0000-0000-0000-000000000803"
MANAGER = "00000000-0000-0000-0000-000000000804"
TOKENS = {"coordinator": COORDINATOR, "venue-staff": VENUE_STAFF}
EVENT_DATE = date(2026, 10, 14)


@pytest.fixture
def fresh_url():
    server = make_url(os.environ["INTEGRATION_DATABASE_URL"])
    name = f"spl80_{uuid.uuid4().hex[:12]}"
    admin = create_engine(server, isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{name}"'))
    try:
        yield server.set(database=name).render_as_string(hide_password=False)
    finally:
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()


@pytest.fixture
def app(fresh_url):
    app = create_app(
        {
            "TESTING": True,
            "DATABASE_URL": fresh_url,
            "IDENTITY_VERIFIER": TOKENS.__getitem__,
        }
    )
    engine = app.extensions["engine"]
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        organisation = Organisation(name="Northstar Community Partners")
        session.add(organisation)
        session.flush()
        for account_id, name, role in (
            (COORDINATOR, "Casey Lim", Role.EVENT_COORDINATOR),
            (ORGANISER, "Devon Lee", Role.EVENT_ORGANISER),
            (VENUE_STAFF, "Valerie Tan", Role.VENUE_STAFF),
            (MANAGER, "Morgan Ong", Role.EVENT_OPERATIONS_MANAGER),
        ):
            session.add(Account(id=account_id, display_name=name))
            session.add(AccountRole(account_id=account_id, role=role.value))
        venue = Venue(
            name="Harbour Hall",
            location="Level 3, Marina Centre",
            facilities=["Projector"],
            accessibility_features=["Step-free access"],
            operating_slots=["AM", "PM", "NIGHT"],
            setup_buffer_slots=1,
            turnaround_buffer_slots=1,
        )
        session.add(venue)
        session.commit()
        app.config["ORGANISATION_ID"] = organisation.id
        app.config["VENUE_ID"] = venue.id
    yield app
    engine.dispose()


def seed_request(app, name, requested_at):
    """One Requested booking for its own event, with the request time under test."""

    with Session(app.extensions["engine"]) as session:
        event = EventRequest(
            organiser_account_id=ORGANISER,
            organisation_id=app.config["ORGANISATION_ID"],
            name=name,
            purpose="Community planning",
            proposed_date=EVENT_DATE,
            start_time=time(13),
            end_time=time(18),
            expected_attendance=150,
            status="planning",
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
        booking = VenueBooking(
            event_request_id=event.id,
            venue_id=app.config["VENUE_ID"],
            status="requested",
            layout="theatre",
            expected_attendance=150,
            booking_date=EVENT_DATE,
            event_slots=["PM"],
            requested_by_account_id=COORDINATOR,
            requested_at=requested_at,
        )
        session.add(booking)
        session.commit()
        return booking.id


# TC-SPL-80-09 (PostgreSQL)
def test_tc_spl_80_09_oldest_request_first_nulls_last_on_postgresql(app):
    later = seed_request(app, "Later", datetime(2026, 9, 27, 9, 30, tzinfo=SINGAPORE))
    earlier = seed_request(app, "Earlier", datetime(2026, 9, 27, 9, 0, tzinfo=SINGAPORE))
    untimed = seed_request(app, "Untimed", None)

    response = app.test_client().get(
        "/api/venue-bookings/pending", headers={"Authorization": "Bearer venue-staff"}
    )

    assert response.status_code == 200, response.json
    # PostgreSQL sorts NULLs last on an ascending column by default and SQLite sorts them first,
    # so an unguarded ORDER BY would put the untimed row first here and last on SQLite.
    assert [item["id"] for item in response.json["requests"]] == [earlier, later, untimed]
