"""Extend existing booking review reasons for SPL-106."""

import sqlalchemy as sa
from alembic import op

revision = "s4_booking_requirement_review"
down_revision = "s3_ordinary_event_details"
branch_labels = None
depends_on = None

TABLE = "venue_booking_review_findings"
CONSTRAINT = "ck_venue_booking_review_findings_known_reason"
OLD_REASONS = (
    "overlap",
    "operational_block",
    "outside_operating_hours",
    "unresolved_historical_timing",
)
NEW_REASONS = (
    "layout_capacity",
    "facilities",
    "accessibility",
    "location",
    "attendance",
    "event_times",
)


def _replace_constraint(reasons):
    with op.batch_alter_table(TABLE) as batch:
        batch.drop_constraint(CONSTRAINT, type_="check")
        batch.create_check_constraint(
            CONSTRAINT, "reason_type in (" + ", ".join(repr(reason) for reason in reasons) + ")"
        )


def upgrade():
    _replace_constraint(OLD_REASONS + NEW_REASONS)


def downgrade():
    found = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT 1 FROM venue_booking_review_findings WHERE reason_type IN "
                "('layout_capacity', 'facilities', 'accessibility', 'location', "
                "'attendance', 'event_times') LIMIT 1"
            )
        )
        .first()
    )
    if found:
        raise RuntimeError(
            "Cannot downgrade while requirement review history exists; retain its audit records."
        )
    _replace_constraint(OLD_REASONS)
