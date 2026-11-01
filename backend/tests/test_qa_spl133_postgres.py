"""PostgreSQL evidence for SPL-133: expiry racing approval, and the hold-expiry migration.

SQLite serialises writes, so it cannot show a race. These cases run only under
`npm run integration` (INTEGRATION_DATABASE_URL), reusing SPL-85's throw-away database fixture,
seeded accounts and race harness. Holds are seeded with a deadline already passed, so the real
clock is after it.
"""

import os
import subprocess
import sys
import threading
import time as clock
import uuid
from datetime import date, datetime, time, timedelta, timezone

import pytest
import test_event_confirmation_postgres as spl85
from app import venue_hold_expiry
from app.exact_venue_bookings import lock_event, lock_venue
from app.models import (
    EventCoordinatorAssignment,
    EventRequest,
    Notification,
    VenueBooking,
    VenueBookingOccupancy,
    VenueBookingStatusHistory,
)
from sqlalchemy import create_engine, func, inspect, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

pytestmark = pytest.mark.skipif(
    not os.getenv("INTEGRATION_DATABASE_URL"),
    reason="Run npm run integration with disposable PostgreSQL",
)

RUNS = 3
SGT = timezone(timedelta(hours=8))
pg_url, engine = spl85.pg_url, spl85.engine


def _due_hold(engine, ids, organisation_id, venue_id, day):
    """A Planning event holding a Requested booking (with a PM claim) whose deadline has passed."""

    now = datetime.now(SGT)
    with Session(engine) as session:
        event = EventRequest(
            organiser_account_id=ids["organiser"],
            organisation_id=organisation_id,
            name=f"Expiry race {day.isoformat()}",
            purpose="Concurrency proof",
            proposed_date=day,
            start_time=time(13),
            end_time=time(18),
            expected_attendance=100,
            status="planning",
            submitted_at=now,
        )
        session.add(event)
        session.flush()
        session.add(
            EventCoordinatorAssignment(
                event_request_id=event.id,
                coordinator_account_id=ids["coordinator"],
                assigned_by_account_id=ids["lead"],
                assigned_at=now,
            )
        )
        booking = VenueBooking(
            event_request_id=event.id,
            venue_id=venue_id,
            status="requested",
            layout="theatre",
            expected_attendance=100,
            booking_date=day,
            event_slots=["PM"],
            requested_by_account_id=ids["coordinator"],
            requested_at=now - timedelta(days=7),
            expires_at=now - timedelta(minutes=1),
        )
        session.add(booking)
        session.flush()
        session.add(
            VenueBookingOccupancy(
                booking_id=booking.id, venue_id=venue_id, day=day, slot="PM", kind="event"
            )
        )
        session.commit()
        return booking.id


def _approve(booking_id):
    return lambda client: client.post(
        f"/api/venue-bookings/{booking_id}/approve",
        json={},
        headers={"Authorization": "Bearer staff"},
    )


def _queue():
    return lambda client: client.get(
        "/api/venue-bookings/pending", headers={"Authorization": "Bearer staff"}
    )


# QA-SPL-133-100 | AC4/AC10 | BB concurrency
def test_qa_spl_133_100_approval_racing_expiry_ends_expired_once(engine, pg_url):
    ids, organisation_id, venue_id, _ = spl85._seed_accounts(engine)
    app = spl85._app(pg_url, ids)
    try:
        for run in range(RUNS):
            day = date(2027, 5, 3) + timedelta(days=run)
            booking_id = _due_hold(engine, ids, organisation_id, venue_id, day)

            (approve_status, approve_body), (queue_status, _) = spl85._race(
                app, [_approve(booking_id), _queue()]
            )

            assert approve_status == 409, approve_body
            assert "can no longer be approved" in approve_body["error"]
            assert queue_status == 200
            with Session(engine) as session:
                assert session.get(VenueBooking, booking_id).status == "expired"
                expiries = session.scalar(
                    select(func.count(VenueBookingStatusHistory.id)).where(
                        VenueBookingStatusHistory.booking_id == booking_id,
                        VenueBookingStatusHistory.action == "expire",
                    )
                )
                notices = session.scalar(
                    select(func.count(Notification.id)).where(
                        Notification.dedupe_key == f"arrangement_hold_expired:{booking_id}"
                    )
                )
                claims = session.scalar(
                    select(func.count(VenueBookingOccupancy.id)).where(
                        VenueBookingOccupancy.booking_id == booking_id
                    )
                )
            assert (expiries, notices, claims) == (1, 1, 0)
    finally:
        app.extensions["engine"].dispose()


