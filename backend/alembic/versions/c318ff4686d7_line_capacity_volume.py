"""công suất (dây chuyền) + thể tích (tank) trên Danh mục ProductionLine

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-07-18

- production_line: thêm capacity_uom (đơn vị công suất, dùng khi kind="line") và
  volume/volume_uom (thể tích + đơn vị, dùng khi kind="tank"/"tank_bbt") — để tách
  Danh mục "Dây chuyền & Tank" (1 panel dùng chung) thành 3 mục riêng: Dây chuyền sản
  xuất (công suất), Tank lên men (thể tích), Tank thành phẩm (thể tích).
"""
from alembic import op
import sqlalchemy as sa

from app.alembic_mssql import prep_drop_columns

revision = 'c318ff4686d7'
down_revision = '72757896fc52'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('production_line') as batch_op:
        batch_op.add_column(sa.Column('capacity_uom', sa.Unicode(length=64), nullable=True))
        batch_op.add_column(sa.Column('volume', sa.Float(), nullable=True))
        batch_op.add_column(sa.Column('volume_uom', sa.Unicode(length=64), nullable=True))


def downgrade() -> None:
    prep_drop_columns(op.get_bind(), 'production_line', ['volume_uom', 'volume', 'capacity_uom'])
    with op.batch_alter_table('production_line') as batch_op:
        batch_op.drop_column('volume_uom')
        batch_op.drop_column('volume')
        batch_op.drop_column('capacity_uom')
