"""Record units of equipment as unavailable, and why (SPL-96).

Revision ID: s3_equipment_unavailable_units
Revises: s3_equipment_review_notes (SPL-92, which this change set is stacked on)

Re-pointed twice as main moved: first from s3_registration_withdrawals to
s3_equipment_reservations when SPL-97 merged and branched from the same parent, then to
s3_equipment_review_notes when this change set was stacked on SPL-92. The single linear chain
is what test_postgres.py asserts, and the PostgreSQL case reads its own parent from this file,
so a re-point needs no test change.

Two additive changes:

- ``equipment_types.unavailable_units``: the running total of units currently out of service.
  It is NOT NULL with a server default of 0, so every row that already exists reads as "all
  stock usable" without being rewritten, and the previous application version keeps working
  while this deploys.
- ``ck_equipment_types_unavailable_in_stock``: the database itself refuses a total outside
  0..total_stock (SPL-96 AC1). The constraint text is imported from app.models so the model and
  the database cannot drift apart.
- ``equipment_unavailability_records``: the history behind that total. AC1 asks for the reason,
  who and when on every change, restorations included.
- ``equipment_requirements.review_reason`` and ``review_flagged_at``: why a line was marked
  Review Required, and when (SPL-96 AC3/AC4). Both nullable, so every existing line reads as
  "not flagged" without being rewritten.

``ondelete="CASCADE"`` on the equipment type matches the catalogue's own lifecycle: the history of
a type that no longer exists is not meaningful on its own.
"""

import sqlalchemy as sa
from alembic import op
from app.models import UNAVAILABLE_WITHIN_STOCK

revision = "s3_equipment_unavailable_units"
down_revision = "s3_equipment_review_notes"
branch_labels = None
depends_on = None

TYPES_TABLE = "equipment_types"
STOCK_CONSTRAINT = "ck_equipment_types_unavailable_in_stock"
RECORDS_TABLE = "equipment_unavailability_records"
REQUIREMENTS_TABLE = "equipment_requirements"
REVIEW_COLUMNS = ("review_reason", "review_flagged_at")


def upgrade():
    # SPL-96 AC3/AC4. The flag itself is the existing ``status`` value; these carry its reason.
    with op.batch_alter_table(REQUIREMENTS_TABLE) as batch:
        batch.add_column(sa.Column("review_reason", sa.Text()))
        batch.add_column(sa.Column("review_flagged_at", sa.DateTime(timezone=True)))

    with op.batch_alter_table(TYPES_TABLE) as batch:
        batch.add_column(
            sa.Column(
                "unavailable_units",
                sa.Integer(),
                nullable=False,
                server_default="0",
            )
        )
        batch.create_check_constraint(STOCK_CONSTRAINT, UNAVAILABLE_WITHIN_STOCK)

    op.create_table(
        RECORDS_TABLE,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "equipment_type_id",
            sa.Integer(),
            sa.ForeignKey("equipment_types.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("action", sa.String(length=20), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column(
            "recorded_by_account_id",
            sa.Uuid(as_uuid=False),
            sa.ForeignKey("accounts.id"),
            nullable=False,
        ),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "quantity > 0", name="ck_equipment_unavailability_records_positive_quantity"
        ),
        sa.CheckConstraint(
            "action in ('marked_unavailable', 'restored')",
            name="ck_equipment_unavailability_records_known_action",
        ),
    )
    op.create_index(f"ix_{RECORDS_TABLE}_equipment_type_id", RECORDS_TABLE, ["equipment_type_id"])

    # Same lock-down as every other product table: row-level security on, and no direct access
    # for the browser's Supabase roles. These records name who took equipment out of service, so
    # they are only reachable through Flask, which checks who is asking (AGENTS.md).
    # test_postgres.py asserts every product table is in this state.
    op.execute(f"ALTER TABLE {RECORDS_TABLE} ENABLE ROW LEVEL SECURITY")
    op.execute(f"REVOKE ALL ON TABLE {RECORDS_TABLE} FROM PUBLIC")
    op.execute(f"REVOKE ALL ON SEQUENCE {RECORDS_TABLE}_id_seq FROM PUBLIC")
    op.execute(
        f"""
        DO $$
        DECLARE
            role_name text;
        BEGIN
            FOREACH role_name IN ARRAY ARRAY['anon', 'authenticated']
            LOOP
                IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = role_name) THEN
                    EXECUTE format('REVOKE ALL ON TABLE {RECORDS_TABLE} FROM %I', role_name);
                    EXECUTE format(
                        'REVOKE ALL ON SEQUENCE {RECORDS_TABLE}_id_seq FROM %I', role_name
                    );
                END IF;
            END LOOP;
        END $$;
        """
    )


def downgrade():
    # Reverse order: the history table references the types table.
    op.drop_index(f"ix_{RECORDS_TABLE}_equipment_type_id", table_name=RECORDS_TABLE)
    op.drop_table(RECORDS_TABLE)
    with op.batch_alter_table(TYPES_TABLE) as batch:
        batch.drop_constraint(STOCK_CONSTRAINT, type_="check")
        batch.drop_column("unavailable_units")
    with op.batch_alter_table(REQUIREMENTS_TABLE) as batch:
        for column in REVIEW_COLUMNS:
            batch.drop_column(column)
