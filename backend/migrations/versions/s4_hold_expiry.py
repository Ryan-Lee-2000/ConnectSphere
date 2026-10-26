"""Give tentative venue holds an expiry deadline (SPL-133).

Revision ID: s4_hold_expiry
Revises: s4_event_completion

* ``venue_bookings.expires_at``: when a Requested booking (the tentative hold) expires, with an
  index on (status, expires_at) so due holds are found without scanning every booking.
* ``expired`` joins the known booking statuses.
* ``venue_booking_status_history.actor_account_id`` becomes nullable: expiry is a system action
  that no account performs.
* Cutover (team proposal on the story): every existing Requested booking receives the same default
  deadline as a new hold, measured from this migration: 7 days later, or the booking's event start
  if that is still in the future and earlier. Nothing is backdated.

Additive for the running release: it never reads ``expires_at`` and never writes ``expired``.
"""

from datetime import datetime, timedelta, timezone

import sqlalchemy as sa
from alembic import op

revision = "s4_hold_expiry"
down_revision = "s4_event_completion"
branch_labels = None
depends_on = None

SINGAPORE = timezone(timedelta(hours=8))
DEFAULT_HOLD = timedelta(days=7)
OLD_STATUSES = "status in ('requested', 'approved', 'rejected', 'withdrawn', 'cancelled')"
NEW_STATUSES = (
    "status in ('requested', 'approved', 'rejected', 'withdrawn', 'cancelled', 'expired')"
)


def upgrade():
    with op.batch_alter_table("venue_bookings") as batch:
        batch.add_column(sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True))
        batch.drop_constraint("ck_venue_bookings_known_status", type_="check")
        batch.create_check_constraint("ck_venue_bookings_known_status", NEW_STATUSES)
    op.create_index(
        "ix_venue_bookings_status_expires_at", "venue_bookings", ["status", "expires_at"]
    )
    with op.batch_alter_table("venue_booking_status_history") as batch:
        batch.alter_column("actor_account_id", existing_type=sa.Uuid(as_uuid=False), nullable=True)
    _backfill_deadlines(datetime.now(SINGAPORE))


def _backfill_deadlines(now):
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            "SELECT b.id, b.exact_timing, b.booking_date, e.start_time "
            "FROM venue_bookings b JOIN event_requests e ON e.id = b.event_request_id "
            "WHERE b.status = 'requested' AND b.expires_at IS NULL"
        )
    ).all()
    for booking_id, timing, booking_date, start_time in rows:
        deadline = now + DEFAULT_HOLD
        start = _event_start(timing, booking_date, start_time)
        if start is not None and now < start < deadline:
            deadline = start
        bind.execute(
            sa.text("UPDATE venue_bookings SET expires_at = :deadline WHERE id = :id"),
            {"deadline": deadline, "id": booking_id},
        )


def _event_start(timing, booking_date, start_time):
    if isinstance(timing, dict):
        try:
            return datetime.fromisoformat(timing["event"]["start"])
        except (KeyError, TypeError, ValueError):
            return None
    if booking_date and start_time:
        return datetime.combine(booking_date, start_time, tzinfo=SINGAPORE)
    return None


def downgrade():
    bind = op.get_bind()
    blocked = bind.execute(
        sa.text(
            "SELECT (SELECT count(*) FROM venue_bookings WHERE status = 'expired') + "
            "(SELECT count(*) FROM venue_booking_status_history WHERE actor_account_id IS NULL)"
        )
    ).scalar()
    if blocked:
        raise RuntimeError(
            "Cannot downgrade SPL-133 while expired holds or system history entries exist."
        )
    with op.batch_alter_table("venue_booking_status_history") as batch:
        batch.alter_column("actor_account_id", existing_type=sa.Uuid(as_uuid=False), nullable=False)
    op.drop_index("ix_venue_bookings_status_expires_at", table_name="venue_bookings")
    with op.batch_alter_table("venue_bookings") as batch:
        batch.drop_constraint("ck_venue_bookings_known_status", type_="check")
        batch.create_check_constraint("ck_venue_bookings_known_status", OLD_STATUSES)
        batch.drop_column("expires_at")
