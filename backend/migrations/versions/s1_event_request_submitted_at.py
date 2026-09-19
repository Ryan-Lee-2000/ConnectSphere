"""Record when an event request was submitted (CS-E03-S5).

Revision ID: s1_event_request_submitted_at
Revises: sprint1_event_requests

Additive only. The column is nullable so requests stored by CS-E03-S1 before this story
remain readable without a backfill, and so the merged revision is never rewritten.
"""

import sqlalchemy as sa
from alembic import op

revision = "s1_event_request_submitted_at"
down_revision = "sprint1_event_requests"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "event_requests",
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade():
    op.drop_column("event_requests", "submitted_at")
