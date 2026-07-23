"""FIFO snapshot cho NVL mẻ nấu/mẻ lọc + NVL mẻ chiết mới

Revision ID: d7e8f9a1b2c4
Revises: c6d7e8f9a1b3
Create Date: 2026-07-21

- brew_material_usage/filter_material_usage: thêm lot_date (ngày nhập của lô đã dùng) và
  fifo_ok (lô đã chọn có phải lô cũ nhất/FIFO tại Kho phân xưởng lúc gán hay không) — snapshot
  ngay lúc gán, xem services/warehouse.py::is_oldest_workshop_lot.
- bottle_material_usage: bảng mới — NVL dùng thật cho mẻ chiết (VD CO2, hóa chất vệ sinh),
  mirror filter_material_usage; Chiết trước đây không tiêu thụ NVL.
"""
from alembic import op
import sqlalchemy as sa

revision = 'd7e8f9a1b2c4'
down_revision = 'c6d7e8f9a1b3'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('brew_material_usage', sa.Column('lot_date', sa.DateTime(timezone=True), nullable=True))
    op.add_column('brew_material_usage', sa.Column('fifo_ok', sa.Boolean(), nullable=True))
    op.add_column('filter_material_usage', sa.Column('lot_date', sa.DateTime(timezone=True), nullable=True))
    op.add_column('filter_material_usage', sa.Column('fifo_ok', sa.Boolean(), nullable=True))

    op.create_table(
        'bottle_material_usage',
        sa.Column('usage_id', sa.Unicode(length=64), primary_key=True),
        sa.Column('bottle_id', sa.Unicode(length=64), sa.ForeignKey('bottle_record.bottle_id'), nullable=False),
        sa.Column('lot_id', sa.Unicode(length=64), sa.ForeignKey('material_lot.lot_id'), nullable=True),
        sa.Column('movement_id', sa.Unicode(length=64), sa.ForeignKey('stock_movement.movement_id'), nullable=True),
        sa.Column('material_name', sa.Unicode(length=255), nullable=False),
        sa.Column('lot_pm', sa.Unicode(length=255), nullable=True),
        sa.Column('lot_date', sa.DateTime(timezone=True), nullable=True),
        sa.Column('fifo_ok', sa.Boolean(), nullable=True),
        sa.Column('quantity', sa.Float(), nullable=False),
        sa.Column('uom', sa.Unicode(length=255), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_bottle_material_usage_bottle_id', 'bottle_material_usage', ['bottle_id'])
    op.create_index('ix_bottle_material_usage_lot_id', 'bottle_material_usage', ['lot_id'])


def downgrade() -> None:
    op.drop_index('ix_bottle_material_usage_lot_id', table_name='bottle_material_usage')
    op.drop_index('ix_bottle_material_usage_bottle_id', table_name='bottle_material_usage')
    op.drop_table('bottle_material_usage')
    op.drop_column('filter_material_usage', 'fifo_ok')
    op.drop_column('filter_material_usage', 'lot_date')
    op.drop_column('brew_material_usage', 'fifo_ok')
    op.drop_column('brew_material_usage', 'lot_date')
