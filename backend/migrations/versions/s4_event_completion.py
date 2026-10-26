"""Record who completed an event, when, and the optional closing note (SPL-105).

Revision ID: s4_event_completion
Revises: s4_safety_reviews

Three nullable columns on ``event_requests``, filled when the assigned coordinator marks the
event completed, and a check constraint so the actor and time are always stored together and the
note never without them. The predicate is imported from app.models so the model and database
cannot drift.

Purely additive: existing rows keep null values, and the previous application version keeps working
while this deploys.
"""

import sqlalchemy as sa
from alembic import op
from app.models import COMPLETION_RECORDED

revision = "s4_event_completion"
down_revision = "s4_safety_reviews"
branch_labels = None
depends_on = None

TABLE = "event_requests"
CONSTRAINT = "ck_event_requests_completion_recorded"


def upgrade():
    with op.batch_alter_table(TABLE) as batch:
        batch.add_column(
            sa.Column(
                "completed_by_account_id",
                sa.Uuid(as_uuid=False),
                sa.ForeignKey("accounts.id"),
                nullable=True,
            )
        )
        batch.add_column(sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("completion_note", sa.Text(), nullable=True))
        batch.create_check_constraint(CONSTRAINT, COMPLETION_RECORDED)


def downgrade():
    with op.batch_alter_table(TABLE) as batch:
        batch.drop_constraint(CONSTRAINT, type_="check")
        batch.drop_column("completion_note")
        batch.drop_column("completed_at")
        batch.drop_column("completed_by_account_id")
