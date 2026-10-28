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
    "equipment_reservations",
    # SPL-98: append-only history for partial and whole-event equipment releases.
    "equipment_reservation_releases",
    "equipment_types",
    "event_coordinator_assignments",
    "event_coordinator_history",
    "event_status_history",
    # SPL-108: append-only audit for assigned-coordinator ordinary information edits.
    "event_detail_changes",
    "clarification_requests",
    "notifications",
    "venue_operational_blocks",
    "venue_bookings",
    "venue_booking_occupancy",
    "venue_booking_status_history",
    # SPL-130: one persisted, independently resolvable cause per affected booking.
    "venue_booking_review_findings",
    "registration_settings_history",
    "event_registrations",
    # SPL-92: Technical Support's notes and questions on requirement lines.
    "equipment_review_notes",
    # SPL-96: the history behind each equipment type's unavailable-unit total.
    "equipment_unavailability_records",
    # SPL-93: requirement-level unavailable/restored audit history.
    "equipment_requirement_unavailability_records",
    # SPL-91: every coordinator change or removal of a requirement line.
    "equipment_requirement_changes",
    # SPL-111: organiser change requests and their items.
    "event_change_requests",
    "event_change_request_items",
    # SPL-135: server-owned safety-review evidence for the preparation gate.
    "safety_reviews",
    # SPL-125: one email record per notice, sent or failed.
    "email_deliveries",
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
        # TC-SPL-129-08: upgrade populated legacy evidence, not only an empty schema.
        subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "s2_clarification_responses"],
            check=True,
            env={**os.environ, "DATABASE_URL": url},
        )
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO venues (id, name, facilities, accessibility_features, "
                    "operating_slots, "
                    "setup_buffer_slots, turnaround_buffer_slots) "
                    "VALUES (99129, 'Legacy timing fixture', '[]', '[]', '[\"AM\",\"PM\"]', 1, 0)"
                )
            )
            conn.execute(text("INSERT INTO organisations (id,name) VALUES (99129,'Legacy client')"))
            conn.execute(
                text(
                    "INSERT INTO accounts (id,display_name) "
                    "VALUES ('00000000-0000-0000-0000-000000099129','Legacy owner')"
                )
            )
            conn.execute(
                text(
                    "INSERT INTO event_requests (id,organiser_account_id,organisation_id,"
                    "name,status,required_facilities,accessibility_needs,registration_required) "
                    "VALUES (99129,'00000000-0000-0000-0000-000000099129',"
                    "99129,'Legacy event','draft','[]','[]',false)"
                )
            )
            conn.execute(
                text(
                    "INSERT INTO venue_bookings (id,event_request_id,venue_id,status) "
                    "VALUES (99129,99129,99129,'requested')"
                )
            )
            conn.execute(
                text(
                    "INSERT INTO venue_booking_occupancy "
                    "(booking_id,venue_id,occupancy_date,slot,kind) "
                    "VALUES (99129,99129,'2026-10-12','AM','setup')"
                )
            )
            evidence_before = (
                conn.execute(text("SELECT * FROM venue_booking_occupancy WHERE booking_id=99129"))
                .mappings()
                .one()
            )
        for _ in range(2):
            subprocess.run(
                [sys.executable, "-m", "alembic", "upgrade", "head"],
                check=True,
                env={**os.environ, "DATABASE_URL": url},
            )
        with engine.begin() as conn:
            venue = conn.execute(text("SELECT * FROM venues WHERE id=99129")).mappings().one()
            assert venue["operating_slots"] == ["AM", "PM"]
            assert venue["setup_buffer_slots"] == 1
            assert venue["setup_minutes"] is None and venue["turnaround_minutes"] is None
            assert venue["operating_intervals"] is None and venue["timing_revision"] == 0
            assert (
                conn.execute(text("SELECT * FROM venue_booking_occupancy WHERE booking_id=99129"))
                .mappings()
                .one()
                == evidence_before
            )
            # Remove only these test-owned rows, retaining the migrated schema for later checks.
            for table in ("venue_bookings", "event_requests", "venues", "organisations"):
                conn.execute(text(f"DELETE FROM {table} WHERE id=99129"))
            conn.execute(
                text("DELETE FROM accounts WHERE id='00000000-0000-0000-0000-000000099129'")
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
        withdrawal_columns = {
            column["name"]: column for column in inspect(engine).get_columns("event_requests")
        }
        # SPL-108 is additive: all ordinary-information columns start nullable for legacy rows.
        assert {
            "event_notes",
            "event_contact_name",
            "event_contact_email",
            "event_contact_phone",
        } <= set(withdrawal_columns)
        assert all(
            withdrawal_columns[column]["nullable"]
            for column in (
                "event_notes",
                "event_contact_name",
                "event_contact_email",
                "event_contact_phone",
            )
        )
        detail_change_foreign_keys = inspect(engine).get_foreign_keys("event_detail_changes")
        assert any(
            foreign_key["constrained_columns"] == ["event_request_id"]
            and foreign_key["referred_table"] == "event_requests"
            and foreign_key["options"].get("ondelete") == "CASCADE"
            for foreign_key in detail_change_foreign_keys
        )
        assert any(
            foreign_key["constrained_columns"] == ["changed_by_account_id"]
            and foreign_key["referred_table"] == "accounts"
            for foreign_key in detail_change_foreign_keys
        )
        assert withdrawal_columns["withdrawn_by_account_id"]["nullable"] is True
        assert withdrawal_columns["withdrawn_at"]["nullable"] is True
        assert withdrawal_columns["withdrawal_note"]["nullable"] is True
        assert any(
            constraint["name"] == "ck_event_requests_withdrawal_complete"
            for constraint in inspect(engine).get_check_constraints("event_requests")
        )
        assert any(
            foreign_key["constrained_columns"] == ["withdrawn_by_account_id"]
            and foreign_key["referred_table"] == "accounts"
            for foreign_key in inspect(engine).get_foreign_keys("event_requests")
        )
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
