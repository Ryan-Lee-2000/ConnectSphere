"""Mark bookings affected by operational unavailability (SPL-89).

Revision ID: s2_booking_review_marker
Revises: s2_venue_occupancy
"""

import sqlalchemy as sa
from alembic import op

revision = "s2_booking_review_marker"
down_revision = "s2_venue_occupancy"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "venue_bookings",
        sa.Column(
            "requires_review",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "venue_bookings",
        sa.Column(
            "review_trigger_block_id",
            sa.Integer(),
            sa.ForeignKey("venue_operational_blocks.id", ondelete="SET NULL"),
        ),
    )
    op.add_column(
        "venue_bookings",
        sa.Column("review_marked_at", sa.DateTime(timezone=True)),
    )
    op.add_column(
        "venue_bookings",
        sa.Column(
            "review_marked_by_account_id",
            sa.Uuid(),
            sa.ForeignKey("accounts.id"),
        ),
    )


def downgrade():
    op.drop_column("venue_bookings", "review_marked_by_account_id")
    op.drop_column("venue_bookings", "review_marked_at")
    op.drop_column("venue_bookings", "review_trigger_block_id")
    op.drop_column("venue_bookings", "requires_review")
