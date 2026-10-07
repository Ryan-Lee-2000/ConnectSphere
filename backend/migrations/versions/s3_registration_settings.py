"""Store attendee registration settings and their change history (SPL-114).

Revision ID: s3_registration_settings
Revises: s3_exact_booking_snapshots (SPL-137, the newest migration on main when this was rebased)

Two changes, both additive so the previous application version keeps working while this deploys:

1. Three nullable columns on ``event_requests``: when registration opens, when it closes and how
   many places there are. All three stay null until the coordinator enables registration, so every
   existing event starts with registration off (AC5).
2. A new ``registration_settings_history`` table: one row per save, holding the old and new
   settings, who saved them and when (AC6).

The check constraints are the same text the SQLAlchemy model uses (imported from app.models), so
the database itself refuses an incomplete setting, a period that closes before it opens, or a
capacity below one, even if a future route forgot to validate.
"""

import sqlalchemy as sa
from alembic import op
from app.models import (
    REGISTRATION_CAPACITY_POSITIVE,
    REGISTRATION_PERIOD_ORDER,
    REGISTRATION_SETTINGS_COMPLETE,
)

revision = "s3_registration_settings"
down_revision = "s3_exact_booking_snapshots"
branch_labels = None
depends_on = None

EVENTS = "event_requests"
HISTORY = "registration_settings_history"
CONSTRAINTS = {
    "ck_event_requests_registration_complete": REGISTRATION_SETTINGS_COMPLETE,
    "ck_event_requests_registration_period": REGISTRATION_PERIOD_ORDER,
    "ck_event_requests_registration_capacity": REGISTRATION_CAPACITY_POSITIVE,
}


def upgrade():
    # 1. The current settings live on the event itself, so every later story (SPL-115/116) can
    #    read them with the event and no extra join.
    with op.batch_alter_table(EVENTS) as batch:
        batch.add_column(sa.Column("registration_opens_at", sa.DateTime(timezone=True)))
        batch.add_column(sa.Column("registration_closes_at", sa.DateTime(timezone=True)))
        batch.add_column(sa.Column("registration_capacity", sa.Integer()))
        for name, condition in CONSTRAINTS.items():
            batch.create_check_constraint(name, condition)

    # 2. The audit trail. Rows are only ever inserted, never updated, so the history cannot be
    #    rewritten after the fact.
    op.create_table(
        HISTORY,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "event_request_id",
            sa.Integer(),
            sa.ForeignKey("event_requests.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # Null "previous" values mean this row is the first enabling.
        sa.Column("previous_opens_at", sa.DateTime(timezone=True)),
        sa.Column("previous_closes_at", sa.DateTime(timezone=True)),
        sa.Column("previous_capacity", sa.Integer()),
        sa.Column("opens_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closes_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("capacity", sa.Integer(), nullable=False),
        sa.Column(
            "changed_by_account_id",
            sa.Uuid(as_uuid=False),
            sa.ForeignKey("accounts.id"),
            nullable=False,
        ),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(f"ix_{HISTORY}_event_request_id", HISTORY, ["event_request_id"])

    # Same lock-down as every other product table: row-level security on, and no direct access
    # for the browser's Supabase roles. All reads and writes go through Flask (AGENTS.md).
    op.execute(f"ALTER TABLE {HISTORY} ENABLE ROW LEVEL SECURITY")
    op.execute(f"REVOKE ALL ON TABLE {HISTORY} FROM PUBLIC")
    op.execute(f"REVOKE ALL ON SEQUENCE {HISTORY}_id_seq FROM PUBLIC")
    op.execute(
        f"""
        DO $$
        DECLARE
            role_name text;
        BEGIN
            FOREACH role_name IN ARRAY ARRAY['anon', 'authenticated']
            LOOP
                IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = role_name) THEN
                    EXECUTE format('REVOKE ALL ON TABLE {HISTORY} FROM %I', role_name);
                    EXECUTE format('REVOKE ALL ON SEQUENCE {HISTORY}_id_seq FROM %I', role_name);
                END IF;
            END LOOP;
        END $$;
        """
    )


def downgrade():
    # Reverse order: drop the history first, then the columns and their constraints.
    op.drop_table(HISTORY)
    with op.batch_alter_table(EVENTS) as batch:
        for name in CONSTRAINTS:
            batch.drop_constraint(name, type_="check")
        batch.drop_column("registration_capacity")
        batch.drop_column("registration_closes_at")
        batch.drop_column("registration_opens_at")
