"""Record event-request withdrawal evidence (SPL-69).

Revision ID: s2_event_withdrawal
Revises: s2_venue_booking_rejection
"""

import sqlalchemy as sa
from alembic import op

revision = "s2_event_withdrawal"
down_revision = "s2_venue_booking_rejection"
branch_labels = None
depends_on = None

TABLE = "event_requests"
CONSTRAINT = "ck_event_requests_withdrawal_complete"
COMPLETE = (
    "(withdrawn_by_account_id is null and withdrawn_at is null and withdrawal_note is null)"
    " or (withdrawn_by_account_id is not null and withdrawn_at is not null)"
)


def upgrade():
    with op.batch_alter_table(TABLE) as batch:
        batch.add_column(
            sa.Column(
                "withdrawn_by_account_id",
                sa.Uuid(as_uuid=False),
                sa.ForeignKey("accounts.id"),
                nullable=True,
            )
        )
        batch.add_column(sa.Column("withdrawn_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("withdrawal_note", sa.Text(), nullable=True))
        batch.create_check_constraint(CONSTRAINT, COMPLETE)


def downgrade():
    with op.batch_alter_table(TABLE) as batch:
        batch.drop_constraint(CONSTRAINT, type_="check")
        batch.drop_column("withdrawal_note")
        batch.drop_column("withdrawn_at")
        batch.drop_column("withdrawn_by_account_id")
