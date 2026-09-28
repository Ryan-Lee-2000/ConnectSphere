"""PostgreSQL evidence for SPL-79 (CS-E10-S1): the history migration backfills existing bookings.

Runs only under `npm run integration` (INTEGRATION_DATABASE_URL). The test builds its own
throw-away database on that server, migrates it with Alembic, and drops it afterwards.
"""

import os
import subprocess
import sys
import uuid
from datetime import date, datetime, time

import pytest
from app.event_requests import SINGAPORE
from app.models import (
    Account,
    EventRequest,
    Organisation,
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

PREVIOUS_HEAD = "s2_venue_booking_withdrawal"


def _alembic(url, *arguments):
    return subprocess.run(
        [sys.executable, "-m", "alembic", *arguments],
        capture_output=True,
        text=True,
        env={**os.environ, "DATABASE_URL": url},
    )


@pytest.fixture
def fresh_url():
    server = make_url(os.environ["INTEGRATION_DATABASE_URL"])
    name = f"spl79_{uuid.uuid4().hex[:12]}"
    admin = create_engine(server, isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{name}"'))
    try:
        yield server.set(database=name).render_as_string(hide_password=False)
    finally:
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()


# TC-SPL-79-06 (a)
def test_tc_spl_79_06_existing_bookings_are_backfilled(fresh_url):
    migrated = _alembic(fresh_url, "upgrade", PREVIOUS_HEAD)
    assert migrated.returncode == 0, migrated.stderr
    requested_at = datetime(2026, 9, 27, 21, 15, tzinfo=SINGAPORE)
    withdrawn_at = datetime(2026, 9, 28, 10, 15, tzinfo=SINGAPORE)
    coordinator = str(uuid.uuid4())
    engine = create_engine(fresh_url)
    try:
        with Session(engine) as session:
            organisation = Organisation(name="SPL-79 backfill client")
            session.add(organisation)
            session.flush()
            session.add(
                Account(id=coordinator, display_name="Casey Lim", organisation_id=organisation.id)
            )
            session.flush()
            planning_event = EventRequest(
                organiser_account_id=coordinator,
                organisation_id=organisation.id,
                name="Backfill Forum",
                purpose="Backfill proof",
                proposed_date=date(2026, 10, 14),
                start_time=time(13),
                end_time=time(18),
                expected_attendance=100,
                status="planning",
            )
            venue = Venue(name="Backfill Hall", operating_slots=["PM"])
            session.add_all([planning_event, venue])
            session.flush()
            session.execute(
                text(
                    "INSERT INTO venue_bookings (event_request_id, venue_id, status, "
                    "requires_review, requested_by_account_id, requested_at, "
                    "withdrawn_by_account_id, withdrawn_at) VALUES "
                    "(:event, :venue, 'withdrawn', false, :who, :req, :who, :wd), "
                    "(:event, :venue, 'requested', false, NULL, NULL, NULL, NULL)"
                ),
                {
                    "event": planning_event.id,
                    "venue": venue.id,
                    "who": coordinator,
                    "req": requested_at,
                    "wd": withdrawn_at,
                },
            )
            session.commit()
            withdrawn_id, fixture_id = session.scalars(
                text("SELECT id FROM venue_bookings ORDER BY id")
            ).all()

        upgraded = _alembic(fresh_url, "upgrade", "head")
        assert upgraded.returncode == 0, upgraded.stderr

        with engine.connect() as connection:
            rows = connection.execute(
                text(
                    "SELECT booking_id, action, previous_status, resulting_status, "
                    "actor_account_id, changed_at, note FROM venue_booking_status_history "
                    "ORDER BY changed_at"
                )
            ).all()
        assert [(r.booking_id, r.action, r.previous_status, r.resulting_status) for r in rows] == [
            (withdrawn_id, "request", None, "requested"),
            (withdrawn_id, "withdraw", "requested", "withdrawn"),
        ]
        assert {str(r.actor_account_id) for r in rows} == {coordinator}
        assert [r.changed_at for r in rows] == [requested_at, withdrawn_at]
        assert all(r.note is None for r in rows)
        # A booking stored without request details (an SPL-83 fixture) gets no invented history.
        assert fixture_id not in {r.booking_id for r in rows}
        with Session(engine) as session:
            assert session.get(VenueBooking, fixture_id).status == "requested"
    finally:
        engine.dispose()


def test_spl_79_history_table_has_rls_and_no_browser_grants(fresh_url):
    """Supporting verification: the new table follows the product-table security rule."""

    upgraded = _alembic(fresh_url, "upgrade", "head")
    assert upgraded.returncode == 0, upgraded.stderr
    engine = create_engine(fresh_url)
    try:
        with engine.connect() as connection:
            assert (
                connection.execute(
                    text(
                        "SELECT relrowsecurity FROM pg_class "
                        "WHERE relname = 'venue_booking_status_history'"
                    )
                ).scalar()
                is True
            )
            granted = connection.execute(
                text(
                    "SELECT count(*) FROM information_schema.role_table_grants "
                    "WHERE table_name = 'venue_booking_status_history' "
                    "AND grantee IN ('anon', 'authenticated', 'PUBLIC')"
                )
            ).scalar()
            assert granted == 0
    finally:
        engine.dispose()
