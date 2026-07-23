"""nguyên liệu dùng thật cho 1 mẻ lọc (NVL lọc), trừ tồn kho Kho phân xưởng

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-07-17

- filter_material_usage: mirror brew_material_usage nhưng gắn với filter_record thay vì
  brew_batch — gán NVL cho 1 mẻ lọc trừ tồn kho thật qua services/warehouse.py::issue(),
  hoàn kho thật qua undo_issue() khi xóa dòng (bảng mới nên có đủ lot_id/movement_id ngay từ
  đầu, không cần tách 2 migration như brew_material_usage trước đây).
"""
from alembic import op
import sqlalchemy as sa

revision = 'd4e5f6a7b8c9'
down_revision = 'c3d4e5f6a7b8'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'filter_material_usage',
        sa.Column('usage_id', sa.Unicode(length=64), nullable=False),
        sa.Column('filter_id', sa.Unicode(length=64), sa.ForeignKey('filter_record.filter_id'), nullable=False),
        sa.Column('receipt_id', sa.Unicode(length=64), sa.ForeignKey('material_receipt.receipt_id'), nullable=True),
        sa.Column('lot_id', sa.Unicode(length=64), sa.ForeignKey('material_lot.lot_id'), nullable=True),
        sa.Column('movement_id', sa.Unicode(length=64), sa.ForeignKey('stock_movement.movement_id'), nullable=True),
        sa.Column('material_name', sa.Unicode(length=255), nullable=False),
        sa.Column('lot_pm', sa.Unicode(length=255), nullable=True),
        sa.Column('quantity', sa.Float(), nullable=False, server_default='0'),
        sa.Column('uom', sa.Unicode(length=255), nullable=False, server_default='kg'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('usage_id'),
    )
    op.create_index('ix_filter_material_usage_filter_id', 'filter_material_usage', ['filter_id'])
    op.create_index('ix_filter_material_usage_lot_id', 'filter_material_usage', ['lot_id'])


def downgrade() -> None:
    op.drop_table('filter_material_usage')
