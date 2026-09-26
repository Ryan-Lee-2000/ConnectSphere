"""Add the shared venue-booking occupancy model for SPL-83.

Revision ID: s2_venue_occupancy
Revises: s2_venue_blocks
"""

import sqlalchemy as sa
from alembic import op

revision = "s2_venue_occupancy"
down_revision = "s2_venue_blocks"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "venue_bookings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "event_request_id",
            sa.Integer(),
            sa.ForeignKey("event_requests.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "venue_id",
            sa.Integer(),
            sa.ForeignKey("venues.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.CheckConstraint(
            "status in ('requested', 'approved', 'rejected', 'withdrawn', 'cancelled')",
            name="ck_venue_bookings_known_status",
        ),
    )
    op.create_index("ix_venue_bookings_event_request_id", "venue_bookings", ["event_request_id"])
    op.create_index("ix_venue_bookings_venue_id", "venue_bookings", ["venue_id"])
    op.create_table(
        "venue_booking_occupancy",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "booking_id",
            sa.Integer(),
            sa.ForeignKey("venue_bookings.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "venue_id",
            sa.Integer(),
            sa.ForeignKey("venues.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("occupancy_date", sa.Date(), nullable=False),
        sa.Column("slot", sa.String(length=10), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.CheckConstraint(
            "slot in ('AM', 'PM', 'NIGHT')",
            name="ck_venue_booking_occupancy_known_slot",
        ),
        sa.CheckConstraint(
            "kind in ('event', 'setup', 'turnaround')",
            name="ck_venue_booking_occupancy_known_kind",
        ),
        sa.UniqueConstraint(
            "venue_id",
            "occupancy_date",
            "slot",
            name="uq_venue_booking_occupancy_venue_date_slot",
        ),
    )
    op.create_index(
        "ix_venue_booking_occupancy_booking_id",
        "venue_booking_occupancy",
        ["booking_id"],
    )
    for table in ("venue_bookings", "venue_booking_occupancy"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"REVOKE ALL ON TABLE {table} FROM PUBLIC")
        op.execute(f"REVOKE ALL ON SEQUENCE {table}_id_seq FROM PUBLIC")
        op.execute(
            f"""
            DO $$
            DECLARE
                role_name text;
            BEGIN
                FOREACH role_name IN ARRAY ARRAY['anon', 'authenticated']
                LOOP
                    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = role_name) THEN
                        EXECUTE format('REVOKE ALL ON TABLE {table} FROM %I', role_name);
                        EXECUTE format(
                            'REVOKE ALL ON SEQUENCE {table}_id_seq FROM %I', role_name);
                    END IF;
                END LOOP;
            END $$;
            """
        )


def downgrade():
    op.drop_table("venue_booking_occupancy")
    op.drop_table("venue_bookings")
