"""Add event-level equipment requirement mapping and planning fields for SPL-90."""

import sqlalchemy as sa
from alembic import op

revision = "s3_equipment_requirements"
# This migration is unmerged, so it follows the newest migration on main rather than
# creating a second Alembic head beside SPL-138's timed venue-closure migration.
down_revision = "s3_timed_venue_closures"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "equipment_requirements",
        sa.Column("equipment_type_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_equipment_requirements_equipment_type_id",
        "equipment_requirements",
        "equipment_types",
        ["equipment_type_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_equipment_requirements_equipment_type_id",
        "equipment_requirements",
        ["equipment_type_id"],
    )
    op.add_column(
        "equipment_requirements",
        sa.Column("required_start_date", sa.Date(), nullable=True),
    )
    op.add_column(
        "equipment_requirements",
        sa.Column("required_end_date", sa.Date(), nullable=True),
    )
    op.add_column(
        "equipment_requirements",
        sa.Column("status", sa.String(length=40), nullable=False, server_default="unmapped"),
    )
    op.add_column(
        "equipment_requirements",
        sa.Column("essentiality", sa.String(length=20), nullable=False, server_default="undecided"),
    )
    op.add_column(
        "equipment_requirements",
        sa.Column("consulted_technical_support_account_id", sa.Uuid(), nullable=True),
    )
    op.add_column(
        "equipment_requirements",
        sa.Column("essentiality_decision_note", sa.Text(), nullable=True),
    )
    op.add_column(
        "equipment_requirements",
        sa.Column("essentiality_decided_by_account_id", sa.Uuid(), nullable=True),
    )
    op.add_column(
        "equipment_requirements",
        sa.Column("essentiality_decided_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "equipment_requirements",
        sa.Column("removed_by_account_id", sa.Uuid(), nullable=True),
    )
    op.add_column(
        "equipment_requirements",
        sa.Column("removed_at", sa.DateTime(timezone=True), nullable=True),
    )
    for column, constraint in (
        ("consulted_technical_support_account_id", "fk_eq_req_consulted_tech"),
        ("essentiality_decided_by_account_id", "fk_eq_req_essentiality_actor"),
        ("removed_by_account_id", "fk_eq_req_removed_actor"),
    ):
        op.create_foreign_key(
            constraint,
            "equipment_requirements",
            "accounts",
            [column],
            ["id"],
        )
    op.create_check_constraint(
        "ck_equipment_requirements_known_status",
        "equipment_requirements",
        "status in ('unmapped', 'requested', 'partially_reserved', 'reserved', "
        "'review_required', 'unavailable', 'removed')",
    )
    op.create_check_constraint(
        "ck_equipment_requirements_known_essentiality",
        "equipment_requirements",
        "essentiality in ('undecided', 'essential', 'non_essential')",
    )
    # Existing organiser lines are preserved as un-mapped requirement records.  Where the event
    # already has a date, that date supplies the safe default for both required boundaries.
    op.execute(
        """
        UPDATE equipment_requirements AS requirement
        SET required_start_date = event.proposed_date,
            required_end_date = event.proposed_date
        FROM event_requests AS event
        WHERE event.id = requirement.event_request_id
          AND event.proposed_date IS NOT NULL
        """
    )


def downgrade():
    op.drop_constraint("ck_equipment_requirements_known_essentiality", "equipment_requirements")
    op.drop_constraint("ck_equipment_requirements_known_status", "equipment_requirements")
    for constraint in (
        "fk_eq_req_removed_actor",
        "fk_eq_req_essentiality_actor",
        "fk_eq_req_consulted_tech",
    ):
        op.drop_constraint(constraint, "equipment_requirements")
    for name in (
        "removed_at",
        "removed_by_account_id",
        "essentiality_decided_at",
        "essentiality_decided_by_account_id",
        "essentiality_decision_note",
        "consulted_technical_support_account_id",
        "essentiality",
        "status",
        "required_end_date",
        "required_start_date",
    ):
        op.drop_column("equipment_requirements", name)
    op.drop_index(
        "ix_equipment_requirements_equipment_type_id", table_name="equipment_requirements"
    )
    op.drop_constraint("fk_equipment_requirements_equipment_type_id", "equipment_requirements")
    op.drop_column("equipment_requirements", "equipment_type_id")
