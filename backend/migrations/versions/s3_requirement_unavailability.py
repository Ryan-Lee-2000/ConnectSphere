"""Record unavailable/restored decisions on individual event equipment requirements (SPL-93)."""

import sqlalchemy as sa
from alembic import op

revision = "s3_requirement_unavailability"
down_revision = "s3_equipment_releases"
branch_labels = None
depends_on = None

TABLE = "equipment_requirement_unavailability_records"


def _secure_table() -> None:
    """RLS and revoked browser-role grants keep decision history behind Flask authorization."""

    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(f"ALTER TABLE {TABLE} ENABLE ROW LEVEL SECURITY")
    op.execute(f"REVOKE ALL ON TABLE {TABLE} FROM PUBLIC")
    op.execute(f"REVOKE ALL ON SEQUENCE {TABLE}_id_seq FROM PUBLIC")
    op.execute(
        f"""
        DO $$
        DECLARE role_name text;
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


def upgrade():
    op.create_table(
        TABLE,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("equipment_requirement_id", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("reason", sa.Text()),
        sa.Column("alternative_suggestion", sa.Text()),
        sa.Column("recorded_by_account_id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["equipment_requirement_id"], ["equipment_requirements.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["recorded_by_account_id"], ["accounts.id"]),
        sa.CheckConstraint(
            "action in ('marked_unavailable', 'restored_to_requested')",
            name="ck_equipment_requirement_unavailability_records_known_action",
        ),
        sa.CheckConstraint(
            "action != 'marked_unavailable' OR (reason IS NOT NULL AND length(trim(reason)) > 0)",
            name="ck_equipment_requirement_unavailability_records_mark_reason",
        ),
    )
    # PostgreSQL limits identifiers to 63 characters; use a short, explicit lookup index name.
    op.create_index("ix_equipment_unavail_requirement_id", TABLE, ["equipment_requirement_id"])
    _secure_table()


def downgrade():
    op.drop_index("ix_equipment_unavail_requirement_id", table_name=TABLE)
    op.drop_table(TABLE)
