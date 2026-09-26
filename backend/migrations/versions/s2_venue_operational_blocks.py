"""Record venue operational unavailability (SPL-89).

Revision ID: s2_venue_blocks
Revises: s2_event_status_history
"""

import sqlalchemy as sa
from alembic import op

revision = "s2_venue_blocks"
down_revision = "s2_event_status_history"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "venue_operational_blocks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "venue_id",
            sa.Integer(),
            sa.ForeignKey("venues.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("slots", sa.JSON(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column(
            "created_by_account_id",
            sa.Uuid(as_uuid=False),
            sa.ForeignKey("accounts.id"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "removed_by_account_id",
            sa.Uuid(as_uuid=False),
            sa.ForeignKey("accounts.id"),
        ),
        sa.Column("removed_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("end_date >= start_date", name="ck_venue_blocks_date_order"),
    )
    op.create_index(
        "ix_venue_operational_blocks_venue_id",
        "venue_operational_blocks",
        ["venue_id"],
    )
    op.create_index(
        "ix_venue_operational_blocks_availability",
        "venue_operational_blocks",
        ["venue_id", "start_date", "end_date", "removed_at"],
    )
    op.execute("ALTER TABLE venue_operational_blocks ENABLE ROW LEVEL SECURITY")
    op.execute("REVOKE ALL ON TABLE venue_operational_blocks FROM PUBLIC")
    op.execute("REVOKE ALL ON SEQUENCE venue_operational_blocks_id_seq FROM PUBLIC")
    op.execute(
        """
        DO $$
        DECLARE
            role_name text;
        BEGIN
            FOREACH role_name IN ARRAY ARRAY['anon', 'authenticated']
            LOOP
                IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = role_name) THEN
                    EXECUTE format(
                        'REVOKE ALL ON TABLE venue_operational_blocks FROM %I', role_name);
                    EXECUTE format(
                        'REVOKE ALL ON SEQUENCE venue_operational_blocks_id_seq FROM %I',
                        role_name);
                END IF;
            END LOOP;
        END $$;
        """
    )


def downgrade():
    op.drop_table("venue_operational_blocks")
