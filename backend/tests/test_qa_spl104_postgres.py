"""SPL-104 QA cases on real PostgreSQL: simultaneous actions and real rollback.

SQLite serialises writes, so it cannot show a race. These run only under `npm run integration`
(INTEGRATION_DATABASE_URL). Each test builds its own throw-away database on that server, migrates
it with Alembic and drops it afterwards, as SPL-78's PostgreSQL cases do.
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
from app import venue_booking_requests as requests_module
from app.models import (
    Account,
    AccountRole,
    EventCoordinatorAssignment,
    EventRequest,
    Notification,
    Organisation,
    Role,
    Venue,
    VenueBooking,
    VenueLayout,
)
from sqlalchemy import create_engine, event, func, select, text
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
    name = f"spl104_{uuid.uuid4().hex[:12]}"
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
    roles = {
        "coordinator": Role.EVENT_COORDINATOR,
        "manager": Role.EVENT_OPERATIONS_MANAGER,
        "organiser": Role.EVENT_ORGANISER,
        "staff-a": Role.VENUE_STAFF,
        "staff-b": Role.VENUE_STAFF,
    }
    with Session(engine) as session:
        organisation = Organisation(name=f"SPL-104 client {uuid.uuid4()}")
        session.add(organisation)
        session.flush()
        for name, role in roles.items():
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


def _seed_event(engine, ids, organisation_id, day):
    with Session(engine) as session:
        planning = EventRequest(
            organiser_account_id=ids["organiser"],
            organisation_id=organisation_id,
            name=f"Race {day.isoformat()}",
            purpose="Concurrency proof",
            proposed_date=day,
            start_time=time(13),
            end_time=time(18),
            expected_attendance=100,
            status="planning",
        )
        session.add(planning)
        session.flush()
        session.add(
            EventCoordinatorAssignment(
                event_request_id=planning.id,
                coordinator_account_id=ids["coordinator"],
                assigned_by_account_id=ids["manager"],
                assigned_at=datetime(2026, 9, 20, 9, tzinfo=timezone.utc),
            )
        )
        session.commit()
        return planning.id


def _race(app, calls):
    """Run the calls at once, held until each is about to take its first row lock."""

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


def _request(event_id, venue_id):
    return lambda client: client.post(
        f"/api/event-requests/{event_id}/venue-bookings",
        json={"venue_id": venue_id, "layout": "theatre"},
        headers={"Authorization": "Bearer coordinator"},
    )


def _withdraw(event_id, booking_id):
    return lambda client: client.post(
        f"/api/event-requests/{event_id}/venue-bookings/{booking_id}/withdraw",
        headers={"Authorization": "Bearer coordinator"},
    )


def _per_recipient(engine, ids, event_id, prefix):
    names = {value: name for name, value in ids.items()}
    with Session(engine) as session:
        rows = session.execute(
            select(Notification.recipient_account_id, func.count())
            .where(
                Notification.event_request_id == event_id,
                Notification.dedupe_key.startswith(prefix),
            )
            .group_by(Notification.recipient_account_id)
        ).all()
    return {names[recipient]: total for recipient, total in rows}


def _app(pg_url, ids):
    return create_app(
        {"TESTING": True, "DATABASE_URL": pg_url, "IDENTITY_VERIFIER": ids.__getitem__}
    )


# QA-SPL-104-070 | AC2 AC7 | WB concurrency
def test_qa_spl_104_070_simultaneous_withdrawals_notify_once(engine, pg_url):
    ids, organisation_id, venue_id = _seed_accounts(engine)
    app = _app(pg_url, ids)
    try:
        for run in range(RUNS):
            event_id = _seed_event(engine, ids, organisation_id, date(2027, 3, 1) + timedelta(run))
            created = _request(event_id, venue_id)(app.test_client())
            assert created.status_code == 201, created.json
            booking_id = created.json["booking"]["id"]
            results = _race(app, [_withdraw(event_id, booking_id), _withdraw(event_id, booking_id)])
            assert sorted(status for status, _ in results) == [200, 409], results
            withdrawn = _per_recipient(engine, ids, event_id, "venue_booking_withdrawn:")
            assert withdrawn == {"staff-a": 1, "staff-b": 1}
    finally:
        app.extensions["engine"].dispose()


# QA-SPL-104-071 | AC1 AC7 | WB concurrency
def test_qa_spl_104_071_the_same_request_sent_twice_at_once_notifies_once(engine, pg_url):
    ids, organisation_id, venue_id = _seed_accounts(engine)
    app = _app(pg_url, ids)
    try:
        for run in range(RUNS):
            event_id = _seed_event(engine, ids, organisation_id, date(2027, 4, 1) + timedelta(run))
            results = _race(app, [_request(event_id, venue_id), _request(event_id, venue_id)])
            assert sorted(status for status, _ in results) == [201, 409], results
            requested = _per_recipient(engine, ids, event_id, "venue_booking_requested:")
            assert requested == {"staff-a": 1, "staff-b": 1}
    finally:
        app.extensions["engine"].dispose()


# QA-SPL-104-072 | AC7 | WB rollback
def test_qa_spl_104_072_failure_after_the_notice_rolls_both_back(engine, pg_url, monkeypatch):
    ids, organisation_id, venue_id = _seed_accounts(engine)
    event_id = _seed_event(engine, ids, organisation_id, date(2027, 5, 1))
    real = requests_module.add_venue_booking_notices

    def then_fail(session, *args, **kwargs):
        real(session, *args, **kwargs)
        session.flush()
        raise RuntimeError("injected failure after the notice was written")

    monkeypatch.setattr(requests_module, "add_venue_booking_notices", then_fail)
    app = _app(pg_url, ids)
    try:
        with pytest.raises(RuntimeError):
            _request(event_id, venue_id)(app.test_client())
    finally:
        app.extensions["engine"].dispose()
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(VenueBooking)) == 0
        assert session.scalar(select(func.count()).select_from(Notification)) == 0
