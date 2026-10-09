"""PostgreSQL migration evidence for SPL-90 equipment requirements.

SQLite route tests prove the API rejects bad input.  These focused tests prove the
database migration itself also protects real PostgreSQL data, including an upgrade
where an organiser's existing free-text requirement is already present.
"""

import os
import subprocess
import sys
import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError

pytestmark = pytest.mark.skipif(
    not os.getenv("INTEGRATION_DATABASE_URL"),
    reason="Run npm run integration with disposable PostgreSQL",
)

PARENT_REVISION = "s3_timed_venue_closures"
TARGET_REVISION = "s3_equipment_requirements"


@pytest.fixture
def pg_url():
    """Create one isolated database so migration checks never touch shared test data."""

    server = make_url(os.environ["INTEGRATION_DATABASE_URL"])
    database_name = f"spl90_{uuid.uuid4().hex[:12]}"
    admin = create_engine(server, isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{database_name}"'))
    url = server.set(database=database_name).render_as_string(hide_password=False)
    try:
        yield url
    finally:
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{database_name}" WITH (FORCE)'))
        admin.dispose()


def migrate(url, revision):
    """Run one Alembic target against this test's private PostgreSQL database."""

    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", revision],
        capture_output=True,
        text=True,
        env={**os.environ, "DATABASE_URL": url},
    )
    assert result.returncode == 0, result.stderr


def seed_legacy_requirement(engine):
    """Insert a pre-SPL-90 organiser line exactly as a populated upgrade would contain."""

    organiser_id = "00000000-0000-0000-0000-000000000090"
    with engine.begin() as connection:
        connection.execute(
            text("INSERT INTO organisations (id, name) VALUES (90, 'SPL-90 migration client')")
        )
        connection.execute(
            text(
                "INSERT INTO accounts (id, display_name, organisation_id) "
                "VALUES (:id, 'Legacy organiser', 90)"
            ),
            {"id": organiser_id},
        )
        connection.execute(
            text(
                "INSERT INTO event_requests "
                "(id, organiser_account_id, organisation_id, name, purpose, proposed_date, "
                "start_time, end_time, expected_attendance, status) "
                "VALUES (90, :organiser_id, 90, 'Legacy equipment event', 'Workshop', "
                "'2026-11-18', '09:00', '12:00', 40, 'planning')"
            ),
            {"organiser_id": organiser_id},
        )
        connection.execute(
            text(
                "INSERT INTO equipment_requirements "
                "(id, event_request_id, equipment_type, quantity, notes) "
                "VALUES (90, 90, 'Original organiser projector request', 2, 'Keep this wording')"
            )
        )


# TC-SPL-90-012: a populated upgrade keeps the organiser's original line and backfills dates.
def test_tc_spl_90_012_populated_upgrade_backfills_existing_requirement(pg_url):
    migrate(pg_url, PARENT_REVISION)
    engine = create_engine(pg_url)
    try:
        seed_legacy_requirement(engine)
        migrate(pg_url, TARGET_REVISION)
        with engine.connect() as connection:
            requirement = (
                connection.execute(text("SELECT * FROM equipment_requirements WHERE id = 90"))
                .mappings()
                .one()
            )
        assert requirement["equipment_type"] == "Original organiser projector request"
        assert requirement["quantity"] == 2
        assert requirement["notes"] == "Keep this wording"
        assert requirement["equipment_type_id"] is None
        assert str(requirement["required_start_date"]) == "2026-11-18"
        assert str(requirement["required_end_date"]) == "2026-11-18"
        assert requirement["status"] == "unmapped"
        assert requirement["essentiality"] == "undecided"
    finally:
        engine.dispose()


# TC-SPL-90-013: PostgreSQL, not only the API, rejects invented state values.
@pytest.mark.parametrize(
    ("column", "invalid_value", "constraint"),
    [
        ("status", "invented", "ck_equipment_requirements_known_status"),
        ("essentiality", "maybe", "ck_equipment_requirements_known_essentiality"),
    ],
)
def test_tc_spl_90_013_postgres_rejects_invalid_requirement_state(
    pg_url, column, invalid_value, constraint
):
    migrate(pg_url, PARENT_REVISION)
    engine = create_engine(pg_url)
    try:
        seed_legacy_requirement(engine)
        migrate(pg_url, TARGET_REVISION)
        with pytest.raises(IntegrityError, match=constraint):
            with engine.begin() as connection:
                connection.execute(
                    text(f"UPDATE equipment_requirements SET {column} = :value WHERE id = 90"),
                    {"value": invalid_value},
                )
    finally:
        engine.dispose()
