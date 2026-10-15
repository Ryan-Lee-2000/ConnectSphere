"""Persist multiple venue-booking timing review findings (SPL-130)."""

from datetime import datetime, timezone

import sqlalchemy as sa
from alembic import op

revision = "s3_booking_review_findings"
down_revision = "s3_requirement_unavailability"
branch_labels = None
depends_on = None

TABLE = "venue_booking_review_findings"


def upgrade():
    op.create_table(
        TABLE,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("booking_id", sa.Integer(), nullable=False),
        sa.Column("finding_key", sa.String(length=120), nullable=False),
        sa.Column("reason_type", sa.String(length=40), nullable=False),
        sa.Column("detail", sa.Text(), nullable=False),
        sa.Column("original_occupancy", sa.JSON()),
        sa.Column("current_occupancy", sa.JSON()),
        sa.Column("venue_timing_revision", sa.Integer(), nullable=False),
        sa.Column("first_assessed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_assessed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        sa.Column("resolved_by_account_id", sa.Uuid(as_uuid=False)),
        sa.ForeignKeyConstraint(["booking_id"], ["venue_bookings.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["resolved_by_account_id"], ["accounts.id"]),
        sa.CheckConstraint(
            "reason_type in ('overlap', 'operational_block', 'outside_operating_hours', "
            "'unresolved_historical_timing')",
            name="ck_venue_booking_review_findings_known_reason",
        ),
        sa.UniqueConstraint(
            "booking_id", "finding_key", name="uq_venue_booking_review_findings_key"
        ),
    )
    op.create_index("ix_venue_booking_review_findings_active", TABLE, ["booking_id", "resolved_at"])

    # Run the same assessment used by configuration changes. This is intentionally after table
    # creation and inside Alembic's transaction: a deployment cannot expose revised availability
    # before existing commitments have their findings recorded.
    bind = op.get_bind()
    now = datetime.now(timezone.utc)
    from app.models import Venue
    from app.venue_booking_assessment import assess_venue_bookings
    from sqlalchemy.orm import Session

    # Alembic owns the outer transaction. The savepoint lets ORM relationship loading and flushes
    # share that connection without committing independently of the schema migration.
    with Session(bind=bind, join_transaction_mode="create_savepoint") as session:
        for venue in session.scalars(sa.select(Venue).order_by(Venue.id)):
            assess_venue_bookings(
                session,
                venue,
                assessed_by_account_id=None,
                assessed_at=now,
            )
        session.commit()

    if bind.dialect.name == "postgresql":
        op.execute(f"ALTER TABLE {TABLE} ENABLE ROW LEVEL SECURITY")
        op.execute(f"REVOKE ALL ON TABLE {TABLE} FROM PUBLIC")
        op.execute(f"REVOKE ALL ON SEQUENCE {TABLE}_id_seq FROM PUBLIC")
        op.execute(
            f"""
            DO $$
            DECLARE role_name text;
            BEGIN
                FOREACH role_name IN ARRAY ARRAY['anon', 'authenticated'] LOOP
                    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = role_name) THEN
                        EXECUTE format('REVOKE ALL ON TABLE {TABLE} FROM %I', role_name);
                        EXECUTE format('REVOKE ALL ON SEQUENCE {TABLE}_id_seq FROM %I', role_name);
                    END IF;
                END LOOP;
            END $$;
            """
        )


def downgrade():
    op.drop_index("ix_venue_booking_review_findings_active", table_name=TABLE)
    op.drop_table(TABLE)
