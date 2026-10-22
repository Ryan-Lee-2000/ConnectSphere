"""Remember which add request created each equipment requirement line (SPL-122 review).

Revision ID: s4_equipment_request_ids
Revises: s4_booking_requirement_review (SPL-106, the newest migration on main)

The Add form sends one request id with every attempt of one addition. Storing it, unique per
event, lets the server answer a retried request with the line it already created, so a lost
response cannot produce a second line or a second Technical Support notice (AC4).

Additive and nullable: existing lines have no request id, nulls never collide in the unique
constraint, and the previous application version keeps working while this deploys.
"""

import sqlalchemy as sa
from alembic import op

revision = "s4_equipment_request_ids"
down_revision = "s4_booking_requirement_review"
branch_labels = None
depends_on = None

TABLE = "equipment_requirements"
CONSTRAINT = "uq_equipment_requirements_request"


def upgrade():
    with op.batch_alter_table(TABLE) as batch:
        batch.add_column(sa.Column("request_id", sa.Uuid(as_uuid=False), nullable=True))
        batch.create_unique_constraint(CONSTRAINT, ["event_request_id", "request_id"])


def downgrade():
    with op.batch_alter_table(TABLE) as batch:
        batch.drop_constraint(CONSTRAINT, type_="unique")
        batch.drop_column("request_id")
