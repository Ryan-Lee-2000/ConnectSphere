"""Allow incomplete event request drafts after the shared status migrations.

Revision ID: sprint1_event_request_drafts
Revises: s1_event_request_statuses
"""

import sqlalchemy as sa
from alembic import op

revision = "sprint1_event_request_drafts"
down_revision = "s1_event_request_statuses"
branch_labels = None
depends_on = None

DRAFTABLE_COLUMNS = (
    ("purpose", sa.Text()),
    ("proposed_date", sa.Date()),
    ("start_time", sa.Time()),
    ("end_time", sa.Time()),
    ("expected_attendance", sa.Integer()),
)


def upgrade():
    op.add_column(
        "event_requests",
        sa.Column(
            "last_saved_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )

    for column, column_type in DRAFTABLE_COLUMNS:
        op.alter_column(
            "event_requests",
            column,
            existing_type=column_type,
            nullable=True,
        )

    op.create_check_constraint(
        "ck_event_requests_submitted_fields",
        "event_requests",
        "status <> 'submitted' or (purpose is not null "
        "and proposed_date is not null "
        "and start_time is not null "
        "and end_time is not null "
        "and expected_attendance is not null)",
    )


def downgrade():
    op.execute(
        "DO $$ BEGIN "
        "IF EXISTS (SELECT 1 FROM event_requests WHERE status = 'draft') "
        "THEN RAISE EXCEPTION "
        "'Cannot downgrade while event request drafts exist'; "
        "END IF; "
        "END $$"
    )

    op.drop_constraint(
        "ck_event_requests_submitted_fields",
        "event_requests",
        type_="check",
    )

    for column, column_type in DRAFTABLE_COLUMNS:
        op.alter_column(
            "event_requests",
            column,
            existing_type=column_type,
            nullable=False,
        )

    op.drop_column("event_requests", "last_saved_at")
