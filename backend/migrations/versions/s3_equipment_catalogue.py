"""Create the pooled equipment catalogue required by SPL-94."""

import sqlalchemy as sa
from alembic import op

revision = "s3_equipment_catalogue"
down_revision = "s3_exact_booking_snapshots"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "equipment_types",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("normalised_name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("location", sa.Text(), nullable=True),
        sa.Column("total_stock", sa.Integer(), nullable=False),
        sa.CheckConstraint("total_stock >= 0", name="ck_equipment_types_non_negative_stock"),
        sa.UniqueConstraint("normalised_name", name="uq_equipment_types_normalised_name"),
    )
    op.execute("ALTER TABLE equipment_types ENABLE ROW LEVEL SECURITY")
    op.execute("REVOKE ALL ON equipment_types FROM PUBLIC")
    op.execute("REVOKE ALL ON SEQUENCE equipment_types_id_seq FROM PUBLIC")
    op.execute(
        """
        DO $$
        DECLARE
            role_name text;
        BEGIN
            FOREACH role_name IN ARRAY ARRAY['anon', 'authenticated']
            LOOP
                IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = role_name) THEN
                    EXECUTE format('REVOKE ALL ON TABLE equipment_types FROM %I', role_name);
                    EXECUTE format(
                        'REVOKE ALL ON SEQUENCE equipment_types_id_seq FROM %I', role_name
                    );
                END IF;
            END LOOP;
        END $$;
        """
    )


def downgrade():
    op.drop_table("equipment_types")
