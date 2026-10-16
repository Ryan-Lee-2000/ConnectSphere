"""Add ordinary event information and its audit history (SPL-108).

Revision ID: s3_ordinary_event_details
Revises: s3_event_cancellation

The four new nullable event fields preserve all existing rows. Every coordinator edit is recorded
in an append-only audit table; browser roles cannot access that table directly.
"""

import sqlalchemy as sa
from alembic import op

revision = "s3_ordinary_event_details"
down_revision = "s3_event_cancellation"
branch_labels = None
depends_on = None

EVENTS = "event_requests"
HISTORY = "event_detail_changes"


def upgrade():
    with op.batch_alter_table(EVENTS) as batch:
        batch.add_column(sa.Column("event_notes", sa.Text()))
        batch.add_column(sa.Column("event_contact_name", sa.Text()))
        batch.add_column(sa.Column("event_contact_email", sa.Text()))
        batch.add_column(sa.Column("event_contact_phone", sa.Text()))

    op.create_table(
        HISTORY,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "event_request_id",
            sa.Integer(),
            sa.ForeignKey("event_requests.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("changes", sa.JSON(), nullable=False),
        sa.Column(
            "changed_by_account_id",
            sa.Uuid(as_uuid=False),
            sa.ForeignKey("accounts.id"),
            nullable=False,
        ),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(f"ix_{HISTORY}_event_request_id", HISTORY, ["event_request_id"])

    op.execute(f"ALTER TABLE {HISTORY} ENABLE ROW LEVEL SECURITY")
    op.execute(f"REVOKE ALL ON TABLE {HISTORY} FROM PUBLIC")
    op.execute(f"REVOKE ALL ON SEQUENCE {HISTORY}_id_seq FROM PUBLIC")
    op.execute(
        f"""
        DO $$
        DECLARE role_name text;
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
    op.drop_table(HISTORY)
    with op.batch_alter_table(EVENTS) as batch:
        batch.drop_column("event_contact_phone")
        batch.drop_column("event_contact_email")
        batch.drop_column("event_contact_name")
        batch.drop_column("event_notes")
