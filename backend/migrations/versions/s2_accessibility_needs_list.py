"""Store event request accessibility needs as a list rather than free text.

Revision ID: s2_accessibility_needs_list
Revises: s2_booking_review_marker

``accessibility_needs`` moves from a single free-text column to a JSON list of strings,
matching ``required_facilities``, so the event request form can offer venue-scoped
multi-select options instead of a single free-text field. Existing text values are
preserved by wrapping them in a one-element list; empty/null values become ``[]``.
"""

import sqlalchemy as sa
from alembic import op

revision = "s2_accessibility_needs_list"
down_revision = "s2_booking_review_marker"
branch_labels = None
depends_on = None

TABLE = "event_requests"


def upgrade():
    op.add_column(TABLE, sa.Column("accessibility_needs_list", sa.JSON(), nullable=True))
    op.execute(
        f"""
        UPDATE {TABLE}
        SET accessibility_needs_list = CASE
            WHEN accessibility_needs IS NULL OR btrim(accessibility_needs) = '' THEN '[]'::json
            ELSE json_build_array(accessibility_needs)
        END
        """
    )
    with op.batch_alter_table(TABLE) as batch:
        batch.alter_column(
            "accessibility_needs_list",
            nullable=False,
            server_default=sa.text("'[]'::json"),
        )
        batch.drop_column("accessibility_needs")
        batch.alter_column("accessibility_needs_list", new_column_name="accessibility_needs")


def downgrade():
    connection = op.get_bind()
    multi_valued = connection.execute(
        sa.text(f"select count(*) from {TABLE} where json_array_length(accessibility_needs) > 1")
    ).scalar_one()
    if multi_valued:
        raise RuntimeError(
            f"{multi_valued} event request(s) hold more than one accessibility need. "
            "Downgrading would lose data. Resolve them before downgrading."
        )

    op.add_column(TABLE, sa.Column("accessibility_needs_text", sa.Text(), nullable=True))
    op.execute(
        f"""
        UPDATE {TABLE}
        SET accessibility_needs_text = CASE
            WHEN json_array_length(accessibility_needs) = 0 THEN NULL
            ELSE accessibility_needs->>0
        END
        """
    )
    with op.batch_alter_table(TABLE) as batch:
        batch.drop_column("accessibility_needs")
        batch.alter_column("accessibility_needs_text", new_column_name="accessibility_needs")
