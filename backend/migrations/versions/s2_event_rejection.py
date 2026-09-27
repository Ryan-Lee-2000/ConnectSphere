"""Record who rejected an event request, when and why (SPL-68).

Revision ID: s2_event_rejection
Revises: s2_event_approval

Rejection is final. The decision-maker, time and reason are kept on the request itself so the
responsible organiser can retrieve the outcome with a plain read; the append-only
``event_status_history`` row remains the audit evidence. The check constraint keeps the three
columns all set or all null.
"""

import sqlalchemy as sa
from alembic import op

revision = "s2_event_rejection"
down_revision = "s2_event_approval"
branch_labels = None
depends_on = None

TABLE = "event_requests"
CONSTRAINT = "ck_event_requests_rejection_complete"
COMPLETE = (
    "(rejected_by_account_id is null and rejected_at is null and rejection_reason is null)"
    " or (rejected_by_account_id is not null and rejected_at is not null"
    " and rejection_reason is not null)"
)


def upgrade():
    with op.batch_alter_table(TABLE) as batch:
        batch.add_column(
            sa.Column(
                "rejected_by_account_id",
                sa.Uuid(as_uuid=False),
                sa.ForeignKey("accounts.id"),
                nullable=True,
            )
        )
        batch.add_column(sa.Column("rejected_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("rejection_reason", sa.Text(), nullable=True))
        batch.create_check_constraint(CONSTRAINT, COMPLETE)


def downgrade():
    with op.batch_alter_table(TABLE) as batch:
        batch.drop_constraint(CONSTRAINT, type_="check")
        batch.drop_column("rejection_reason")
        batch.drop_column("rejected_at")
        batch.drop_column("rejected_by_account_id")
