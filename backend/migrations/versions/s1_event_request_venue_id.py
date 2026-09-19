"""Replace the free-text preferred venue name with a real venue selection (CS-E03-S2).

Revision ID: s1_event_request_venue_id
Revises: sprint1_event_request_drafts

Organisers now pick a venue from the catalogue rather than typing a name, so the free-text
column is no longer read or written anywhere and is dropped. The new column is nullable and
has no foreign-key-driven backfill requirement: every event_requests row predates this story
and simply gains a null venue_id, matching "all venue requirement fields are optional".

Chained after sprint1_event_request_drafts (the merged save-draft migration) rather than
directly after s1_event_request_statuses, since both were independently written against
that same parent and only one can hold that slot; this one is still local/unmerged, so it
is the side that moves.
"""

import sqlalchemy as sa
from alembic import op

revision = "s1_event_request_venue_id"
down_revision = "sprint1_event_request_drafts"
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
