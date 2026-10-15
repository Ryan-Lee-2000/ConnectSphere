"""Add event change requests and their items (SPL-111, CS-E18-S1).

Revision ID: s3_event_change_requests
Revises: s3_requirement_unavailability

Two new tables: ``event_change_requests`` (one row per request, with its status, who submitted it
and when) and ``event_change_request_items`` (the field, its value at submission, the requested
value and the reason).

``uq_event_change_requests_one_pending`` is a *partial* unique index on the event that only covers
Pending rows, so the database refuses a second Pending request for an event (AC4) even if two
submissions race past the route's own check. Resolved requests will stay as history beside a new
Pending one. The predicate is imported from app.models so the model and database cannot drift.

Nothing existing is altered, so the previous application version keeps working while this deploys.
"""

import sqlalchemy as sa
from alembic import op
from app.models import CHANGE_REQUEST_STATUSES, ONE_PENDING_CHANGE_REQUEST

revision = "s3_event_change_requests"
down_revision = "s3_requirement_unavailability"
branch_labels = None
depends_on = None

TABLES = ("event_change_requests", "event_change_request_items")


def upgrade():
    op.create_table(
        "event_change_requests",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "event_request_id",
            sa.Integer(),
            sa.ForeignKey("event_requests.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column(
            "submitted_by_account_id",
            sa.Uuid(as_uuid=False),
            sa.ForeignKey("accounts.id"),
            nullable=False,
        ),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status in (" + ", ".join(repr(status) for status in CHANGE_REQUEST_STATUSES) + ")",
            name="ck_event_change_requests_known_status",
        ),
    )
    op.create_index(
        "ix_event_change_requests_event_request_id", "event_change_requests", ["event_request_id"]
    )
    op.create_index(
        "uq_event_change_requests_one_pending",
        "event_change_requests",
        ["event_request_id"],
        unique=True,
        postgresql_where=sa.text(ONE_PENDING_CHANGE_REQUEST),
    )

    op.create_table(
        "event_change_request_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "change_request_id",
            sa.Integer(),
            sa.ForeignKey("event_change_requests.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("field", sa.String(length=40), nullable=False),
        sa.Column("current_value", sa.JSON(), nullable=True),
        sa.Column("requested_value", sa.JSON(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.UniqueConstraint(
            "change_request_id", "field", name="uq_event_change_request_items_field"
        ),
    )
    op.create_index(
        "ix_event_change_request_items_change_request_id",
        "event_change_request_items",
        ["change_request_id"],
    )

    # Same lock-down as every other product table: row-level security on, and no direct access
    # for the browser's Supabase roles. test_postgres.py asserts every product table is in this
    # state.
    for table in TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"REVOKE ALL ON TABLE {table} FROM PUBLIC")
        op.execute(f"REVOKE ALL ON SEQUENCE {table}_id_seq FROM PUBLIC")
        op.execute(
            f"""
            DO $$
            DECLARE
                role_name text;
            BEGIN
                FOREACH role_name IN ARRAY ARRAY['anon', 'authenticated']
                LOOP
                    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = role_name) THEN
                        EXECUTE format('REVOKE ALL ON TABLE {table} FROM %I', role_name);
                        EXECUTE format('REVOKE ALL ON SEQUENCE {table}_id_seq FROM %I', role_name);
                    END IF;
                END LOOP;
            END $$;
            """
        )


def downgrade():
    op.drop_table("event_change_request_items")
    op.drop_table("event_change_requests")
