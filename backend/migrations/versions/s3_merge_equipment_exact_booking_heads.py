"""Merge the SPL-94 equipment and SPL-137 exact-booking migration heads.

Revision ID: s3_merge_equip_exact
Revises: s3_equipment_catalogue, s3_exact_booking_snapshots
Create Date: 2026-10-09
"""

# revision identifiers, used by Alembic.
revision = "s3_merge_equip_exact"
down_revision = ("s3_equipment_catalogue", "s3_exact_booking_snapshots")
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Join independent schema branches; both parents apply their own changes."""


def downgrade() -> None:
    """A merge revision has no schema changes to reverse."""
