"""The history of coordinator changes and removals of requirement lines (SPL-91).

Revision ID: s3_equipment_requirement_changes
Revises: s3_equipment_releases (SPL-98, the newest migration on main when this was written)

One new table, ``equipment_requirement_changes``: one row per accepted change or removal, holding
the old and new values, how many units the action released, who made it and when (AC4).

``equipment_requirements`` is not altered. The release itself is recorded by SPL-98's
``equipment_reservation_releases``, which stays the only place units are released, so this table
only cross-references the quantity rather than duplicating the release.

``ondelete="CASCADE"`` matches SPL-92's review notes and SPL-98's releases: history about a line
that no longer exists is not meaningful on its own.
"""

import sqlalchemy as sa
from alembic import op

revision = "s3_equipment_requirement_changes"
down_revision = "s3_equipment_releases"
branch_labels = None
depends_on = None

TABLE = "equipment_requirement_changes"


def upgrade():
    op.create_table(
        TABLE,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "equipment_requirement_id",
            sa.Integer(),
            sa.ForeignKey("equipment_requirements.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("action", sa.String(length=20), nullable=False),
        sa.Column("old_values", sa.JSON(), nullable=False),
        sa.Column("new_values", sa.JSON(), nullable=False),
        sa.Column("released_quantity", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "changed_by_account_id",
            sa.Uuid(as_uuid=False),
            sa.ForeignKey("accounts.id"),
            nullable=False,
        ),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "action in ('changed', 'removed')",
            name="ck_equipment_requirement_changes_known_action",
        ),
        sa.CheckConstraint(
            "released_quantity >= 0",
            name="ck_equipment_requirement_changes_released_not_negative",
        ),
    )
    op.create_index(f"ix_{TABLE}_equipment_requirement_id", TABLE, ["equipment_requirement_id"])
    # The history route reads one line's changes newest first, which is this index's job.
    op.create_index(
        f"ix_{TABLE}_requirement_changed", TABLE, ["equipment_requirement_id", "changed_at"]
    )

    # Same lock-down as every other product table: row-level security on, and no direct access
    # for the browser's Supabase roles. The history names who changed what about whose event, so
    # it is reachable only through Flask, which checks who is asking (AGENTS.md).
    # test_postgres.py asserts every product table is in this state.
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
    op.drop_index(f"ix_{TABLE}_requirement_changed", table_name=TABLE)
    op.drop_index(f"ix_{TABLE}_equipment_requirement_id", table_name=TABLE)
    op.drop_table(TABLE)
