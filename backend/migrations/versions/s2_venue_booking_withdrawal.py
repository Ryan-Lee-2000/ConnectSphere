"""Record who withdrew a venue-booking request, and when (SPL-78).

Revision ID: s2_venue_booking_withdrawal
Revises: s2_venue_booking_request
"""

import sqlalchemy as sa
from alembic import op

revision = "s2_venue_booking_withdrawal"
down_revision = "s2_venue_booking_request"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "venue_bookings",
        sa.Column("withdrawn_by_account_id", sa.Uuid(), sa.ForeignKey("accounts.id")),
    )
    op.add_column("venue_bookings", sa.Column("withdrawn_at", sa.DateTime(timezone=True)))


def downgrade():
    op.drop_column("venue_bookings", "withdrawn_at")
    op.drop_column("venue_bookings", "withdrawn_by_account_id")
