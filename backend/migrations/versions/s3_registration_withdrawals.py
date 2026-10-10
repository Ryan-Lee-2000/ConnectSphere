"""Record when an attendee withdraws a registration (SPL-118).

Revision ID: s3_registration_withdrawals
Revises: s3_event_registrations (SPL-116, the newest migration on main when this was written)

One additive change to ``event_registrations``:

- ``withdrawn_at``: when the attendee withdrew (SPL-118 AC2). Nullable, so every existing
  registration keeps working unchanged and reads as "not withdrawn".
- ``ck_event_registrations_withdrawal_time``: the database itself refuses a Registered row that
  carries a withdrawal time. The constraint text is imported from app.models so the model and the
  database cannot drift apart.

No existing row is rewritten, so the previous application version keeps working while this deploys.
"""

import sqlalchemy as sa
from alembic import op
from app.models import REGISTERED_HAS_NO_WITHDRAWAL

revision = "s3_registration_withdrawals"
down_revision = "s3_event_registrations"
branch_labels = None
depends_on = None

TABLE = "event_registrations"
CONSTRAINT = "ck_event_registrations_withdrawal_time"


def upgrade():
    with op.batch_alter_table(TABLE) as batch:
        batch.add_column(sa.Column("withdrawn_at", sa.DateTime(timezone=True)))
        batch.create_check_constraint(CONSTRAINT, REGISTERED_HAS_NO_WITHDRAWAL)


def downgrade():
    # Reverse order: the constraint mentions the column, so it goes first.
    with op.batch_alter_table(TABLE) as batch:
        batch.drop_constraint(CONSTRAINT, type_="check")
        batch.drop_column("withdrawn_at")
