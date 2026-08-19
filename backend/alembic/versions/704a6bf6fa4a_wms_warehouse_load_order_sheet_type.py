"""wms_warehouse_load_order_sheet_type

Revision ID: 704a6bf6fa4a
Revises: 60e22975e4c9
Create Date: 2026-08-18 00:04:17.951544
"""
from alembic import op
import sqlalchemy as sa


revision = '704a6bf6fa4a'
down_revision = '60e22975e4c9'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('wms_warehouse', sa.Column('load_order_sheet_type', sa.Unicode(length=16), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('wms_warehouse') as batch_op:
        batch_op.drop_column('load_order_sheet_type')
