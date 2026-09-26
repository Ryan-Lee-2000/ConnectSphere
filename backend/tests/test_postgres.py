"""Verify the migration toolchain against a new disposable PostgreSQL database."""

import os
import subprocess
import sys

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError

PRODUCT_TABLES = {
    "accounts",
    "account_roles",
    "organisations",
    "venues",
    "venue_layouts",
    "event_requests",
    "equipment_requirements",
    "event_coordinator_assignments",
    "event_coordinator_history",
    "event_status_history",
    "venue_operational_blocks",
    "venue_bookings",
    "venue_booking_occupancy",
}
PRODUCT_TABLE_LIST = ", ".join(f"'{table}'" for table in sorted(PRODUCT_TABLES))


@pytest.mark.skipif(
    not os.getenv("INTEGRATION_DATABASE_URL"),
    reason="Run npm run integration with disposable PostgreSQL",
)
def test_empty_baseline_migration_is_rerunnable():
    url = os.environ["INTEGRATION_DATABASE_URL"]
    if not url.startswith("postgresql"):
        pytest.fail("Integration requires PostgreSQL")
    engine = create_engine(url)
    try:
        if inspect(engine).get_table_names():
            pytest.fail("Integration database is not empty; provide a fresh disposable database")
        for _ in range(2):
            subprocess.run(
                [sys.executable, "-m", "alembic", "upgrade", "sprint0_base"],
                check=True,
                env={**os.environ, "DATABASE_URL": url},
            )
        assert inspect(engine).get_table_names() == ["alembic_version"]
        with engine.connect() as conn:
            assert (
                conn.execute(text("select version_num from alembic_version")).scalar()
                == "sprint0_base"
            )
        for _ in range(2):
            subprocess.run(
                [sys.executable, "-m", "alembic", "upgrade", "head"],
                check=True,
                env={**os.environ, "DATABASE_URL": url},
            )
        heads = ScriptDirectory.from_config(Config("alembic.ini")).get_heads()
        assert len(heads) == 1, "Resolve competing migration heads before merging"
        assert set(inspect(engine).get_table_names()) == PRODUCT_TABLES | {"alembic_version"}
        booking_columns = {
            column["name"]: column for column in inspect(engine).get_columns("venue_bookings")
        }
        assert booking_columns["requires_review"]["nullable"] is False
        assert {
            "review_trigger_block_id",
            "review_marked_at",
            "review_marked_by_account_id",
        } <= set(booking_columns)
        with engine.connect() as conn:
            assert set(
                conn.execute(text("select version_num from alembic_version")).scalars()
            ) == set(heads)
            rls_tables = set(
                conn.execute(
                    text(
                        "select relname from pg_class "
                        f"where relname in ({PRODUCT_TABLE_LIST}) "
                        "and relrowsecurity"
                    )
                ).scalars()
            )
            assert rls_tables == PRODUCT_TABLES
            browser_grants = conn.execute(
                text(
                    "select grantee, table_name, privilege_type "
                    "from information_schema.table_privileges "
                    "where table_schema = 'public' "
                    f"and table_name in ({PRODUCT_TABLE_LIST}) "
                    "and grantee in ('PUBLIC', 'anon', 'authenticated')"
                )
            ).all()
            assert browser_grants == []
            # SPL-70 must be able to move a request out of 'submitted'.
            allowed = conn.execute(
                text(
                    "select pg_get_constraintdef(oid) from pg_constraint "
                    "where conname = 'ck_event_requests_known_status'"
                )
            ).scalar()
            assert "under_review" in allowed
        with engine.begin() as conn:
            conn.execute(
                text(
                    "insert into accounts (id, display_name, organisation_id) "
                    "values (:account_id, 'Migration test organiser', "
                    "(select id from organisations where name = 'Existing client organisation'))"
                ),
                {"account_id": "00000000-0000-0000-0000-000000000099"},
            )
            conn.execute(
                text(
                    "insert into event_requests "
                    "(organiser_account_id, organisation_id, name, status) "
                    "values (:account_id, "
                    "(select id from organisations where name = 'Existing client organisation'), "
                    "'An early idea', 'draft')"
                ),
                {"account_id": "00000000-0000-0000-0000-000000000099"},
            )
        with pytest.raises(IntegrityError), engine.begin() as conn:
            conn.execute(
                text(
                    "insert into event_requests "
                    "(organiser_account_id, organisation_id, name, status) "
                    "values (:account_id, "
                    "(select id from organisations where name = 'Existing client organisation'), "
                    "'Incomplete submission', 'submitted')"
                ),
                {"account_id": "00000000-0000-0000-0000-000000000099"},
            )
    finally:
        engine.dispose()
