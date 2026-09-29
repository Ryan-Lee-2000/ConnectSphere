"""Record organiser responses to clarification requests (SPL-66).

Revision ID: s2_clarification_responses
Revises: s2_event_withdrawal
"""

import sqlalchemy as sa
from alembic import op

revision = "s2_clarification_responses"
down_revision = "s2_event_withdrawal"
branch_labels = None
depends_on = None

TABLE = "clarification_requests"
CONSTRAINT = "ck_clarification_requests_response_complete"
COMPLETE = (
    "(response is null and respondent_account_id is null and responded_at is null) or "
    "(response is not null and respondent_account_id is not null and responded_at is not null)"
)


def upgrade():
    with op.batch_alter_table(TABLE) as batch:
        batch.add_column(sa.Column("response", sa.Text(), nullable=True))
        batch.add_column(
            sa.Column(
                "respondent_account_id",
                sa.Uuid(as_uuid=False),
                sa.ForeignKey("accounts.id"),
                nullable=True,
            )
        )
        batch.add_column(sa.Column("responded_at", sa.DateTime(timezone=True), nullable=True))
        batch.create_check_constraint(CONSTRAINT, COMPLETE)


def downgrade():
    with op.batch_alter_table(TABLE) as batch:
        batch.drop_constraint(CONSTRAINT, type_="check")
        batch.drop_column("responded_at")
        batch.drop_column("respondent_account_id")
        batch.drop_column("response")
