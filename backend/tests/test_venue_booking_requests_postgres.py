"""PostgreSQL evidence for SPL-77 (CS-E09-S3): concurrent booking requests and the migration.

SQLite serialises writes, so it cannot show a race. These cases run only under
`npm run integration` (INTEGRATION_DATABASE_URL). Each test builds its own throw-away database
on that server, migrates it with Alembic, and drops it afterwards.
"""

import os
import subprocess
import sys
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, time, timezone

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
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
from sqlalchemy import create_engine, event, func, inspect, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

pytestmark = pytest.mark.skipif(
    not os.getenv("INTEGRATION_DATABASE_URL"),
    reason="Run npm run integration with disposable PostgreSQL",
)

EVENT_DATE = date(2026, 10, 14)


@pytest.fixture
def pg_url():
    server = make_url(os.environ["INTEGRATION_DATABASE_URL"])
    name = f"spl77_{uuid.uuid4().hex[:12]}"
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


def _seed(engine, *, events, venues):
    """Accounts, one Planning event per coordinator name, and the named venues."""

    ids = {name: str(uuid.uuid4()) for name in ("manager", "organiser", *events)}
    with Session(engine) as session:
        organisation = Organisation(name=f"SPL-77 client {uuid.uuid4()}")
        session.add(organisation)
        session.flush()
        for name, account_id in ids.items():
            role = {
                "manager": Role.EVENT_OPERATIONS_MANAGER,
                "organiser": Role.EVENT_ORGANISER,
            }.get(name, Role.EVENT_COORDINATOR)
            session.add(Account(id=account_id, display_name=name, organisation_id=organisation.id))
            session.add(AccountRole(account_id=account_id, role=role.value))
        session.flush()
        event_ids = {}
        for coordinator in events:
            planning_event = EventRequest(
                organiser_account_id=ids["organiser"],
                organisation_id=organisation.id,
                name=f"{coordinator} event",
                purpose="Concurrency proof",
                proposed_date=EVENT_DATE,
                start_time=time(13),
                end_time=time(18),
                expected_attendance=100,
                status="planning",
            )
            session.add(planning_event)
            session.flush()
            session.add(
                EventCoordinatorAssignment(
                    event_request_id=planning_event.id,
                    coordinator_account_id=ids[coordinator],
                    assigned_by_account_id=ids["manager"],
                    assigned_at=datetime(2026, 9, 20, 9, tzinfo=timezone.utc),
                )
            )
            event_ids[coordinator] = planning_event.id
        venue_ids = {}
        for name, preparation in venues.items():
            venue = Venue(
                name=name,
                operating_slots=["AM", "PM", "NIGHT"],
                setup_buffer_slots=preparation,
                turnaround_buffer_slots=preparation,
            )
            venue.layouts = [VenueLayout(layout="theatre", capacity=200)]
            session.add(venue)
            session.flush()
            venue_ids[name] = venue.id
        session.commit()
    return ids, event_ids, venue_ids


def _app(pg_url, ids):
    return create_app(
        {"TESTING": True, "DATABASE_URL": pg_url, "IDENTITY_VERIFIER": ids.__getitem__}
    )


def _race(app, marker, calls):
    """Run the calls together, releasing both at the first SQL statement containing marker."""

    app_engine = app.extensions["engine"]
    barrier = threading.Barrier(len(calls), timeout=10)
    released: set[int] = set()
    guard = threading.Lock()

    def align(_connection, _cursor, statement, _parameters, _context, _executemany):
        if marker not in statement:
            return
        with guard:
            if threading.get_ident() in released:
                return
            released.add(threading.get_ident())
        barrier.wait()

    def post(call):
        coordinator, event_id, venue_id = call
        client = app.test_client()
        response = client.post(
            f"/api/event-requests/{event_id}/venue-bookings",
            json={"venue_id": venue_id, "layout": "theatre"},
            headers={"Authorization": f"Bearer {coordinator}"},
        )
        return response.status_code, response.json

    event.listen(app_engine, "before_cursor_execute", align)
    try:
        with ThreadPoolExecutor(max_workers=len(calls)) as executor:
            return list(executor.map(post, calls))
    finally:
        event.remove(app_engine, "before_cursor_execute", align)
        app_engine.dispose()