# QA-SPL-133-101 | AC10 | BB concurrency
def test_qa_spl_133_101_two_requests_after_the_deadline_expire_once(engine, pg_url):
    ids, organisation_id, venue_id, _ = spl85._seed_accounts(engine)
    app = spl85._app(pg_url, ids)
    try:
        for run in range(RUNS):
            day = date(2027, 6, 7) + timedelta(days=run)
            booking_id = _due_hold(engine, ids, organisation_id, venue_id, day)

            results = spl85._race(app, [_queue(), _queue()])

            assert [status for status, _ in results] == [200, 200]
            with Session(engine) as session:
                assert session.get(VenueBooking, booking_id).status == "expired"
                assert (
                    session.scalar(
                        select(func.count(Notification.id)).where(
                            Notification.dedupe_key == f"arrangement_hold_expired:{booking_id}"
                        )
                    )
                    == 1
                )
    finally:
        app.extensions["engine"].dispose()


# QA-SPL-133-102 | AC1/AC5 | WB migration
def test_qa_spl_133_102_migration_adds_the_deadline_and_the_expired_status(engine):
    inspector = inspect(engine)
    columns = {column["name"]: column for column in inspector.get_columns("venue_bookings")}
    assert columns["expires_at"]["nullable"] is True
    history = {c["name"]: c for c in inspector.get_columns("venue_booking_status_history")}
    assert history["actor_account_id"]["nullable"] is True
    indexes = {index["name"]: index for index in inspector.get_indexes("venue_bookings")}
    assert indexes["ix_venue_bookings_status_expires_at"]["column_names"] == [
        "status",
        "expires_at",
    ]
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == (
            "s4_notification_types"
        )
    ids, organisation_id, venue_id, _ = spl85._seed_accounts(engine)
    booking_id = _due_hold(engine, ids, organisation_id, venue_id, date(2027, 7, 1))
    with Session(engine) as session:
        session.get(VenueBooking, booking_id).status = "expired"
        session.commit()
    with Session(engine) as session, pytest.raises(IntegrityError):
        session.execute(
            text("UPDATE venue_bookings SET status = 'lapsed' WHERE id = :id"), {"id": booking_id}
        )


def _alembic(url, *args):
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        capture_output=True,
        text=True,
        env={**os.environ, "DATABASE_URL": url},
    )


