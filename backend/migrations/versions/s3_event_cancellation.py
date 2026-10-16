"""Record who cancelled an event, when and why (SPL-86, CS-E07-S5).

Revision ID: s3_event_cancellation
Revises: s3_venue_arrangements

Three nullable columns on ``event_requests``, filled together when the assigned coordinator
cancels the event, and a check constraint so none is ever stored without the others. The
predicate is imported from app.models so the model and database cannot drift.

Purely additive: existing rows keep null values, and the previous application version keeps working
while this deploys.
"""

import sqlalchemy as sa
from alembic import op
from app.models import CANCELLATION_COMPLETE

revision = "s3_event_cancellation"
down_revision = "s3_venue_arrangements"
branch_labels = None
depends_on = None

TABLE = "event_requests"
CONSTRAINT = "ck_event_requests_cancellation_complete"


def upgrade():
    with op.batch_alter_table(TABLE) as batch:
        batch.add_column(
            sa.Column(
                "cancelled_by_account_id",
                sa.Uuid(as_uuid=False),
                sa.ForeignKey("accounts.id"),
                nullable=True,
            )
        )
        batch.add_column(sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("cancellation_reason", sa.Text(), nullable=True))
        batch.create_check_constraint(CONSTRAINT, CANCELLATION_COMPLETE)


def downgrade():
    with op.batch_alter_table(TABLE) as batch:
        batch.drop_constraint(CONSTRAINT, type_="check")
        batch.drop_column("cancellation_reason")
        batch.drop_column("cancelled_at")
        batch.drop_column("cancelled_by_account_id")
