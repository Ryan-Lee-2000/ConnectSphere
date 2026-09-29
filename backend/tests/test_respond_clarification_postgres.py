"""PostgreSQL migration and constraint coverage for SPL-66."""

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


def _alembic(url: str, *arguments: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "alembic", *arguments],
        capture_output=True,
        text=True,
        env={**os.environ, "DATABASE_URL": url},
    )


@pytest.fixture
def engine():
    """Migrate a fresh database so this story proves its real PostgreSQL schema."""

    server = make_url(os.environ["INTEGRATION_DATABASE_URL"])
    name = f"spl66_{uuid.uuid4().hex[:12]}"
    admin = create_engine(server, isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{name}"'))
    url = server.set(database=name).render_as_string(hide_password=False)
    upgraded = _alembic(url, "upgrade", "head")
    assert upgraded.returncode == 0, upgraded.stderr
    migrated = create_engine(url)
    try:
        yield migrated
    finally:
        migrated.dispose()
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()


# TC-SPL-66-02
def test_tc_spl_66_02_response_columns_and_completeness_constraint(engine):
    """The response, trusted respondent and time must be present together or all absent."""

    with engine.connect() as connection:
        columns = {
            row.column_name: (row.data_type, row.is_nullable)
            for row in connection.execute(
                text(
                    "select column_name, data_type, is_nullable "
                    "from information_schema.columns "
                    "where table_name = 'clarification_requests' "
                    "and column_name in ('response', 'respondent_account_id', 'responded_at')"
                )
            )
        }
        constraint = connection.execute(
            text(
                "select pg_get_constraintdef(oid) from pg_constraint "
                "where conname = 'ck_clarification_requests_response_complete'"
            )
        ).scalar_one()

    assert columns == {
        "response": ("text", "YES"),
        "respondent_account_id": ("uuid", "YES"),
        "responded_at": ("timestamp with time zone", "YES"),
    }
    assert "response IS NULL" in constraint
    assert "respondent_account_id IS NOT NULL" in constraint


# TC-SPL-66-02
def test_tc_spl_66_02_partial_response_evidence_is_rejected_by_postgres(engine):
    """PostgreSQL rejects partial evidence even if an application write bypasses Flask."""

    # Reuse seeded accounts and an event created by the baseline migration's seed-independent
    # schema through compact SQL; only the constraint behaviour is under test here.
    account_id = str(uuid.uuid4())
    with engine.begin() as connection:
        organisation_id = connection.execute(
            text("insert into organisations (name) values ('SPL-66 Test Client') returning id")
        ).scalar_one()
        connection.execute(
            text(
                "insert into accounts (id, display_name, is_active, organisation_id) "
                "values (:id, 'Actor', true, :organisation)"
            ),
            {"id": account_id, "organisation": organisation_id},
        )
        event_id = connection.execute(
            text(
                "insert into event_requests "
                "(organiser_account_id, organisation_id, name, purpose, proposed_date, "
                "start_time, end_time, "
                "expected_attendance, status, required_facilities, accessibility_needs, "
                "registration_required) values "
                "(:actor, :organisation, 'Forum', 'Test', '2026-12-01', '09:00', '12:00', 10, "
                "'returned_for_clarification', '[]'::json, '[]'::json, false) returning id"
            ),
                {"actor": account_id, "organisation": organisation_id},
        ).scalar_one()
        clarification_id = connection.execute(
            text(
                "insert into clarification_requests "
                "(event_request_id, message, author_account_id, created_at) "
                "values (:event, 'Question', :actor, now()) returning id"
            ),
            {"event": event_id, "actor": account_id},
        ).scalar_one()

    with engine.connect() as connection:
        transaction = connection.begin()
        with pytest.raises(IntegrityError):
            connection.execute(
                text("update clarification_requests set response = 'Answer' where id = :id"),
                {"id": clarification_id},
            )
        transaction.rollback()
