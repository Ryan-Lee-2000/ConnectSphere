"""Record each venue booking's own required facilities (SPL-131, CS-E10 multiple venues).

Revision ID: s3_venue_arrangements
Revises: s3_event_confirmation

An event may now hold several venue bookings, each for one part of the event. A booking's
attendee count and layout already live on ``venue_bookings``; this adds the facilities that
part of the event needs. Null means the booking recorded none of its own, so the event's
required facilities apply - which is how every existing booking is read (AC9). No backfill:
existing rows are not rewritten with guessed values.

Purely additive on an already RLS-protected table: the previous application version ignores the
new column while this deploys.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "s3_venue_arrangements"
down_revision = "s3_event_confirmation"
branch_labels = None
depends_on = None

TABLE = "venue_bookings"


def upgrade():
    with op.batch_alter_table(TABLE) as batch:
        batch.add_column(
            sa.Column(
                "required_facilities",
                sa.JSON().with_variant(postgresql.JSONB(), "postgresql"),
                nullable=True,
            )
        )


def downgrade():
    with op.batch_alter_table(TABLE) as batch:
        batch.drop_column("required_facilities")
