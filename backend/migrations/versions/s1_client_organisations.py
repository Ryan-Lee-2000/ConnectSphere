"""Add trusted client-organisation membership and event ownership.

Revision ID: s1_client_organisations
Revises: sprint1_event_request_drafts
"""

import sqlalchemy as sa
from alembic import op

revision = "s1_client_organisations"
down_revision = "sprint1_event_request_drafts"
branch_labels = None
depends_on = None


def _secure_organisations() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute("ALTER TABLE organisations ENABLE ROW LEVEL SECURITY")
    op.execute("REVOKE ALL ON TABLE organisations FROM PUBLIC")
    op.execute("REVOKE ALL ON SEQUENCE organisations_id_seq FROM PUBLIC")
    op.execute(
        """
        DO $$
        DECLARE role_name text;
        BEGIN
          FOREACH role_name IN ARRAY ARRAY['anon', 'authenticated']
          LOOP
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = role_name) THEN
              EXECUTE format('REVOKE ALL ON TABLE organisations FROM %I', role_name);
              EXECUTE format('REVOKE ALL ON SEQUENCE organisations_id_seq FROM %I', role_name);
            END IF;
          END LOOP;
        END $$;
        """
    )


def upgrade():
    op.create_table(
        "organisations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.UniqueConstraint("name", name="uq_organisations_name"),
    )
    _secure_organisations()

    op.add_column("accounts", sa.Column("display_name", sa.Text(), nullable=True))
    op.add_column("accounts", sa.Column("organisation_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_accounts_organisation_id",
        "accounts",
        "organisations",
        ["organisation_id"],
        ["id"],
    )
    op.create_index("ix_accounts_organisation_id", "accounts", ["organisation_id"])

    # Existing data is demo data with no recorded client. Preserve it under one explicit
    # migration organisation so no submitted event becomes unscoped during deployment.
    op.execute("INSERT INTO organisations (name) VALUES ('Existing client organisation')")
    op.execute("UPDATE accounts SET display_name = CAST(id AS TEXT)")
    op.execute(
        """
        UPDATE accounts
        SET organisation_id = (SELECT id FROM organisations
                               WHERE name = 'Existing client organisation')
        WHERE id IN (SELECT account_id FROM account_roles WHERE role = 'event_organiser')
           OR id IN (SELECT organiser_account_id FROM event_requests)
        """
    )
    op.execute(
        """
        UPDATE event_requests
        SET organisation_id = (
          SELECT accounts.organisation_id
          FROM accounts
          WHERE accounts.id = event_requests.organiser_account_id
        )
        """
    )

    op.alter_column("accounts", "display_name", existing_type=sa.Text(), nullable=False)
    op.create_foreign_key(
        "fk_event_requests_organisation_id",
        "event_requests",
        "organisations",
        ["organisation_id"],
        ["id"],
    )
    op.alter_column("event_requests", "organisation_id", existing_type=sa.Integer(), nullable=False)
    op.create_index("ix_event_requests_organisation_id", "event_requests", ["organisation_id"])


def downgrade():
    op.drop_index("ix_event_requests_organisation_id", table_name="event_requests")
    op.alter_column("event_requests", "organisation_id", existing_type=sa.Integer(), nullable=True)
    op.drop_constraint("fk_event_requests_organisation_id", "event_requests", type_="foreignkey")
    op.drop_index("ix_accounts_organisation_id", table_name="accounts")
    op.drop_constraint("fk_accounts_organisation_id", "accounts", type_="foreignkey")
    op.drop_column("accounts", "organisation_id")
    op.drop_column("accounts", "display_name")
    op.drop_table("organisations")
