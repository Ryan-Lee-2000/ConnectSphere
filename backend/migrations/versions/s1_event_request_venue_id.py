"""Replace the free-text preferred venue name with a real venue selection (CS-E03-S2).

Revision ID: s1_event_request_venue_id
Revises: s1_event_request_statuses

Organisers now pick a venue from the catalogue rather than typing a name, so the free-text
column is no longer read or written anywhere and is dropped. The new column is nullable and
has no foreign-key-driven backfill requirement: every event_requests row predates this story
and simply gains a null venue_id, matching "all venue requirement fields are optional".
"""

import sqlalchemy as sa
from alembic import op

revision = "s1_event_request_venue_id"
down_revision = "s1_event_request_statuses"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_column("event_requests", "preferred_venue_name")
    op.add_column(
        "event_requests",
        sa.Column(
            "venue_id",
            sa.Integer(),
            sa.ForeignKey("venues.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )


def downgrade():
    op.drop_column("event_requests", "venue_id")
    op.add_column(
        "event_requests",
        sa.Column("preferred_venue_name", sa.Text(), nullable=True),
    )
