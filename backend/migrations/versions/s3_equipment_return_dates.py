"""Record who last moved a reservation's planned return date, and when (SPL-100).

Revision ID: s3_equipment_return_dates
Revises: s3_equipment_review_notes (SPL-92, the newest migration on main after SPL-92 merged)

Originally written against ``s3_equipment_reservations``, alongside SPL-92's
``s3_equipment_review_notes`` and SPL-96's ``s3_equipment_unavailable_units``. SPL-92 merged
first, so this was re-pointed to follow it and keep a single head. If SPL-96 reaches main before
this does, re-point again at ``s3_equipment_unavailable_units``: test_postgres.py asserts one
head, and the PostgreSQL case reads its own parent from this file, so a re-point needs no test
change.

The three stories are kept on independent branches on purpose: none depends on another's code, so
chaining them only to tidy the migration graph would force an arbitrary merge order on the team.

Two additive, nullable columns on ``equipment_reservations``. The planned return date itself is
the existing ``commitment_end_date``, which SPL-97 already sets from the requirement's required
end date, so AC1's default needs no schema change at all — only proving.

Nullable rather than defaulted: a reservation nobody has edited must read as untouched, not as
edited by whoever created it. Every existing row therefore keeps working unchanged, and the
previous application version keeps working while this deploys.
"""

import sqlalchemy as sa
from alembic import op

revision = "s3_equipment_return_dates"
down_revision = "s3_equipment_review_notes"
branch_labels = None
depends_on = None

TABLE = "equipment_reservations"
COLUMNS = ("return_date_changed_by_account_id", "return_date_changed_at")


def upgrade():
    with op.batch_alter_table(TABLE) as batch:
        batch.add_column(
            sa.Column(
                "return_date_changed_by_account_id",
                sa.Uuid(as_uuid=False),
                sa.ForeignKey("accounts.id"),
                nullable=True,
            )
        )
        batch.add_column(
            sa.Column("return_date_changed_at", sa.DateTime(timezone=True), nullable=True)
        )


def downgrade():
    with op.batch_alter_table(TABLE) as batch:
        for column in COLUMNS:
            batch.drop_column(column)
