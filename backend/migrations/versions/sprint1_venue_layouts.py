"""Add supported room layouts and stated venue capacities.

Revision ID: sprint1_venue_layouts
Revises: sprint1_venue_catalogue
"""

import sqlalchemy as sa
from alembic import op

revision = "sprint1_venue_layouts"
down_revision = "sprint1_venue_catalogue"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "venue_layouts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "venue_id",
            sa.Integer(),
            sa.ForeignKey("venues.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("layout", sa.Text(), nullable=False),
        sa.Column("capacity", sa.Integer(), nullable=False),
        sa.UniqueConstraint("venue_id", "layout", name="uq_venue_layouts_venue_layout"),
    )
    op.execute("ALTER TABLE venue_layouts ENABLE ROW LEVEL SECURITY")
    op.execute("REVOKE ALL ON TABLE venue_layouts FROM PUBLIC")
    op.execute("REVOKE ALL ON SEQUENCE venue_layouts_id_seq FROM PUBLIC")
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
                        'REVOKE ALL ON TABLE venue_layouts FROM %I', role_name
                    );
                    EXECUTE format(
                        'REVOKE ALL ON SEQUENCE venue_layouts_id_seq FROM %I', role_name);
                END IF;
            END LOOP;
        END $$;
        """
    )


def downgrade():
    op.drop_table("venue_layouts")
