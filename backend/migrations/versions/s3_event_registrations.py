"""Store attendee registrations (SPL-116).

Revision ID: s3_event_registrations
Revises: s3_registration_settings (SPL-114, which this story builds on)

One additive change: a new ``event_registrations`` table, one row per attendee registration.

Two database guarantees back up the route's own checks:

- ``ck_event_registrations_known_status``: a registration is only ever Registered or Withdrawn.
- ``uq_event_registrations_one_active``: a *partial* unique index on (event, attendee) that only
  covers rows whose status is 'registered'. The database therefore refuses a second Registered
  row for the same attendee and event (SPL-116 AC5), while a Withdrawn row can stay as history
  next to a new Registered one.
"""

import sqlalchemy as sa
from alembic import op
from app.models import ONE_ACTIVE_REGISTRATION, REGISTRATION_STATUSES

revision = "s3_event_registrations"
down_revision = "s3_registration_settings"
branch_labels = None
depends_on = None

TABLE = "event_registrations"
STATUS_CHECK = "status in (" + ", ".join(repr(status) for status in REGISTRATION_STATUSES) + ")"


def upgrade():
    op.create_table(
        TABLE,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "event_request_id",
            sa.Integer(),
            sa.ForeignKey("event_requests.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "attendee_account_id",
            sa.Uuid(as_uuid=False),
            sa.ForeignKey("accounts.id"),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("contact_number", sa.Text(), nullable=False),
        sa.Column("special_requirements", sa.Text()),
        sa.Column("registered_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(STATUS_CHECK, name="ck_event_registrations_known_status"),
    )
    op.create_index(f"ix_{TABLE}_event_request_id", TABLE, ["event_request_id"])
    op.create_index(
        "uq_event_registrations_one_active",
        TABLE,
        ["event_request_id", "attendee_account_id"],
        unique=True,
        postgresql_where=sa.text(ONE_ACTIVE_REGISTRATION),
    )

    # Same lock-down as every other product table: row-level security on, and no direct access
    # for the browser's Supabase roles. Attendees' personal details are only reachable through
    # Flask, which checks who is asking (AGENTS.md).
    op.execute(f"ALTER TABLE {TABLE} ENABLE ROW LEVEL SECURITY")
    op.execute(f"REVOKE ALL ON TABLE {TABLE} FROM PUBLIC")
    op.execute(f"REVOKE ALL ON SEQUENCE {TABLE}_id_seq FROM PUBLIC")
    op.execute(
        f"""
        DO $$
        DECLARE
            role_name text;
        BEGIN
            FOREACH role_name IN ARRAY ARRAY['anon', 'authenticated']
            LOOP
                IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = role_name) THEN
                    EXECUTE format('REVOKE ALL ON TABLE {TABLE} FROM %I', role_name);
                    EXECUTE format('REVOKE ALL ON SEQUENCE {TABLE}_id_seq FROM %I', role_name);
                END IF;
            END LOOP;
        END $$;
        """
    )


def downgrade():
    op.drop_table(TABLE)
