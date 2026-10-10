"""Persist Technical Support equipment reservations for SPL-97.

Revision ID: s3_equipment_reservations
Revises: s3_registration_withdrawals

The reservation is intentionally an append-only commitment record rather than a cached count on
``equipment_requirements``.  This lets the availability calculation include every overlapping
event and preserves who reserved which quantity and when.
"""

import sqlalchemy as sa
from alembic import op

revision = "s3_equipment_reservations"
down_revision = "s3_registration_withdrawals"
branch_labels = None
depends_on = None


def _secure_table() -> None:
    """Keep reservation records reachable only through the authorised Flask API."""
    if op.get_bind().dialect.name != "postgresql":
        return

    table = "equipment_reservations"
    sequence = "equipment_reservations_id_seq"
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"REVOKE ALL ON TABLE {table} FROM PUBLIC")
    op.execute(f"REVOKE ALL ON SEQUENCE {sequence} FROM PUBLIC")
    op.execute(
        f"""
        DO $$
        DECLARE role_name text;
        BEGIN
            FOREACH role_name IN ARRAY ARRAY['anon', 'authenticated']
            LOOP
                IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = role_name) THEN
                    EXECUTE format('REVOKE ALL ON TABLE {table} FROM %I', role_name);
                    EXECUTE format('REVOKE ALL ON SEQUENCE {sequence} FROM %I', role_name);
                END IF;
            END LOOP;
        END $$;
        """
    )


def upgrade():
    op.create_table(
        "equipment_reservations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("event_request_id", sa.Integer(), nullable=False),
        sa.Column("equipment_requirement_id", sa.Integer(), nullable=False),
        sa.Column("equipment_type_id", sa.Integer(), nullable=False),
        sa.Column("commitment_start_date", sa.Date(), nullable=False),
        sa.Column("commitment_end_date", sa.Date(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("reserved_by_account_id", sa.Uuid(), nullable=False),
        sa.Column("reserved_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("quantity > 0", name="ck_equipment_reservations_positive_quantity"),
        sa.CheckConstraint(
            "commitment_start_date <= commitment_end_date",
            name="ck_equipment_reservations_date_order",
        ),
        sa.ForeignKeyConstraint(["event_request_id"], ["event_requests.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["equipment_requirement_id"], ["equipment_requirements.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["equipment_type_id"], ["equipment_types.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["reserved_by_account_id"], ["accounts.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_equipment_reservations_event_request_id",
        "equipment_reservations",
        ["event_request_id"],
    )
    op.create_index(
        "ix_equipment_reservations_equipment_requirement_id",
        "equipment_reservations",
        ["equipment_requirement_id"],
    )
    op.create_index(
        "ix_equipment_reservations_equipment_type_id",
        "equipment_reservations",
        ["equipment_type_id"],
    )
    op.create_index(
        "ix_equipment_reservations_type_commitment",
        "equipment_reservations",
        ["equipment_type_id", "commitment_start_date", "commitment_end_date"],
    )
    _secure_table()


def downgrade():
    op.drop_index("ix_equipment_reservations_type_commitment", table_name="equipment_reservations")
    op.drop_index(
        "ix_equipment_reservations_equipment_type_id", table_name="equipment_reservations"
    )
    op.drop_index(
        "ix_equipment_reservations_equipment_requirement_id", table_name="equipment_reservations"
    )
    op.drop_index("ix_equipment_reservations_event_request_id", table_name="equipment_reservations")
    op.drop_table("equipment_reservations")
