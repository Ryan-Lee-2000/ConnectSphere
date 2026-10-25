"""Add Safety Officer review evidence and the Preparing event state (SPL-135)."""

# ruff: noqa: E501, E702
import sqlalchemy as sa
from alembic import op
from app.event_statuses import status_check_constraint

revision = "s4_safety_reviews"
down_revision = "s4_change_request_decisions"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_constraint("ck_event_requests_known_status", "event_requests", type_="check")
    op.create_check_constraint(
        "ck_event_requests_known_status", "event_requests", status_check_constraint()
    )
    op.create_table(
        "safety_reviews",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "event_request_id",
            sa.Integer(),
            sa.ForeignKey("event_requests.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("plan", sa.JSON(), nullable=False),
        sa.Column("arrangement_fingerprint", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column(
            "submitted_by_account_id",
            sa.Uuid(as_uuid=False),
            sa.ForeignKey("accounts.id"),
            nullable=False,
        ),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decided_by_account_id", sa.Uuid(as_uuid=False), sa.ForeignKey("accounts.id")),
        sa.Column("decided_at", sa.DateTime(timezone=True)),
        sa.Column("decision_reason", sa.Text()),
        sa.CheckConstraint(
            "status in ('submitted', 'approved', 'changes_requested', 'rejected')",
            name="ck_safety_reviews_known_status",
        ),
    )
    op.create_index("ix_safety_reviews_event_request_id", "safety_reviews", ["event_request_id"])
    if op.get_bind().dialect.name == "postgresql":
        # Browser roles never access business records directly; Flask owns this table.
        op.execute("ALTER TABLE safety_reviews ENABLE ROW LEVEL SECURITY")
        op.execute("REVOKE ALL ON TABLE safety_reviews FROM PUBLIC")
        op.execute("REVOKE ALL ON SEQUENCE safety_reviews_id_seq FROM PUBLIC")
        op.execute(
            """
            DO $$
            BEGIN
              IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
                REVOKE ALL ON TABLE safety_reviews FROM anon;
                REVOKE ALL ON SEQUENCE safety_reviews_id_seq FROM anon;
              END IF;
              IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
                REVOKE ALL ON TABLE safety_reviews FROM authenticated;
                REVOKE ALL ON SEQUENCE safety_reviews_id_seq FROM authenticated;
              END IF;
            END $$;
            """
        )
    op.drop_constraint("ck_account_roles_known_role", "account_roles", type_="check")
    op.create_check_constraint(
        "ck_account_roles_known_role",
        "account_roles",
        "role in ('event_organiser', 'event_operations_manager', 'event_coordinator', 'venue_staff', 'technical_support_staff', 'safety_officer', 'attendee')",
    )


def downgrade():
    op.drop_constraint("ck_account_roles_known_role", "account_roles", type_="check")
    op.create_check_constraint(
        "ck_account_roles_known_role",
        "account_roles",
        "role in ('event_organiser', 'event_operations_manager', 'event_coordinator', 'venue_staff', 'technical_support_staff', 'attendee')",
    )
    op.drop_index("ix_safety_reviews_event_request_id", table_name="safety_reviews")
    op.drop_table("safety_reviews")
    op.drop_constraint("ck_event_requests_known_status", "event_requests", type_="check")
    op.create_check_constraint(
        "ck_event_requests_known_status",
        "event_requests",
        "status in ('draft', 'submitted', 'under_review', 'returned_for_clarification', 'approved', 'planning', 'confirmed', 'completed', 'cancelled', 'rejected', 'withdrawn', 'postponed')",
    )
