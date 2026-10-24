"""Add final per-item decisions and Closed requests (SPL-112)."""

import sqlalchemy as sa
from alembic import op

revision = "s4_change_request_decisions"
down_revision = "s4_equipment_request_ids"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("event_change_requests") as batch:
        batch.drop_constraint("ck_event_change_requests_known_status", type_="check")
        batch.create_check_constraint(
            "ck_event_change_requests_known_status", "status IN ('pending', 'closed')"
        )
    with op.batch_alter_table("event_change_request_items") as batch:
        batch.add_column(sa.Column("decision", sa.String(20), nullable=True))
        batch.add_column(sa.Column("decline_reason", sa.Text(), nullable=True))
        batch.add_column(sa.Column("decided_by_account_id", sa.Uuid(as_uuid=False), nullable=True))
        batch.add_column(sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True))
        batch.create_foreign_key(
            "fk_change_request_item_decider", "accounts", ["decided_by_account_id"], ["id"]
        )
        batch.create_check_constraint(
            "ck_change_request_item_decision",
            "(decision IS NULL AND decline_reason IS NULL AND decided_by_account_id IS NULL "
            "AND decided_at IS NULL) OR (decision IS NOT NULL AND "
            "decision IN ('accepted', 'declined') AND decided_by_account_id IS NOT NULL "
            "AND decided_at IS NOT NULL AND ((decision = 'accepted' AND decline_reason IS NULL) "
            "OR (decision = 'declined' AND decline_reason IS NOT NULL "
            "AND length(trim(decline_reason)) > 0)))",
        )


def downgrade():
    # Refuse to erase decisions or reopen Closed requests, which could permit duplicate effects.
    connection = op.get_bind()
    if connection.scalar(
        sa.text("SELECT count(*) FROM event_change_request_items WHERE decision IS NOT NULL")
    ):
        raise RuntimeError("Cannot downgrade SPL-112 after decisions have been recorded.")
    if connection.scalar(
        sa.text("SELECT count(*) FROM event_change_requests WHERE status = 'closed'")
    ):
        raise RuntimeError("Cannot downgrade SPL-112 while Closed requests exist.")
    with op.batch_alter_table("event_change_request_items") as batch:
        batch.drop_constraint("ck_change_request_item_decision", type_="check")
        batch.drop_constraint("fk_change_request_item_decider", type_="foreignkey")
        for column in ("decided_at", "decided_by_account_id", "decline_reason", "decision"):
            batch.drop_column(column)
    with op.batch_alter_table("event_change_requests") as batch:
        batch.drop_constraint("ck_event_change_requests_known_status", type_="check")
        batch.create_check_constraint("ck_event_change_requests_known_status", "status = 'pending'")
