"""Record Event Coordinator assignments and their history (SPL-59 to SPL-61).

Revision ID: s1_coordinator_assignment
Revises: s1_event_request_statuses

The status vocabulary this story relies on is already widened by CS-E07-S1, so nothing here
touches `ck_event_requests_known_status`.
"""

import sqlalchemy as sa
from alembic import op

revision = "s1_coordinator_assignment"
down_revision = "s1_event_request_statuses"
branch_labels = None
depends_on = None


def _secure_table(table_name: str, sequence_name: str | None = None) -> None:
    op.execute(f"ALTER TABLE {table_name} ENABLE ROW LEVEL SECURITY")
    op.execute(f"REVOKE ALL ON TABLE {table_name} FROM PUBLIC")
    if sequence_name:
        op.execute(f"REVOKE ALL ON SEQUENCE {sequence_name} FROM PUBLIC")
    op.execute(
        f"""
        DO $$
        DECLARE
            role_name text;
        BEGIN
            FOREACH role_name IN ARRAY ARRAY['anon', 'authenticated']
            LOOP
                IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = role_name) THEN
                    EXECUTE format('REVOKE ALL ON TABLE {table_name} FROM %I', role_name);
                END IF;
            END LOOP;
        END $$;
        """
    )
    if sequence_name:
        op.execute(
            f"""
            DO $$
            DECLARE
                role_name text;
            BEGIN
                FOREACH role_name IN ARRAY ARRAY['anon', 'authenticated']
                LOOP
                    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = role_name) THEN
                        EXECUTE format(
                            'REVOKE ALL ON SEQUENCE {sequence_name} FROM %I', role_name);
                    END IF;
                END LOOP;
            END $$;
            """
        )


def upgrade():
    op.add_column("accounts", sa.Column("display_name", sa.Text(), nullable=True))
    op.add_column(
        "accounts",
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.create_table(
        "event_coordinator_assignments",
        sa.Column(
            "event_request_id",
            sa.Integer(),
            sa.ForeignKey("event_requests.id", ondelete="CASCADE"),
            primary_key=True,
            autoincrement=False,
        ),
        sa.Column(
            "coordinator_account_id",
            sa.Uuid(as_uuid=False),
            sa.ForeignKey("accounts.id"),
            nullable=False,
        ),
        sa.Column(
            "assigned_by_account_id",
            sa.Uuid(as_uuid=False),
            sa.ForeignKey("accounts.id"),
            nullable=False,
        ),
        sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "event_coordinator_history",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "event_request_id",
            sa.Integer(),
            sa.ForeignKey("event_requests.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "previous_coordinator_account_id",
            sa.Uuid(as_uuid=False),
            sa.ForeignKey("accounts.id"),
            nullable=True,
        ),
        sa.Column(
            "new_coordinator_account_id",
            sa.Uuid(as_uuid=False),
            sa.ForeignKey("accounts.id"),
            nullable=False,
        ),
        sa.Column(
            "changed_by_account_id",
            sa.Uuid(as_uuid=False),
            sa.ForeignKey("accounts.id"),
            nullable=False,
        ),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_event_coordinator_history_event_request_id",
        "event_coordinator_history",
        ["event_request_id"],
    )
    _secure_table("event_coordinator_assignments")
    _secure_table("event_coordinator_history", "event_coordinator_history_id_seq")


def downgrade():
    op.drop_table("event_coordinator_history")
    op.drop_table("event_coordinator_assignments")
    op.drop_column("accounts", "is_active")
    op.drop_column("accounts", "display_name")
