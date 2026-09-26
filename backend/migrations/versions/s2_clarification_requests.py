"""Record clarification requests and add the Returned for clarification status (SPL-65).

Revision ID: s2_clarification_requests
Revises: s2_accessibility_needs_list

The status check constraint is regenerated from ``app.event_statuses`` so the database accepts
exactly the vocabulary the application describes. Clarification rows are append-only, so a
second request keeps the first as history.
"""

import sqlalchemy as sa
from alembic import op
from app.event_statuses import EVENT_REQUEST_STATUSES, status_check_constraint

revision = "s2_clarification_requests"
down_revision = "s2_accessibility_needs_list"
branch_labels = None
depends_on = None

CONSTRAINT = "ck_event_requests_known_status"
TABLE = "event_requests"
NEW_STATUS = "returned_for_clarification"


def upgrade():
    with op.batch_alter_table(TABLE) as batch:
        batch.drop_constraint(CONSTRAINT, type_="check")
        batch.create_check_constraint(CONSTRAINT, status_check_constraint())
    op.create_table(
        "clarification_requests",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "event_request_id",
            sa.Integer(),
            sa.ForeignKey("event_requests.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column(
            "author_account_id",
            sa.Uuid(as_uuid=False),
            sa.ForeignKey("accounts.id"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_clarification_requests_event_request_id",
        "clarification_requests",
        ["event_request_id"],
    )
    op.execute("ALTER TABLE clarification_requests ENABLE ROW LEVEL SECURITY")
    op.execute("REVOKE ALL ON TABLE clarification_requests FROM PUBLIC")
    op.execute("REVOKE ALL ON SEQUENCE clarification_requests_id_seq FROM PUBLIC")
    op.execute(
        """
        DO $$
        DECLARE
            role_name text;
        BEGIN
            FOREACH role_name IN ARRAY ARRAY['anon', 'authenticated']
            LOOP
                IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = role_name) THEN
                    EXECUTE format('REVOKE ALL ON TABLE clarification_requests FROM %I', role_name);
                    EXECUTE format(
                        'REVOKE ALL ON SEQUENCE clarification_requests_id_seq FROM %I', role_name);
                END IF;
            END LOOP;
        END $$;
        """
    )


def downgrade():
    # Dropping the status would orphan any request that holds it, so refuse rather than
    # break the recreated check constraint.
    returned = (
        op.get_bind()
        .execute(
            sa.text(f"select count(*) from {TABLE} where status = :status"),
            {"status": NEW_STATUS},
        )
        .scalar_one()
    )
    if returned:
        raise RuntimeError(
            f"{returned} event request(s) are Returned for clarification. "
            "Resolve them before downgrading."
        )
    op.drop_table("clarification_requests")
    remaining = ", ".join(
        f"'{status}'" for status in EVENT_REQUEST_STATUSES if status != NEW_STATUS
    )
    with op.batch_alter_table(TABLE) as batch:
        batch.drop_constraint(CONSTRAINT, type_="check")
        batch.create_check_constraint(CONSTRAINT, f"status in ({remaining})")
