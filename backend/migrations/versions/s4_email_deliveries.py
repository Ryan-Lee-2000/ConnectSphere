"""Record each notice's role and keep an email record per notice (SPL-125).

Revision ID: s4_email_deliveries
Revises: s4_hold_expiry

* ``notifications.recipient_role``: the role a notice was sent for. Existing notices are given
  their role from the kind in their dedupe key (AC3d); an unknown kind stops the migration rather
  than guessing. The column is then required and must name a defined role (AC3a, AC3b).
* ``email_deliveries``: one row per notice email, sent or failed, never one per attempt (AC8,
  AC11). Row-level security is on and browser roles have no grants. Existing notices get no
  email.

Not additive for the running release: until the new release is live, the old one cannot create
notices because it does not name a role (accepted by the team, SPL-125 build, 28 Oct 2026).
"""

import sqlalchemy as sa
from alembic import op

revision = "s4_email_deliveries"
down_revision = "s4_hold_expiry"
branch_labels = None
depends_on = None

KNOWN_ROLE = (
    "recipient_role in ('event_organiser', 'event_operations_manager', 'event_coordinator', "
    "'venue_staff', 'technical_support_staff', 'safety_officer', 'attendee')"
)
# Every notice kind on main before SPL-125, with the role each was written for.
ROLE_BY_KIND = {
    "coordinator_assigned": "event_coordinator",
    "coordinator_removed": "event_coordinator",
    "clarification_answered": "event_coordinator",
    "change_request_submitted": "event_coordinator",
    "safety_decision": "event_coordinator",
}
ROLE_BY_PREFIX = {
    "organiser_": "event_organiser",
    "arrangement_": "event_coordinator",
    "technical_": "technical_support_staff",
    "venue_booking_": "venue_staff",
    "attendee_": "attendee",
}


def upgrade():
    op.add_column("notifications", sa.Column("recipient_role", sa.String(length=40)))
    _backfill_roles()
    op.alter_column(
        "notifications", "recipient_role", existing_type=sa.String(length=40), nullable=False
    )
    op.create_check_constraint("ck_notifications_known_role", "notifications", KNOWN_ROLE)
    op.create_table(
        "email_deliveries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "notification_id",
            sa.Integer(),
            sa.ForeignKey("notifications.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "recipient_account_id",
            sa.Uuid(as_uuid=False),
            sa.ForeignKey("accounts.id"),
            nullable=False,
        ),
        sa.Column("recipient_name", sa.Text(), nullable=False),
        sa.Column("recipient_role", sa.String(length=40), nullable=False),
        sa.Column("to_address", sa.Text(), nullable=False),
        sa.Column("subject", sa.Text(), nullable=False),
        sa.Column("body_text", sa.Text(), nullable=False),
        sa.Column("body_html", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=10), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("provider_message_id", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status in ('pending', 'sent', 'failed')", name="ck_email_deliveries_known_status"
        ),
        sa.CheckConstraint(
            "(status = 'pending' and sent_at is null and failed_at is null)"
            " or (status = 'sent' and sent_at is not null and failed_at is null)"
            " or (status = 'failed' and failed_at is not null and sent_at is null)",
            name="ck_email_deliveries_outcome",
        ),
        sa.CheckConstraint(KNOWN_ROLE, name="ck_email_deliveries_known_role"),
    )
    op.create_index(
        "ix_email_deliveries_status_next_attempt_at",
        "email_deliveries",
        ["status", "next_attempt_at"],
    )
    op.execute("ALTER TABLE email_deliveries ENABLE ROW LEVEL SECURITY")
    op.execute("REVOKE ALL ON TABLE email_deliveries FROM PUBLIC")
    op.execute("REVOKE ALL ON SEQUENCE email_deliveries_id_seq FROM PUBLIC")
    op.execute(
        """
        DO $$
        DECLARE
            role_name text;
        BEGIN
            FOREACH role_name IN ARRAY ARRAY['anon', 'authenticated']
            LOOP
                IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = role_name) THEN
                    EXECUTE format('REVOKE ALL ON TABLE email_deliveries FROM %I', role_name);
                    EXECUTE format(
                        'REVOKE ALL ON SEQUENCE email_deliveries_id_seq FROM %I', role_name);
                END IF;
            END LOOP;
        END $$;
        """
    )


def _backfill_roles():
    bind = op.get_bind()
    rows = bind.execute(sa.text("SELECT id, dedupe_key FROM notifications")).all()
    for notice_id, dedupe_key in rows:
        kind = dedupe_key.split(":", 1)[0]
        role = ROLE_BY_KIND.get(kind) or next(
            (role for prefix, role in ROLE_BY_PREFIX.items() if kind.startswith(prefix)), None
        )
        if role is None:
            raise RuntimeError(f"No role is known for notice kind {kind!r} (notice {notice_id}).")
        bind.execute(
            sa.text("UPDATE notifications SET recipient_role = :role WHERE id = :id"),
            {"role": role, "id": notice_id},
        )


def downgrade():
    op.drop_index("ix_email_deliveries_status_next_attempt_at", table_name="email_deliveries")
    op.drop_table("email_deliveries")
    op.drop_constraint("ck_notifications_known_role", "notifications", type_="check")
    op.drop_column("notifications", "recipient_role")
