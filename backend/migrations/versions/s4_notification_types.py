"""Give every notice a type and let each account turn email off per type (SPL-126).

Revision ID: s4_notification_types
Revises: s4_replacement_bookings

* ``notifications.notification_type``: one of the fixed types. Existing notices are given their
  type from the kind in their dedupe key (AC1); an unknown kind stops the migration rather than
  guessing. The column is then required and must name a known type.
* ``notification_email_opt_outs``: one row per account and type with email turned off. No rows
  means every type is on (AC3). Row-level security is on and browser roles have no grants.

Not additive for the running release: until the new release is live, the old one cannot create
notices because it does not set a type (as with SPL-125's ``recipient_role``).
"""

import sqlalchemy as sa
from alembic import op

revision = "s4_notification_types"
down_revision = "s4_replacement_bookings"
branch_labels = None
depends_on = None

# Every notice kind on main when SPL-126 merged, with its type.
TYPE_BY_KIND = {
    "coordinator_assigned": "coordinator_assignment",
    "coordinator_removed": "coordinator_assignment",
    "clarification_answered": "coordinator_requests",
    "change_request_submitted": "coordinator_requests",
    "arrangement_booking_approved": "coordinator_arrangements",
    "arrangement_booking_rejected": "coordinator_arrangements",
    "arrangement_booking_flagged": "coordinator_arrangements",
    "arrangement_equipment_flagged": "coordinator_arrangements",
    "arrangement_equipment_unavailable": "coordinator_arrangements",
    "arrangement_equipment_reserved": "coordinator_arrangements",
    "arrangement_hold_created": "coordinator_hold_deadlines",
    "arrangement_hold_deadline_changed": "coordinator_hold_deadlines",
    "arrangement_hold_expired": "coordinator_hold_deadlines",
    "safety_decision": "coordinator_safety",
    "organiser_clarification_requested": "organiser_review",
    "organiser_decision": "organiser_review",
    "organiser_withdrawn": "organiser_review",
    "organiser_coordinator_changed": "organiser_coordinator",
    "organiser_event_confirmed": "organiser_confirmation",
    "organiser_returned_to_planning": "organiser_confirmation",
    "organiser_change_item_decided": "organiser_confirmation",
    "organiser_event_cancelled": "organiser_confirmation",
    "technical_requirement_recorded": "technical_equipment",
    "technical_requirement_changed": "technical_equipment",
    "technical_requirement_removed": "technical_equipment",
    "technical_event_cancelled": "technical_equipment",
    "venue_booking_requested": "venue_booking_requests",
    "venue_booking_withdrawn": "venue_booking_requests",
    "attendee_registered": "attendee_registration",
    "attendee_withdrawn": "attendee_registration",
    "attendee_event_cancelled": "attendee_event_changes",
    "attendee_schedule_changed": "attendee_event_changes",
    "attendee_venue_added": "attendee_event_changes",
    "attendee_venue_removed": "attendee_event_changes",
}
KNOWN_TYPE = (
    "notification_type in ("
    + ", ".join(f"'{kind}'" for kind in sorted(set(TYPE_BY_KIND.values())))
    + ")"
)


def upgrade():
    op.add_column("notifications", sa.Column("notification_type", sa.String(length=40)))
    _backfill_types()
    op.alter_column(
        "notifications", "notification_type", existing_type=sa.String(length=40), nullable=False
    )
    op.create_check_constraint("ck_notifications_known_type", "notifications", KNOWN_TYPE)
    op.create_table(
        "notification_email_opt_outs",
        sa.Column(
            "account_id",
            sa.Uuid(as_uuid=False),
            sa.ForeignKey("accounts.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("notification_type", sa.String(length=40), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(KNOWN_TYPE, name="ck_notification_email_opt_outs_known_type"),
    )
    op.execute("ALTER TABLE notification_email_opt_outs ENABLE ROW LEVEL SECURITY")
    op.execute("REVOKE ALL ON TABLE notification_email_opt_outs FROM PUBLIC")
    op.execute(
        """
        DO $$
        DECLARE
            role_name text;
        BEGIN
            FOREACH role_name IN ARRAY ARRAY['anon', 'authenticated']
            LOOP
                IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = role_name) THEN
                    EXECUTE format(
                        'REVOKE ALL ON TABLE notification_email_opt_outs FROM %I', role_name);
                END IF;
            END LOOP;
        END $$;
        """
    )


def _backfill_types():
    bind = op.get_bind()
    rows = bind.execute(sa.text("SELECT id, dedupe_key FROM notifications")).all()
    for notice_id, dedupe_key in rows:
        kind = dedupe_key.split(":", 1)[0]
        if kind not in TYPE_BY_KIND:
            raise RuntimeError(f"No type is known for notice kind {kind!r} (notice {notice_id}).")
        bind.execute(
            sa.text("UPDATE notifications SET notification_type = :type WHERE id = :id"),
            {"type": TYPE_BY_KIND[kind], "id": notice_id},
        )


def downgrade():
    op.drop_table("notification_email_opt_outs")
    op.drop_constraint("ck_notifications_known_type", "notifications", type_="check")
    op.drop_column("notifications", "notification_type")
