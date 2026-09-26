"""Record who approved an event request and when (SPL-67).

Revision ID: s2_event_approval
Revises: s2_clarification_requests

Approval moves the request to Planning. The decision-maker and time are kept on the request
itself so the responsible organiser can retrieve the outcome with a plain read; the append-only
``event_status_history`` row remains the audit evidence.
"""

import sqlalchemy as sa
from alembic import op

revision = "s2_event_approval"
down_revision = "s2_clarification_requests"
branch_labels = None
depends_on = None

TABLE = "event_requests"


def upgrade():
    with op.batch_alter_table(TABLE) as batch:
        batch.add_column(
            sa.Column(
                "approved_by_account_id",
                sa.Uuid(as_uuid=False),
                sa.ForeignKey("accounts.id"),
                nullable=True,
            )
        )
        batch.add_column(sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True))


def downgrade():
    with op.batch_alter_table(TABLE) as batch:
        batch.drop_column("approved_at")
        batch.drop_column("approved_by_account_id")
