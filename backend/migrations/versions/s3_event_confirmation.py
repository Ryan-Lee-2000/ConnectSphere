"""Record who confirmed an event and when (SPL-85, CS-E07-S3).

Revision ID: s3_event_confirmation
Revises: s3_booking_review_findings

Two nullable columns on ``event_requests``, filled together when the assigned coordinator confirms
the event, and a check constraint so one is never stored without the other. The predicate is
imported from app.models so the model and database cannot drift.

Purely additive: existing rows keep null values, and the previous application version keeps working
while this deploys.
"""

import sqlalchemy as sa
from alembic import op
from app.models import CONFIRMATION_COMPLETE

revision = "s3_event_confirmation"
down_revision = "s3_booking_review_findings"
branch_labels = None
depends_on = None

TABLE = "event_requests"
CONSTRAINT = "ck_event_requests_confirmation_complete"


def upgrade():
    with op.batch_alter_table(TABLE) as batch:
        batch.add_column(
            sa.Column(
                "confirmed_by_account_id",
                sa.Uuid(as_uuid=False),
                sa.ForeignKey("accounts.id"),
                nullable=True,
            )
        )
        batch.add_column(sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True))
        batch.create_check_constraint(CONSTRAINT, CONFIRMATION_COMPLETE)


def downgrade():
    with op.batch_alter_table(TABLE) as batch:
        batch.drop_constraint(CONSTRAINT, type_="check")
        batch.drop_column("confirmed_at")
        batch.drop_column("confirmed_by_account_id")