# TC-SPL-77-13
# SPL-77 AC-4 Test-13
def test_tc_spl_77_13_concurrent_requests_for_one_event_create_one_booking(engine, pg_url):
    ids, event_ids, venue_ids = _seed(engine, events=["alice"], venues={"Venue A": 0, "Venue B": 0})
    app = _app(pg_url, ids)

    results = _race(
        app,
        "FOR NO KEY UPDATE",
        [
            ("alice", event_ids["alice"], venue_ids["Venue A"]),
            ("alice", event_ids["alice"], venue_ids["Venue B"]),
        ],
    )

    statuses = sorted(status for status, _ in results)
    assert statuses == [201, 409], results
    refused = next(body for status, body in results if status == 409)
    assert "already has an active venue-booking request" in refused["error"]
    with Session(engine) as session:
        bookings = session.scalars(
            select(VenueBooking).where(VenueBooking.event_request_id == event_ids["alice"])
        ).all()
        assert [booking.status for booking in bookings] == ["requested"]
        occupied_venues = set(session.scalars(select(VenueBookingOccupancy.venue_id)))
        assert occupied_venues == {bookings[0].venue_id}


# TC-SPL-77-18
# SPL-77 AC-5 Test-18
def test_tc_spl_77_18_concurrent_requests_for_one_slot_yield_one_booking(engine, pg_url):
    ids, event_ids, venue_ids = _seed(engine, events=["alice", "bob"], venues={"Shared Hall": 1})
    app = _app(pg_url, ids)
    hall = venue_ids["Shared Hall"]

    results = _race(
        app,
        "FROM venues",  # SPL-137 shared boundary precedes legacy slot locks.
        [("alice", event_ids["alice"], hall), ("bob", event_ids["bob"], hall)],
    )

    statuses = sorted(status for status, _ in results)
    assert statuses == [201, 409], results
    refused = next(body for status, body in results if status == 409)
    assert refused["conflict"]["date"] == "2026-10-14"
    assert refused["conflict"]["slot"] in {"AM", "PM", "NIGHT"}
    winner = next(body for status, body in results if status == 201)["booking"]
    with Session(engine) as session:
        rows = session.scalars(
            select(VenueBookingOccupancy).where(VenueBookingOccupancy.venue_id == hall)
        ).all()
        assert {(row.day, row.slot, row.kind) for row in rows} == {
            (EVENT_DATE, "AM", "setup"),
            (EVENT_DATE, "PM", "event"),
            (EVENT_DATE, "NIGHT", "turnaround"),
        }
        assert {row.booking_id for row in rows} == {winner["id"]}
        assert session.scalar(select(func.count(VenueBooking.id))) == 1


# SPL-77 AC-NA Test-Supporting
def test_spl_77_migration_adds_nullable_request_columns_with_a_requester_key(engine):
    """Supporting verification: the additive SPL-77 columns and the requester foreign key."""

    columns = {column["name"]: column for column in inspect(engine).get_columns("venue_bookings")}
    added = {
        "layout",
        "expected_attendance",
        "booking_date",
        "event_slots",
        "setup_date",
        "setup_slot",
        "turnaround_date",
        "turnaround_slot",
        "requested_by_account_id",
        "requested_at",
    }
    assert added <= set(columns)
    assert all(columns[name]["nullable"] for name in added)
    assert any(
        key["referred_table"] == "accounts"
        and key["constrained_columns"] == ["requested_by_account_id"]
        for key in inspect(engine).get_foreign_keys("venue_bookings")
    )
    # The database is at the single current head, and SPL-77's revision is in its history.
    script = ScriptDirectory.from_config(Config("alembic.ini"))
    with engine.connect() as connection:
        applied = connection.execute(text("select version_num from alembic_version")).scalar()
    assert [applied] == script.get_heads()
    assert "s2_venue_booking_request" in {rev.revision for rev in script.walk_revisions()}
