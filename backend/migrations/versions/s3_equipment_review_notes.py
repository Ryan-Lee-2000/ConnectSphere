"""Technical Support notes and clarification questions on requirement lines (SPL-92).

Revision ID: s3_equipment_review_notes
Revises: s3_equipment_reservations (SPL-97, the newest migration on main when this was written)

NOTE FOR WHOEVER MERGES SECOND: SPL-96's ``s3_equipment_unavailable_units`` also branches from
``s3_equipment_reservations``. Whichever of the two merges second must re-point its
``down_revision`` at the other, or there will be two heads and test_postgres.py will fail. The
PostgreSQL case reads its own parent from this file, so a re-point needs no test change.

One new table. ``equipment_requirements`` is not altered, because AC4 is explicit that this story
changes no line: the notes hang off a line without touching it.

``ondelete="CASCADE"`` matches the reservation table's choice: a note about a line that no longer
exists is not meaningful on its own.
"""

import sqlalchemy as sa
from alembic import op

revision = "s3_equipment_review_notes"
down_revision = "s3_equipment_reservations"
branch_labels = None
depends_on = None

TABLE = "equipment_review_notes"


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
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column(
            "author_account_id",
            sa.Uuid(as_uuid=False),
            sa.ForeignKey("accounts.id"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        # The route refuses a blank note with a readable 400; this is the backstop that makes the
        # rule true whatever reaches the database.
        sa.CheckConstraint(
            "length(trim(note)) > 0", name="ck_equipment_review_notes_note_not_blank"
        ),
    )
    op.create_index(f"ix_{TABLE}_equipment_requirement_id", TABLE, ["equipment_requirement_id"])
    # The queue reads a line's notes oldest first, which is this index's job.
    op.create_index(
        f"ix_{TABLE}_requirement_created", TABLE, ["equipment_requirement_id", "created_at"]
    )

    # Same lock-down as every other product table: row-level security on, and no direct access
    # for the browser's Supabase roles. Notes name who asked what about whose event, so they are
    # only reachable through Flask, which checks who is asking (AGENTS.md).
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
    op.drop_index(f"ix_{TABLE}_requirement_created", table_name=TABLE)
    op.drop_index(f"ix_{TABLE}_equipment_requirement_id", table_name=TABLE)
    op.drop_table(TABLE)
