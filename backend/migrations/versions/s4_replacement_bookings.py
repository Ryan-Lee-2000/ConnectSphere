"""Link a replacement venue booking to the disrupted booking it replaces (SPL-132).

Revision ID: s4_replacement_bookings
Revises: s4_email_deliveries

* ``venue_bookings.replaces_booking_id``: the booking a replacement request replaces. Null for
  every ordinary booking, so existing rows need no backfill.
* A partial unique index keeps at most one Requested replacement per original, even if two
  requests race.

Additive for the running release: it never reads or writes the new column.
"""

import sqlalchemy as sa
from alembic import op

revision = "s4_replacement_bookings"
down_revision = "s4_email_deliveries"
branch_labels = None
depends_on = None

ONE_REQUESTED_REPLACEMENT = "status = 'requested' AND replaces_booking_id IS NOT NULL"


def upgrade():
    with op.batch_alter_table("venue_bookings") as batch:
        batch.add_column(sa.Column("replaces_booking_id", sa.Integer(), nullable=True))
        batch.create_foreign_key(
            "fk_venue_bookings_replaces_booking_id",
            "venue_bookings",
            ["replaces_booking_id"],
            ["id"],
            ondelete="SET NULL",
        )
    op.create_index(
        "uq_venue_bookings_one_requested_replacement",
        "venue_bookings",
        ["replaces_booking_id"],
        unique=True,
        postgresql_where=sa.text(ONE_REQUESTED_REPLACEMENT),
        sqlite_where=sa.text(ONE_REQUESTED_REPLACEMENT),
    )


def downgrade():
    op.drop_index("uq_venue_bookings_one_requested_replacement", table_name="venue_bookings")
    with op.batch_alter_table("venue_bookings") as batch:
        batch.drop_constraint("fk_venue_bookings_replaces_booking_id", type_="foreignkey")
        batch.drop_column("replaces_booking_id")
