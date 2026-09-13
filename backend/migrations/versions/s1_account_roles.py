"""Add the trusted account-role authorization model."""

import sqlalchemy as sa
from alembic import op

revision = "s1_account_roles"
down_revision = "sprint0_base"
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
    op.create_table(
        "accounts",
        sa.Column("id", sa.Uuid(as_uuid=False), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "account_roles",
        sa.Column("account_id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("role", sa.String(length=40), nullable=False),
        sa.CheckConstraint(
            "role in (" + ", ".join(repr(role) for role in ROLE_VALUES) + ")",
            name="ck_account_roles_known_role",
        ),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("account_id", "role"),
    )

    if op.get_bind().dialect.name == "postgresql":
        op.execute("ALTER TABLE accounts ENABLE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE account_roles ENABLE ROW LEVEL SECURITY")
        op.execute("REVOKE ALL ON TABLE accounts, account_roles FROM PUBLIC")
        op.execute(
            """
            DO $$
            BEGIN
              IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
                REVOKE ALL ON TABLE accounts, account_roles FROM anon;
              END IF;
              IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
                REVOKE ALL ON TABLE accounts, account_roles FROM authenticated;
              END IF;
            END
            $$
            """
        )


def downgrade():
    op.drop_table("account_roles")
    op.drop_table("accounts")
