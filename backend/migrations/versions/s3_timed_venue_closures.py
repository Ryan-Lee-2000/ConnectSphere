"""Add precise closure intervals without rewriting legacy evidence."""

import sqlalchemy as sa
from alembic import op

revision = "s3_timed_venue_closures"
down_revision = "s3_equipment_catalogue"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("venue_operational_blocks", sa.Column("exact_start", sa.DateTime(timezone=True)))
    op.add_column("venue_operational_blocks", sa.Column("exact_end", sa.DateTime(timezone=True)))
    op.create_check_constraint(
        "ck_venue_blocks_exact_order",
        "venue_operational_blocks",
        "(exact_start is null and exact_end is null) or "
        "(exact_start is not null and exact_end is not null and exact_end > exact_start)",
    )


def downgrade():
    op.drop_constraint("ck_venue_blocks_exact_order", "venue_operational_blocks", type_="check")
    op.drop_column("venue_operational_blocks", "exact_end")
    op.drop_column("venue_operational_blocks", "exact_start")