@pytest.fixture
def fresh_url():
    server = make_url(os.environ["INTEGRATION_DATABASE_URL"])
    name = f"spl133_{uuid.uuid4().hex[:12]}"
    admin = create_engine(server, isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{name}"'))
    try:
        yield server.set(database=name).render_as_string(hide_password=False)
    finally:
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()


# QA-SPL-133-103 | AC1 (cutover) | WB migration
def test_qa_spl_133_103_cutover_gives_existing_holds_the_default_deadline(fresh_url):
    assert _alembic(fresh_url, "upgrade", "s4_event_completion").returncode == 0
    legacy = create_engine(fresh_url)
    near = (datetime.now(SGT) + timedelta(days=2)).date()
    far = (datetime.now(SGT) + timedelta(days=60)).date()
    try:
        with legacy.begin() as connection:
            organisation = connection.scalar(
                text("INSERT INTO organisations (name) VALUES ('Cutover client') RETURNING id")
            )
            account = str(uuid.uuid4())
            connection.execute(
                text(
                    "INSERT INTO accounts (id, display_name, organisation_id, is_active) "
                    "VALUES (:id, 'Olive', :org, true)"
                ),
                {"id": account, "org": organisation},
            )
            venue = connection.scalar(
                text(
                    "INSERT INTO venues (name, operating_slots, setup_buffer_slots, "
                    "turnaround_buffer_slots, facilities, accessibility_features) VALUES "
                    "('Cutover Hall', '[\"AM\",\"PM\",\"NIGHT\"]', 0, 0, '[]', '[]') RETURNING id"
                )
            )
            bookings = {}
            for label, day, status in (
                ("near", near, "requested"),
                ("far", far, "requested"),
                ("approved", far, "approved"),
            ):
                event = connection.scalar(
                    text(
                        "INSERT INTO event_requests (organiser_account_id, organisation_id, name, "
                        "status, proposed_date, start_time, end_time, expected_attendance, "
                        "required_facilities, accessibility_needs, registration_required, "
                        "submitted_at) VALUES (:account, :org, :name, 'planning', :day, '09:00', "
                        "'11:00', 50, '[]', '[]', false, now()) RETURNING id"
                    ),
                    {"account": account, "org": organisation, "name": label, "day": day},
                )
                bookings[label] = connection.scalar(
                    text(
                        "INSERT INTO venue_bookings (event_request_id, venue_id, status, "
                        "booking_date, event_slots) VALUES (:event, :venue, :status, :day, "
                        "'[\"AM\"]') RETURNING id"
                    ),
                    {"event": event, "venue": venue, "status": status, "day": day},
                )
    finally:
        legacy.dispose()
    before = datetime.now(SGT)

    upgraded = _alembic(fresh_url, "upgrade", "head")

    assert upgraded.returncode == 0, upgraded.stderr
    after = datetime.now(SGT)
    current = create_engine(fresh_url)
    try:
        with current.connect() as connection:
            stored = {
                label: connection.scalar(
                    text("SELECT expires_at FROM venue_bookings WHERE id = :id"), {"id": booking_id}
                )
                for label, booking_id in bookings.items()
            }
    finally:
        current.dispose()
    assert stored["near"] == datetime.combine(near, time(9), tzinfo=SGT)
    assert before + timedelta(days=7) <= stored["far"] <= after + timedelta(days=7)
    assert stored["approved"] is None


# QA-SPL-133-104 | AC10 | WB migration
def test_qa_spl_133_104_downgrade_refuses_while_expired_holds_exist(fresh_url):
    assert _alembic(fresh_url, "upgrade", "head").returncode == 0
    current = create_engine(fresh_url)
    try:
        ids, organisation_id, venue_id, _ = spl85._seed_accounts(current)
        booking_id = _due_hold(current, ids, organisation_id, venue_id, date(2027, 8, 2))
        with Session(current) as session:
            session.get(VenueBooking, booking_id).status = "expired"
            session.commit()
    finally:
        current.dispose()

    refused = _alembic(fresh_url, "downgrade", "s4_event_completion")

    assert refused.returncode != 0
    assert "Cannot downgrade SPL-133" in refused.stderr
    check = create_engine(fresh_url)
    try:
        with check.connect() as connection:
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == (
                "s4_notification_types"
            )
    finally:
        check.dispose()


# QA-SPL-133-105 | AC10 | WB migration
def test_qa_spl_133_105_migration_downgrades_and_upgrades_cleanly_when_empty(fresh_url):
    assert _alembic(fresh_url, "upgrade", "head").returncode == 0
    down = _alembic(fresh_url, "downgrade", "s4_event_completion")
    assert down.returncode == 0, down.stderr
    check = create_engine(fresh_url)
    try:
        names = {column["name"] for column in inspect(check).get_columns("venue_bookings")}
        assert "expires_at" not in names
    finally:
        check.dispose()
    up = _alembic(fresh_url, "upgrade", "head")
    assert up.returncode == 0, up.stderr


def _wait_for_a_lock_wait(engine, timeout=15):
    """Block until some session in this database is waiting on a row lock."""

    deadline = clock.monotonic() + timeout
    with engine.connect() as connection:
        while clock.monotonic() < deadline:
            waiting = connection.scalar(
                text(
                    "SELECT count(*) FROM pg_stat_activity WHERE datname = current_database() "
                    "AND wait_event_type = 'Lock'"
                )
            )
            if waiting:
                return
            clock.sleep(0.05)
    raise AssertionError("The expiry batch never waited for the second event's lock.")


# QA-SPL-133-106 | AC10 | BB concurrency (review round 1)
def test_qa_spl_133_106_the_expiry_batch_cannot_deadlock_a_booking_operation(engine, pg_url):
    """Two due holds for different events at one venue, while another operation holds event B.

    That operation then needs the venue (SPL-137 order for event B: event, then venue). Expiry
    must not still hold the venue from event A while it waits for event B.
    """

    ids, organisation_id, venue_id, _ = spl85._seed_accounts(engine)
    first = _due_hold(engine, ids, organisation_id, venue_id, date(2027, 9, 6))
    second = _due_hold(engine, ids, organisation_id, venue_id, date(2027, 9, 7))
    with Session(engine) as session:
        second_event = session.get(VenueBooking, second).event_request_id
    app = spl85._app(pg_url, ids)
    errors = []

    def expire_batch():
        try:
            with app.app_context(), Session(engine) as session:
                venue_hold_expiry.process_due_holds(session, datetime.now(SGT))
        except Exception as error:  # recorded and asserted below
            errors.append(error)

    operation = Session(engine)
    try:
        lock_event(operation, second_event)
        worker = threading.Thread(target=expire_batch)
        worker.start()
        _wait_for_a_lock_wait(engine)
        try:
            lock_venue(operation, venue_id)
            operation.commit()
        except Exception as error:  # a deadlock is reported to one of the two sessions
            errors.append(error)
            operation.rollback()
    finally:
        operation.close()
    worker.join(timeout=30)

    try:
        assert not worker.is_alive()
        assert errors == []
        with Session(engine) as session:
            assert [session.get(VenueBooking, item).status for item in (first, second)] == [
                "expired",
                "expired",
            ]
            for booking_id in (first, second):
                assert (
                    session.scalar(
                        select(func.count(Notification.id)).where(
                            Notification.dedupe_key == f"arrangement_hold_expired:{booking_id}"
                        )
                    )
                    == 1
                )
    finally:
        app.extensions["engine"].dispose()
