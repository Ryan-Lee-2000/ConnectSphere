"""Record who approved a venue-booking request, when, and the optional note (SPL-81).

Revision ID: s2_venue_booking_approval
Revises: s2_venue_booking_history
"""

import sqlalchemy as sa
from alembic import op

revision = "s2_venue_booking_approval"
down_revision = "s2_venue_booking_history"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "venue_bookings",
        sa.Column("approved_by_account_id", sa.Uuid(), sa.ForeignKey("accounts.id")),
    )
    op.add_column("venue_bookings", sa.Column("approved_at", sa.DateTime(timezone=True)))
    op.add_column("venue_bookings", sa.Column("approval_note", sa.Text()))


def downgrade():
    op.drop_column("venue_bookings", "approval_note")
    op.drop_column("venue_bookings", "approved_at")
    op.drop_column("venue_bookings", "approved_by_account_id")
