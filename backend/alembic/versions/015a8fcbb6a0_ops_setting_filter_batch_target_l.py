"""ops_setting filter_batch_target_l

Revision ID: 015a8fcbb6a0
Revises: 9b4c3e2a1d7f
Create Date: 2026-10-21
"""
from alembic import op
import sqlalchemy as sa

revision = "015a8fcbb6a0"
down_revision = "9b4c3e2a1d7f"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("ops_setting", sa.Column("filter_batch_target_l", sa.Float(),
                                           nullable=False, server_default="200000"))


def downgrade():
    op.drop_column("ops_setting", "filter_batch_target_l")
