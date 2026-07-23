"""nguyên liệu dùng cho mẻ nấu lấy thật từ tồn kho Kho phân xưởng (MaterialLot)

Revision ID: f2a3b4c5d6e7
Revises: e1f2a3b4c5d6
Create Date: 2026-07-09

- brew_material_usage: thêm lot_id (FK material_lot) + movement_id (FK stock_movement) —
  gán NVL cho mẻ nấu giờ trừ tồn kho thật qua services/warehouse.py::issue(), hoàn kho thật
  qua undo_issue() khi xóa dòng, thay vì chỉ ghi tên tự do không liên quan tới Kho NVL thật.
"""
from alembic import op
import sqlalchemy as sa

from app.alembic_mssql import prep_drop_columns

revision = 'f2a3b4c5d6e7'
down_revision = 'e1f2a3b4c5d6'
branch_labels = None
depends_on = None

def upgrade() -> None:
    with op.batch_alter_table('brew_material_usage') as batch_op:
        batch_op.add_column(sa.Column('lot_id', sa.Unicode(length=64), sa.ForeignKey('material_lot.lot_id', name='fk_brew_material_usage_lot_id_material_lot'), nullable=True))
        batch_op.add_column(sa.Column('movement_id', sa.Unicode(length=64), sa.ForeignKey('stock_movement.movement_id', name='fk_brew_material_usage_movement_id_stock_movement'), nullable=True))
        batch_op.create_index('ix_brew_material_usage_lot_id', ['lot_id'])


def downgrade() -> None:
    prep_drop_columns(op.get_bind(), 'brew_material_usage', ['movement_id', 'lot_id'])
    with op.batch_alter_table('brew_material_usage') as batch_op:
        batch_op.drop_index('ix_brew_material_usage_lot_id')
        batch_op.drop_column('movement_id')
        batch_op.drop_column('lot_id')
