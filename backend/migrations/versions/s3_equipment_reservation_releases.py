"""Persist auditable partial releases without deleting SPL-97 reservation history.

Revision ID: s3_equipment_releases
Revises: s3_equipment_return_dates
"""

import sqlalchemy as sa
from alembic import op


revision = "s3_equipment_releases"
down_revision = "s3_equipment_return_dates"
branch_labels = None
depends_on = None


def _secure_table() -> None:
    """Keep release history available only through role-checked Flask routes."""

    if op.get_bind().dialect.name != "postgresql":
        return
    table = "equipment_reservation_releases"
    sequence = "equipment_reservation_releases_id_seq"
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
        "equipment_reservation_releases",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("reservation_id", sa.Integer(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("released_by_account_id", sa.Uuid(), nullable=False),
        sa.Column("released_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("quantity > 0", name="ck_equipment_reservation_releases_positive_quantity"),
        sa.ForeignKeyConstraint(
            ["reservation_id"], ["equipment_reservations.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["released_by_account_id"], ["accounts.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_equipment_reservation_releases_reservation_id",
        "equipment_reservation_releases",
        ["reservation_id"],
    )
    _secure_table()


def downgrade():
    op.drop_index(
        "ix_equipment_reservation_releases_reservation_id",
        table_name="equipment_reservation_releases",
    )
    op.drop_table("equipment_reservation_releases")
