"""load_order_warehouse_link

Revision ID: fdf26676925d
Revises: 080916af3e3d
Create Date: 2026-08-19 12:58:13.477489
"""
from alembic import op
import sqlalchemy as sa


revision = 'fdf26676925d'
down_revision = '080916af3e3d'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('load_order') as batch_op:
        batch_op.add_column(sa.Column('warehouse_id', sa.Unicode(length=64), nullable=True))
        batch_op.create_index('ix_load_order_warehouse_id', ['warehouse_id'])


def downgrade() -> None:
    with op.batch_alter_table('load_order') as batch_op:
        batch_op.drop_index('ix_load_order_warehouse_id')
        batch_op.drop_column('warehouse_id')
