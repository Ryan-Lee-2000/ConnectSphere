"""PostgreSQL evidence for SPL-81 (CS-E10-S3): concurrent approvals and the migration.

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
from datetime import date, datetime, time, timedelta, timezone

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
    VenueBookingStatusHistory,
    VenueLayout,
)
from sqlalchemy import create_engine, event, func, inspect, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

pytestmark = pytest.mark.skipif(
    not os.getenv("INTEGRATION_DATABASE_URL"),
    reason="Run npm run integration with disposable PostgreSQL",
)

RUNS = 3


@pytest.fixture
def pg_url():
    server = make_url(os.environ["INTEGRATION_DATABASE_URL"])
    name = f"spl81_{uuid.uuid4().hex[:12]}"
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


def _seed_accounts(engine):
    names = ("coordinator", "manager", "organiser", "staff-a", "staff-b")
    ids = {name: str(uuid.uuid4()) for name in names}
    with Session(engine) as session:
        organisation = Organisation(name=f"SPL-81 client {uuid.uuid4()}")
        session.add(organisation)
        session.flush()
        for name, role in (
            ("coordinator", Role.EVENT_COORDINATOR),
            ("manager", Role.EVENT_OPERATIONS_MANAGER),
            ("organiser", Role.EVENT_ORGANISER),
            ("staff-a", Role.VENUE_STAFF),
            ("staff-b", Role.VENUE_STAFF),
        ):
            session.add(Account(id=ids[name], display_name=name, organisation_id=organisation.id))
            session.add(AccountRole(account_id=ids[name], role=role.value))
        venue = Venue(
            name="Race Hall",
            operating_slots=["AM", "PM", "NIGHT"],
            setup_buffer_slots=0,
            turnaround_buffer_slots=0,
        )
        venue.layouts = [VenueLayout(layout="theatre", capacity=200)]
        session.add(venue)
        session.commit()
        return ids, organisation.id, venue.id


def _seed_booking(engine, ids, organisation_id, venue_id, day):
    """One Planning event and its Requested booking holding the PM slot of ``day``."""

    with Session(engine) as session:
        planning_event = EventRequest(
            organiser_account_id=ids["organiser"],
            organisation_id=organisation_id,
            name=f"Approval race {day.isoformat()}",
            purpose="Concurrency proof",
            proposed_date=day,
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
                coordinator_account_id=ids["coordinator"],
                assigned_by_account_id=ids["manager"],
                assigned_at=datetime(2026, 9, 20, 9, tzinfo=timezone.utc),
            )
        )
        booking = VenueBooking(
            event_request_id=planning_event.id,
            venue_id=venue_id,
            status="requested",
            layout="theatre",
            expected_attendance=100,
            booking_date=day,
            event_slots=["PM"],
            requested_by_account_id=ids["coordinator"],
            requested_at=datetime(2026, 9, 27, 9, tzinfo=timezone.utc),
        )
        session.add(booking)
        session.flush()
        session.add(
            VenueBookingOccupancy(
                booking_id=booking.id, venue_id=venue_id, day=day, slot="PM", kind="event"
            )
        )
        session.commit()
        return planning_event.id, booking.id


def _race(app, calls):
    """Run the calls together, holding each until it is about to take the first aggregate lock."""

    app_engine = app.extensions["engine"]
    barrier = threading.Barrier(len(calls), timeout=10)
    released: set[int] = set()
    guard = threading.Lock()

    def align(_connection, _cursor, statement, _parameters, _context, _executemany):
        if "FOR UPDATE" not in statement and "FOR NO KEY UPDATE" not in statement:
            return
        with guard:
            if threading.get_ident() in released:
                return
            released.add(threading.get_ident())
        barrier.wait()

    def run(call):
        response = call(app.test_client())
        return response.status_code, response.json

    event.listen(app_engine, "before_cursor_execute", align)
    try:
        with ThreadPoolExecutor(max_workers=len(calls)) as executor:
            return list(executor.map(run, calls))
    finally:
        event.remove(app_engine, "before_cursor_execute", align)


def _approve(booking_id, token, note):
    return lambda client: client.post(
        f"/api/venue-bookings/{booking_id}/approve",
        json={"note": note},
        headers={"Authorization": f"Bearer {token}"},
    )


# TC-SPL-81-19
# SPL-81 AC-7 Test-19
def test_tc_spl_81_19_concurrent_approvals_exactly_one_succeeds(engine, pg_url):
    ids, organisation_id, venue_id = _seed_accounts(engine)
    app = create_app(
        {"TESTING": True, "DATABASE_URL": pg_url, "IDENTITY_VERIFIER": ids.__getitem__}
    )
    try:
        for run in range(RUNS):
            day = date(2026, 10, 14) + timedelta(days=run)
            _, booking_id = _seed_booking(engine, ids, organisation_id, venue_id, day)

            results = _race(
                app,
                [
                    _approve(booking_id, "staff-a", "Note A"),
                    _approve(booking_id, "staff-b", "Note B"),
                ],
            )

            assert sorted(status for status, _ in results) == [200, 409], results
            refused = next(body for status, body in results if status == 409)
            assert refused["error"] == "Only a Requested venue-booking request can be approved."
            winner = next(body for status, body in results if status == 200)["booking"]
            with Session(engine) as session:
                booking = session.get(VenueBooking, booking_id)
                assert booking.status == "approved"
                assert booking.approval_note == winner["approval_note"]
                assert booking.approved_by_account_id == winner["approved_by"]["id"]
                approvals = session.scalar(
                    select(func.count(VenueBookingStatusHistory.id)).where(
                        VenueBookingStatusHistory.booking_id == booking_id,
                        VenueBookingStatusHistory.action == "approve",
                    )
                )
                assert approvals == 1
    finally:
        app.extensions["engine"].dispose()


# TC-SPL-81-20
# SPL-81 AC-7,6 Test-20
def test_tc_spl_81_20_approval_racing_withdrawal_has_one_outcome(engine, pg_url):
    ids, organisation_id, venue_id = _seed_accounts(engine)
    app = create_app(
        {"TESTING": True, "DATABASE_URL": pg_url, "IDENTITY_VERIFIER": ids.__getitem__}
    )
    try:
        for run in range(RUNS):
            day = date(2026, 11, 14) + timedelta(days=run)
            event_id, booking_id = _seed_booking(engine, ids, organisation_id, venue_id, day)
            withdraw = lambda client: client.post(  # noqa: E731
                f"/api/event-requests/{event_id}/venue-bookings/{booking_id}/withdraw",
                headers={"Authorization": "Bearer coordinator"},
            )

            results = _race(app, [_approve(booking_id, "staff-a", "Note A"), withdraw])

            assert sorted(status for status, _ in results) == [200, 409], results
            with Session(engine) as session:
                booking = session.get(VenueBooking, booking_id)
                held = session.scalar(
                    select(func.count(VenueBookingOccupancy.id)).where(
                        VenueBookingOccupancy.booking_id == booking_id
                    )
                )
                if booking.status == "approved":
                    assert held == 1
                    assert booking.withdrawn_at is None
                else:
                    assert booking.status == "withdrawn"
                    assert held == 0
                    assert booking.approved_at is None and booking.approval_note is None
    finally:
        app.extensions["engine"].dispose()


# SPL-81 AC-NA Test-Supporting
def test_spl_81_migration_adds_nullable_approval_columns_with_an_approver_key(engine):
    """Supporting verification: the additive SPL-81 columns and the approver foreign key."""

    columns = {column["name"]: column for column in inspect(engine).get_columns("venue_bookings")}
    assert {"approved_by_account_id", "approved_at", "approval_note"} <= set(columns)
    assert all(
        columns[name]["nullable"]
        for name in ("approved_by_account_id", "approved_at", "approval_note")
    )
    assert any(
        key["referred_table"] == "accounts"
        and key["constrained_columns"] == ["approved_by_account_id"]
        for key in inspect(engine).get_foreign_keys("venue_bookings")
    )
