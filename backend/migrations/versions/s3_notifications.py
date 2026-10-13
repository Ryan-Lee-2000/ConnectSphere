"""Add the in-app notifications inbox (SPL-101).

Revision ID: s3_notifications
Revises: s3_equipment_releases
"""

import sqlalchemy as sa
from alembic import op

revision = "s3_notifications"
down_revision = "s3_equipment_releases"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "notifications",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "recipient_account_id",
            sa.Uuid(as_uuid=False),
            sa.ForeignKey("accounts.id"),
            nullable=False,
        ),
        sa.Column(
            "event_request_id",
            sa.Integer(),
            sa.ForeignKey("event_requests.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("dedupe_key", sa.String(length=120), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("recipient_account_id", "dedupe_key", name="uq_notifications_dedupe"),
    )
    op.create_index(
        "ix_notifications_recipient_account_id", "notifications", ["recipient_account_id"]
    )
    op.execute("ALTER TABLE notifications ENABLE ROW LEVEL SECURITY")
    op.execute("REVOKE ALL ON TABLE notifications FROM PUBLIC")
    op.execute("REVOKE ALL ON SEQUENCE notifications_id_seq FROM PUBLIC")
    op.execute(
        """
        DO $$
        DECLARE
            role_name text;
        BEGIN
            FOREACH role_name IN ARRAY ARRAY['anon', 'authenticated']
            LOOP
                IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = role_name) THEN
                    EXECUTE format('REVOKE ALL ON TABLE notifications FROM %I', role_name);
                    EXECUTE format(
                        'REVOKE ALL ON SEQUENCE notifications_id_seq FROM %I', role_name);
                END IF;
            END LOOP;
        END $$;
        """
    )


def downgrade():
    op.drop_table("notifications")
