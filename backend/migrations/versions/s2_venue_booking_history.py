"""Record every venue-booking status change (SPL-79).

Revision ID: s2_venue_booking_history
Revises: s2_venue_booking_withdrawal
"""

import sqlalchemy as sa
from alembic import op

revision = "s2_venue_booking_history"
down_revision = "s2_venue_booking_withdrawal"
branch_labels = None
depends_on = None

TABLE = "venue_booking_status_history"


def upgrade():
    op.create_table(
        TABLE,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "booking_id",
            sa.Integer(),
            sa.ForeignKey("venue_bookings.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("action", sa.String(length=40), nullable=False),
        sa.Column("previous_status", sa.String(length=40)),
        sa.Column("resulting_status", sa.String(length=40), nullable=False),
        sa.Column(
            "actor_account_id",
            sa.Uuid(as_uuid=False),
            sa.ForeignKey("accounts.id"),
            nullable=False,
        ),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("note", sa.Text()),
    )
    op.create_index(f"ix_{TABLE}_booking_id", TABLE, ["booking_id"])
    # Backfill bookings made before this story from what SPL-77 and SPL-78 already stored.
    op.execute(
        f"""
        INSERT INTO {TABLE}
            (booking_id, action, previous_status, resulting_status, actor_account_id, changed_at)
        SELECT id, 'request', NULL, 'requested', requested_by_account_id, requested_at
        FROM venue_bookings
        WHERE requested_by_account_id IS NOT NULL AND requested_at IS NOT NULL
        """
    )
    op.execute(
        f"""
        INSERT INTO {TABLE}
            (booking_id, action, previous_status, resulting_status, actor_account_id, changed_at)
        SELECT id, 'withdraw', 'requested', 'withdrawn', withdrawn_by_account_id, withdrawn_at
        FROM venue_bookings
        WHERE withdrawn_by_account_id IS NOT NULL AND withdrawn_at IS NOT NULL
        """
    )
    op.execute(f"ALTER TABLE {TABLE} ENABLE ROW LEVEL SECURITY")
    op.execute(f"REVOKE ALL ON TABLE {TABLE} FROM PUBLIC")
    op.execute(f"REVOKE ALL ON SEQUENCE {TABLE}_id_seq FROM PUBLIC")
    op.execute(
        f"""
        DO $$
        DECLARE
            role_name text;
        BEGIN
            FOREACH role_name IN ARRAY ARRAY['anon', 'authenticated']
            LOOP
                IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = role_name) THEN
                    EXECUTE format('REVOKE ALL ON TABLE {TABLE} FROM %I', role_name);
                    EXECUTE format('REVOKE ALL ON SEQUENCE {TABLE}_id_seq FROM %I', role_name);
                END IF;
            END LOOP;
        END $$;
        """
    )


def downgrade():
    op.drop_table(TABLE)
