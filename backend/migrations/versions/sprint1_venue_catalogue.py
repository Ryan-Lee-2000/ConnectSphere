"""Add the Sprint 1 venue catalogue.

Revision ID: sprint1_venue_catalogue
Revises: s1_account_roles
"""

import sqlalchemy as sa
from alembic import op

revision = "sprint1_venue_catalogue"
down_revision = "s1_account_roles"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "venues",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("location", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("facilities", sa.JSON(), nullable=False),
        sa.Column("accessibility_features", sa.JSON(), nullable=False),
        sa.Column("operating_slots", sa.JSON(), nullable=False),
        sa.Column("setup_buffer_slots", sa.Integer(), nullable=False),
        sa.Column("turnaround_buffer_slots", sa.Integer(), nullable=False),
    )
    op.execute("ALTER TABLE venues ENABLE ROW LEVEL SECURITY")
    op.execute("REVOKE ALL ON TABLE venues FROM PUBLIC")
    op.execute("REVOKE ALL ON SEQUENCE venues_id_seq FROM PUBLIC")
    op.execute(
        """
        DO $$
        DECLARE
            role_name text;
        BEGIN
            FOREACH role_name IN ARRAY ARRAY['anon', 'authenticated']
            LOOP
                IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = role_name) THEN
                    EXECUTE format('REVOKE ALL ON TABLE venues FROM %I', role_name);
                    EXECUTE format('REVOKE ALL ON SEQUENCE venues_id_seq FROM %I', role_name);
                END IF;
            END LOOP;
        END $$;
        """
    )


def downgrade():
    op.drop_table("venues")
