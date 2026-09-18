"""Allow name-only event request drafts while keeping submitted rows complete.

Revision ID: sprint1_event_request_drafts
Revises: sprint1_event_requests
"""

import sqlalchemy as sa
from alembic import op

revision = "sprint1_event_request_drafts"
down_revision = "sprint1_event_requests"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "event_requests",
        sa.Column(
            "last_saved_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.drop_constraint("ck_event_requests_known_status", "event_requests", type_="check")
    op.drop_constraint("ck_event_requests_time_order", "event_requests", type_="check")
    op.drop_constraint("ck_event_requests_positive_attendance", "event_requests", type_="check")
    for column, column_type in (
        ("purpose", sa.Text()),
        ("proposed_date", sa.Date()),
        ("start_time", sa.Time()),
        ("end_time", sa.Time()),
        ("expected_attendance", sa.Integer()),
    ):
        op.alter_column("event_requests", column, existing_type=column_type, nullable=True)
    op.create_check_constraint(
        "ck_event_requests_known_status",
        "event_requests",
        "status in ('draft', 'submitted')",
    )
    op.create_check_constraint(
        "ck_event_requests_submitted_fields",
        "event_requests",
        "status <> 'submitted' or (purpose is not null and proposed_date is not null "
        "and start_time is not null and end_time is not null "
        "and expected_attendance is not null and end_time > start_time "
        "and expected_attendance > 0)",
    )


def downgrade():
    op.execute(
        "DO $$ BEGIN IF EXISTS (SELECT 1 FROM event_requests WHERE status = 'draft') "
        "THEN RAISE EXCEPTION 'Cannot downgrade while event request drafts exist'; "
        "END IF; END $$"
    )
    op.drop_constraint("ck_event_requests_submitted_fields", "event_requests", type_="check")
    op.drop_constraint("ck_event_requests_known_status", "event_requests", type_="check")
    for column, column_type in (
        ("purpose", sa.Text()),
        ("proposed_date", sa.Date()),
        ("start_time", sa.Time()),
        ("end_time", sa.Time()),
        ("expected_attendance", sa.Integer()),
    ):
        op.alter_column("event_requests", column, existing_type=column_type, nullable=False)
    op.create_check_constraint(
        "ck_event_requests_known_status", "event_requests", "status in ('submitted')"
    )
    op.create_check_constraint(
        "ck_event_requests_time_order", "event_requests", "end_time > start_time"
    )
    op.create_check_constraint(
        "ck_event_requests_positive_attendance", "event_requests", "expected_attendance > 0"
    )
    op.drop_column("event_requests", "last_saved_at")
