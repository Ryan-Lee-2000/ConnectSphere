"""PostgreSQL evidence for SPL-114 (CS-E19-S1): the migration, and the database's own guards.

The server tests run on SQLite, which builds tables straight from the models and never runs a
migration. This case proves the real path: the Alembic migration upgrades, downgrades and
re-upgrades on PostgreSQL 17 (the CI image), and once applied, the database itself refuses
registration settings the route would also refuse. That second layer matters because a future
route that forgets a check still cannot store an impossible period or capacity.

This case runs only under `npm run integration` (INTEGRATION_DATABASE_URL). It builds its own
throw-away database, migrates it with Alembic, and drops it afterwards.
"""

import os
import subprocess
import sys
import uuid
from datetime import date, datetime, time
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from app.event_requests import SINGAPORE
from app.models import Account, EventRequest, Organisation
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

pytestmark = pytest.mark.skipif(
    not os.getenv("INTEGRATION_DATABASE_URL"),
    reason="Run npm run integration with disposable PostgreSQL",
)


def _migrations():
    """The project's Alembic migration scripts, read from disk (no database needed)."""

    config = Config()
    config.set_main_option(
        "script_location", str(Path(__file__).resolve().parents[1] / "migrations")
    )
    return ScriptDirectory.from_config(config)


def _alembic(url, *args):
    """Run an Alembic command against the throw-away database and fail loudly if it errors."""

    result = subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        capture_output=True,
        text=True,
        env={**os.environ, "DATABASE_URL": url},
    )
    assert result.returncode == 0, result.stderr


@pytest.fixture
def pg_url():
    server = make_url(os.environ["INTEGRATION_DATABASE_URL"])
    name = f"spl114_{uuid.uuid4().hex[:12]}"
    admin = create_engine(server, isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{name}"'))
    url = server.set(database=name).render_as_string(hide_password=False)
    try:
        _alembic(url, "upgrade", "head")
        yield url
    finally:
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()


def _event_id(engine):
    """One Confirmed event with registration still off."""

    with Session(engine) as session:
        organisation = Organisation(name=f"SPL-114 client {uuid.uuid4()}")
        session.add(organisation)
        session.flush()
        organiser = Account(
            id=str(uuid.uuid4()), display_name="Devon Lee", organisation_id=organisation.id
        )
        session.add(organiser)
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
        )
        session.add(event)
        session.commit()
        return event.id


def _set(engine, event_id, opens_at, closes_at, capacity):
    """Write the three settings directly, bypassing the route, as a buggy route would."""

    with Session(engine) as session:
        event = session.get(EventRequest, event_id)
        event.registration_opens_at = opens_at
        event.registration_closes_at = closes_at
        event.registration_capacity = capacity
        session.commit()


OPENS = datetime(2026, 10, 10, 9, tzinfo=SINGAPORE)
CLOSES = datetime(2026, 11, 19, 18, tzinfo=SINGAPORE)


# TC-SPL-114-17
# SPL-114 AC-2,3,6 Test-17
def test_tc_spl_114_17_migration_round_trips_and_the_database_refuses_bad_settings(pg_url):
    # The migration can be undone and redone cleanly, so a failed deploy can roll back. Roll back
    # to whatever this migration currently follows, read from the migration itself, so re-pointing
    # it after another story's migration merges never means editing this test.
    parent = _migrations().get_revision("s3_registration_settings").down_revision
    _alembic(pg_url, "downgrade", parent)
    engine = create_engine(pg_url)
    try:
        assert "registration_settings_history" not in inspect(engine).get_table_names()
        assert "registration_capacity" not in {
            column["name"] for column in inspect(engine).get_columns("event_requests")
        }
    finally:
        engine.dispose()
    _alembic(pg_url, "upgrade", "head")

    engine = create_engine(pg_url)
    try:
        event_id = _event_id(engine)

        # Each of these breaks one database rule, so each must be refused by PostgreSQL itself.
        for opens_at, closes_at, capacity in (
            (CLOSES, OPENS, 100),  # closes before it opens
            (OPENS, OPENS, 100),  # opens and closes at the same instant
            (OPENS, CLOSES, 0),  # no places
            (OPENS, None, 100),  # incomplete: no closing time
        ):
            with pytest.raises(IntegrityError):
                _set(engine, event_id, opens_at, closes_at, capacity)

        # Not vacuous: a valid setting is stored, and comes back as the same instant.
        _set(engine, event_id, OPENS, CLOSES, 100)
        with Session(engine) as session:
            event = session.get(EventRequest, event_id)
            assert event.registration_opens_at == OPENS
            assert event.registration_closes_at == CLOSES
            assert event.registration_capacity == 100
    finally:
        engine.dispose()
