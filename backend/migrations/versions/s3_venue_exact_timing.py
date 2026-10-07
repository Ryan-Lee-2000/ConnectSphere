"""Add nullable, explicitly confirmed venue timing without rewriting legacy evidence."""

import sqlalchemy as sa
from alembic import op

revision = "s3_venue_exact_timing"
down_revision = "s2_clarification_responses"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("venues", sa.Column("setup_minutes", sa.Integer(), nullable=True))
    op.add_column("venues", sa.Column("turnaround_minutes", sa.Integer(), nullable=True))
    op.add_column("venues", sa.Column("operating_intervals", sa.JSON(), nullable=True))
    op.add_column(
        "venues", sa.Column("timing_revision", sa.Integer(), nullable=False, server_default="0")
    )
    # Existing table RLS and grants remain intact. No guessed backfill or changed booking claims.


def downgrade():
    for name in ("timing_revision", "operating_intervals", "turnaround_minutes", "setup_minutes"):
        op.drop_column("venues", name)
