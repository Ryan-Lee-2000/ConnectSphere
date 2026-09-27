"""Record the submitted venue-booking request on its booking (SPL-77).

Revision ID: s2_venue_booking_request
Revises: s2_event_rejection
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "s2_venue_booking_request"
down_revision = "s2_event_rejection"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("venue_bookings", sa.Column("layout", sa.Text()))
    op.add_column("venue_bookings", sa.Column("expected_attendance", sa.Integer()))
    op.add_column("venue_bookings", sa.Column("booking_date", sa.Date()))
    # jsonb, not json: SPL-89 selects DISTINCT bookings and json has no equality operator.
    op.add_column(
        "venue_bookings",
        sa.Column("event_slots", sa.JSON().with_variant(postgresql.JSONB(), "postgresql")),
    )
    op.add_column("venue_bookings", sa.Column("setup_date", sa.Date()))
    op.add_column("venue_bookings", sa.Column("setup_slot", sa.String(length=10)))
    op.add_column("venue_bookings", sa.Column("turnaround_date", sa.Date()))
    op.add_column("venue_bookings", sa.Column("turnaround_slot", sa.String(length=10)))
    op.add_column(
        "venue_bookings",
        sa.Column("requested_by_account_id", sa.Uuid(), sa.ForeignKey("accounts.id")),
    )
    op.add_column("venue_bookings", sa.Column("requested_at", sa.DateTime(timezone=True)))


def downgrade():
    for column in (
        "requested_at",
        "requested_by_account_id",
        "turnaround_slot",
        "turnaround_date",
        "setup_slot",
        "setup_date",
        "event_slots",
        "booking_date",
        "expected_attendance",
        "layout",
    ):
        op.drop_column("venue_bookings", column)
