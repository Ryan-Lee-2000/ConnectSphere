"""Record who rejected a venue-booking request, when, the reason, and any alternative (SPL-82).

Revision ID: s2_venue_booking_rejection
Revises: s2_venue_booking_approval
"""

import sqlalchemy as sa
from alembic import op

revision = "s2_venue_booking_rejection"
down_revision = "s2_venue_booking_approval"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "venue_bookings",
        sa.Column("rejected_by_account_id", sa.Uuid(), sa.ForeignKey("accounts.id")),
    )
    op.add_column("venue_bookings", sa.Column("rejected_at", sa.DateTime(timezone=True)))
    op.add_column("venue_bookings", sa.Column("rejection_reason", sa.Text()))
    op.add_column("venue_bookings", sa.Column("rejection_alternative_suggestion", sa.Text()))


def downgrade():
    op.drop_column("venue_bookings", "rejection_alternative_suggestion")
    op.drop_column("venue_bookings", "rejection_reason")
    op.drop_column("venue_bookings", "rejected_at")
    op.drop_column("venue_bookings", "rejected_by_account_id")
