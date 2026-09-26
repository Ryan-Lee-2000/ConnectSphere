"""Record server-authorised event status transitions (SPL-70).

Revision ID: s2_event_status_history
Revises: s1_event_request_venue_id
"""

import sqlalchemy as sa
from alembic import op

revision = "s2_event_status_history"
down_revision = "s1_event_request_venue_id"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "event_status_history",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "event_request_id",
            sa.Integer(),
            sa.ForeignKey("event_requests.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("action", sa.String(length=80), nullable=False),
        sa.Column("previous_status", sa.String(length=40), nullable=False),
        sa.Column("resulting_status", sa.String(length=40), nullable=False),
        sa.Column(
            "actor_account_id",
            sa.Uuid(as_uuid=False),
            sa.ForeignKey("accounts.id"),
            nullable=False,
        ),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_event_status_history_event_request_id",
        "event_status_history",
        ["event_request_id"],
    )
    op.execute("ALTER TABLE event_status_history ENABLE ROW LEVEL SECURITY")
    op.execute("REVOKE ALL ON TABLE event_status_history FROM PUBLIC")
    op.execute("REVOKE ALL ON SEQUENCE event_status_history_id_seq FROM PUBLIC")
    op.execute(
        """
        DO $$
        DECLARE
            role_name text;
        BEGIN
            FOREACH role_name IN ARRAY ARRAY['anon', 'authenticated']
            LOOP
                IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = role_name) THEN
                    EXECUTE format('REVOKE ALL ON TABLE event_status_history FROM %I', role_name);
                    EXECUTE format(
                        'REVOKE ALL ON SEQUENCE event_status_history_id_seq FROM %I', role_name);
                END IF;
            END LOOP;
        END $$;
        """
    )


def downgrade():
    op.drop_table("event_status_history")
