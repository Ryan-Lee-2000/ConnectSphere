"""Add organiser event requests and equipment requirement lines.

Revision ID: sprint1_event_requests
Revises: sprint1_venue_layouts
"""

import sqlalchemy as sa
from alembic import op

revision = "sprint1_event_requests"
down_revision = "sprint1_venue_layouts"
branch_labels = None
depends_on = None


def _secure_table(table_name: str, sequence_name: str) -> None:
    op.execute(f"ALTER TABLE {table_name} ENABLE ROW LEVEL SECURITY")
    op.execute(f"REVOKE ALL ON TABLE {table_name} FROM PUBLIC")
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
                    EXECUTE format('REVOKE ALL ON SEQUENCE {sequence_name} FROM %I', role_name);
                END IF;
            END LOOP;
        END $$;
        """
    )


def upgrade():
    op.create_table(
        "event_requests",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "organiser_account_id",
            sa.Uuid(as_uuid=False),
            sa.ForeignKey("accounts.id"),
            nullable=False,
        ),
        sa.Column("organisation_id", sa.Integer(), nullable=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("purpose", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("proposed_date", sa.Date(), nullable=False),
        sa.Column("start_time", sa.Time(), nullable=False),
        sa.Column("end_time", sa.Time(), nullable=False),
        sa.Column("expected_attendance", sa.Integer(), nullable=False),
        sa.Column(
            "status", sa.String(length=40), nullable=False, server_default=sa.text("'submitted'")
        ),
        sa.Column("preferred_room_layout", sa.Text(), nullable=True),
        sa.Column(
            "required_facilities",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'::json"),
        ),
        sa.Column("facilities_notes", sa.Text(), nullable=True),
        sa.Column("accessibility_needs", sa.Text(), nullable=True),
        sa.Column("location_preference", sa.Text(), nullable=True),
        sa.Column("venue_notes", sa.Text(), nullable=True),
        sa.Column("preferred_venue_name", sa.Text(), nullable=True),
        sa.Column("registration_required", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("registration_notes", sa.Text(), nullable=True),
        sa.CheckConstraint("end_time > start_time", name="ck_event_requests_time_order"),
        sa.CheckConstraint("expected_attendance > 0", name="ck_event_requests_positive_attendance"),
        sa.CheckConstraint("status in ('submitted')", name="ck_event_requests_known_status"),
    )
    op.create_table(
        "equipment_requirements",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "event_request_id",
            sa.Integer(),
            sa.ForeignKey("event_requests.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("equipment_type", sa.Text(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.CheckConstraint("quantity > 0", name="ck_equipment_requirements_positive_quantity"),
    )
    _secure_table("event_requests", "event_requests_id_seq")
    _secure_table("equipment_requirements", "equipment_requirements_id_seq")


def downgrade():
    op.drop_table("equipment_requirements")
    op.drop_table("event_requests")
