"""finished_product_group table

Revision ID: 10b08a0df0d1
Revises: 82986e9353e0
Create Date: 2026-08-13
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "10b08a0df0d1"
down_revision = "82986e9353e0"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "finished_product_group",
        sa.Column("group_id", sa.Unicode(64), primary_key=True),
        sa.Column("name", sa.Unicode(255), nullable=False),
        sa.Column("product_ids", sa.UnicodeText(), nullable=False, server_default=""),
        sa.Column("created_by", sa.Unicode(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_finished_product_group_name", "finished_product_group", ["name"], unique=True)


def downgrade():
    op.drop_index("ix_finished_product_group_name", table_name="finished_product_group")
    op.drop_table("finished_product_group")
