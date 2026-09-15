"""Verify the migration toolchain against a new disposable PostgreSQL database."""

import os
import subprocess
import sys

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text

PRODUCT_TABLES = {
    "accounts",
    "account_roles",
    "venues",
    "venue_layouts",
    "event_requests",
    "equipment_requirements",
    "event_coordinator_assignments",
    "event_coordinator_history",
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
            # SPL-60 must be able to move a request out of 'submitted'.
            allowed = conn.execute(
                text(
                    "select pg_get_constraintdef(oid) from pg_constraint "
                    "where conname = 'ck_event_requests_known_status'"
                )
            ).scalar()
            assert "under_review" in allowed
    finally:
        engine.dispose()
