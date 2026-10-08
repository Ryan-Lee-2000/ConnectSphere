"""Preserve exact booking evidence alongside untouched legacy claims."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "s3_exact_booking_snapshots"
down_revision = "s3_venue_exact_timing"
branch_labels = None
depends_on = None


def upgrade():
    for name in ("exact_timing", "reviewed_requirements"):
        op.add_column(
            "venue_bookings",
            sa.Column(name, sa.JSON().with_variant(JSONB(), "postgresql"), nullable=True),
        )
    # Existing venue_bookings RLS/grants continue to protect both new fields.


def downgrade():
    op.drop_column("venue_bookings", "reviewed_requirements")
    op.drop_column("venue_bookings", "exact_timing")
