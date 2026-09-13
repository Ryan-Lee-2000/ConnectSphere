"""Bridge pre-SPL-44 local venue databases to trusted account-role authorization.

Revision ID: s1_venue_auth_bridge
Revises: sprint1_venue_layouts
"""

import sqlalchemy as sa
from alembic import op

revision = "s1_venue_auth_bridge"
down_revision = "sprint1_venue_layouts"
branch_labels = None
depends_on = None

ROLE_VALUES = (
    "event_organiser",
    "event_operations_manager",
    "event_coordinator",
    "venue_staff",
    "technical_support_staff",
    "attendee",
)


def upgrade():
    """Create S2's tables when an older local catalogue database skipped them."""

    existing = set(sa.inspect(op.get_bind()).get_table_names())
    if "accounts" in existing and "account_roles" in existing:
        return

    op.create_table(
        "accounts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "account_roles",
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(length=40), nullable=False),
        sa.CheckConstraint(
            "role in (" + ", ".join(repr(role) for role in ROLE_VALUES) + ")",
            name="ck_account_roles_known_role",
        ),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("account_id", "role"),
    )
    for table in ("accounts", "account_roles"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"""
            DO $$
            DECLARE
                role_name text;
            BEGIN
                FOREACH role_name IN ARRAY ARRAY['anon', 'authenticated']
                LOOP
                    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = role_name) THEN
                        EXECUTE format('REVOKE ALL ON TABLE {table} FROM %I', role_name);
                    END IF;
                END LOOP;
            END $$;
            """
        )


def downgrade():
    op.drop_table("account_roles")
    op.drop_table("accounts")
