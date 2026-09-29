"""PostgreSQL evidence for SPL-78 (CS-E09-S4): concurrent withdrawals and the migration.

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


@pytest.fixture
def pg_url():
    server = make_url(os.environ["INTEGRATION_DATABASE_URL"])
    name = f"spl78_{uuid.uuid4().hex[:12]}"
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
    """One coordinator, one Planning event and its Requested booking holding one slot."""

    ids = {name: str(uuid.uuid4()) for name in ("coordinator", "manager", "organiser")}
    with Session(engine) as session:
        organisation = Organisation(name=f"SPL-78 client {uuid.uuid4()}")
        session.add(organisation)
        session.flush()
        for name, role in (
            ("coordinator", Role.EVENT_COORDINATOR),
            ("manager", Role.EVENT_OPERATIONS_MANAGER),
            ("organiser", Role.EVENT_ORGANISER),
        ):
            session.add(Account(id=ids[name], display_name=name, organisation_id=organisation.id))
            session.add(AccountRole(account_id=ids[name], role=role.value))
        session.flush()
        planning_event = EventRequest(
            organiser_account_id=ids["organiser"],
            organisation_id=organisation.id,
            name="Withdrawal race",
            purpose="Concurrency proof",
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
                coordinator_account_id=ids["coordinator"],
                assigned_by_account_id=ids["manager"],
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
        return ids, planning_event.id, booking.id


# TC-SPL-78-19
# SPL-78 AC-6 Test-19
def test_tc_spl_78_19_concurrent_withdrawals_succeed_once(engine, pg_url):
    ids, event_id, booking_id = _seed(engine)
    app = create_app(
        {"TESTING": True, "DATABASE_URL": pg_url, "IDENTITY_VERIFIER": ids.__getitem__}
    )
    app_engine = app.extensions["engine"]
    barrier = threading.Barrier(2, timeout=10)
    released: set[int] = set()
    guard = threading.Lock()

    def align(_connection, _cursor, statement, _parameters, _context, _executemany):
        # Hold both requests until each is about to take the booking row lock.
        if "FOR UPDATE" not in statement:
            return
        with guard:
            if threading.get_ident() in released:
                return
            released.add(threading.get_ident())
        barrier.wait()

    def post(_):
        response = app.test_client().post(
            f"/api/event-requests/{event_id}/venue-bookings/{booking_id}/withdraw",
            headers={"Authorization": "Bearer coordinator"},
        )
        return response.status_code, response.json

    event.listen(app_engine, "before_cursor_execute", align)
    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(post, range(2)))
    finally:
        event.remove(app_engine, "before_cursor_execute", align)
        app_engine.dispose()

    assert sorted(status for status, _ in results) == [200, 409], results
    refused = next(body for status, body in results if status == 409)
    assert refused["error"] == "Only a Requested venue-booking request can be withdrawn."
    winner = next(body for status, body in results if status == 200)["booking"]
    with Session(engine) as session:
        booking = session.get(VenueBooking, booking_id)
        assert booking.status == "withdrawn"
        assert booking.withdrawn_at is not None
        assert datetime.fromisoformat(winner["withdrawn_at"]) == booking.withdrawn_at
        assert (
            session.scalar(
                select(func.count(VenueBookingOccupancy.id)).where(
                    VenueBookingOccupancy.booking_id == booking_id
                )
            )
            == 0
        )


# SPL-78 AC-NA Test-Supporting
def test_spl_78_migration_adds_nullable_withdrawal_columns_with_a_withdrawer_key(engine):
    """Supporting verification: the additive SPL-78 columns and the withdrawer foreign key."""

    columns = {column["name"]: column for column in inspect(engine).get_columns("venue_bookings")}
    assert {"withdrawn_by_account_id", "withdrawn_at"} <= set(columns)
    assert columns["withdrawn_by_account_id"]["nullable"] is True
    assert columns["withdrawn_at"]["nullable"] is True
    assert any(
        key["referred_table"] == "accounts"
        and key["constrained_columns"] == ["withdrawn_by_account_id"]
        for key in inspect(engine).get_foreign_keys("venue_bookings")
    )
