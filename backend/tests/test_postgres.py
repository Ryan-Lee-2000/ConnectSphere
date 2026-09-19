"""Verify the migration toolchain against a new disposable PostgreSQL database."""

import os
import subprocess
import sys

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError


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
        assert set(inspect(engine).get_table_names()) == {
            "accounts",
            "account_roles",
            "alembic_version",
            "venues",
            "venue_layouts",
            "event_requests",
            "equipment_requirements",
        }
        with engine.connect() as conn:
            assert set(
                conn.execute(text("select version_num from alembic_version")).scalars()
            ) == set(heads)
            rls_tables = set(
                conn.execute(
                    text(
                        "select relname from pg_class "
                        "where relname in ('accounts', 'account_roles', 'venues', 'venue_layouts', "
                        "'event_requests', 'equipment_requirements') "
                        "and relrowsecurity"
                    )
                ).scalars()
            )
            assert rls_tables == {
                "accounts",
                "account_roles",
                "venues",
                "venue_layouts",
                "event_requests",
                "equipment_requirements",
            }
            browser_grants = conn.execute(
                text(
                    "select grantee, table_name, privilege_type "
                    "from information_schema.table_privileges "
                    "where table_schema = 'public' "
                    "and table_name in ('accounts', 'account_roles', 'venues', 'venue_layouts', "
                    "'event_requests', 'equipment_requirements') "
                    "and grantee in ('PUBLIC', 'anon', 'authenticated')"
                )
            ).all()
            assert browser_grants == []
        with engine.begin() as conn:
            conn.execute(
                text("insert into accounts (id) values (:account_id)"),
                {"account_id": "00000000-0000-0000-0000-000000000099"},
            )
            conn.execute(
                text(
                    "insert into event_requests (organiser_account_id, name, status) "
                    "values (:account_id, 'An early idea', 'draft')"
                ),
                {"account_id": "00000000-0000-0000-0000-000000000099"},
            )
        with pytest.raises(IntegrityError), engine.begin() as conn:
            conn.execute(
                text(
                    "insert into event_requests (organiser_account_id, name, status) "
                    "values (:account_id, 'Incomplete submission', 'submitted')"
                ),
                {"account_id": "00000000-0000-0000-0000-000000000099"},
            )
    finally:
        engine.dispose()
