"""Widen the event request status vocabulary and record when it last changed (CS-E07-S1).

Revision ID: s1_event_request_statuses
Revises: s1_event_request_submitted_at

Two changes, both additive in effect:

* ``ck_event_requests_known_status`` is replaced so a request may hold any value in the agreed
  vocabulary rather than only ``submitted``. Every value previously stored remains legal, so no
  existing row is invalidated and no backfill is needed.
* ``status_changed_at`` is added, nullable. Nothing in this story writes it; the organiser is
  shown the submission time until something moves a status on (CS-E06, CS-E07-S3 to S5).

The constraint text is generated from ``app.event_statuses`` so this migration and the model
cannot disagree about which values the database accepts.
"""

import sqlalchemy as sa
from alembic import op
from app.event_statuses import status_check_constraint

revision = "s1_event_request_statuses"
down_revision = "s1_event_request_submitted_at"
branch_labels = None
depends_on = None

CONSTRAINT = "ck_event_requests_known_status"
TABLE = "event_requests"


def upgrade():
    op.add_column(
        TABLE,
        sa.Column("status_changed_at", sa.DateTime(timezone=True), nullable=True),
    )
    with op.batch_alter_table(TABLE) as batch:
        batch.drop_constraint(CONSTRAINT, type_="check")
        batch.create_check_constraint(CONSTRAINT, status_check_constraint())


def downgrade():
    # Narrowing the vocabulary would orphan any request that has moved past submission, so
    # refuse rather than silently break the check constraint the recreated one implies.
    connection = op.get_bind()
    beyond_submission = connection.execute(
        sa.text(f"select count(*) from {TABLE} where status <> 'submitted'")
    ).scalar_one()
    if beyond_submission:
        raise RuntimeError(
            f"{beyond_submission} event request(s) hold a status outside the original "
            "vocabulary. Resolve them before downgrading."
        )

    with op.batch_alter_table(TABLE) as batch:
        batch.drop_constraint(CONSTRAINT, type_="check")
        batch.create_check_constraint(CONSTRAINT, "status in ('submitted')")
    op.drop_column(TABLE, "status_changed_at")
