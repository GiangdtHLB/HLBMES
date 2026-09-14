"""Lệnh lọc (pipeline Mẻ sản xuất mới) — thêm dòng vật tư dự kiến khai báo lúc lập lệnh

Revision ID: a1b2c3d4e5fa
Revises: 3d58c9a80d40
Create Date: 2026-09-13

- batch_filter_order_material_line: 1 dòng vật tư dự kiến (bột trợ lọc/diatomite...) khai báo
  NGAY LÚC LẬP Lệnh lọc (BatchFilterOrder, pipeline mới) — mirror filter_order_material_line
  (module cũ) nhưng ĐƠN GIẢN HƠN: không tách qty_from_company/qty_from_workshop vì không có
  bước chọn FIFO lúc lập lệnh (FIFO do vận hành tự chọn khi ghi NGUYÊN LIỆU LỌC thật ở Lô lọc —
  xem services/batch_pipeline.py::add_filter_lot_material, không đổi). Dùng để chặn thiếu tồn
  lúc lập lệnh + làm gợi ý khi ghi nguyên liệu thật.
"""
from alembic import op
import sqlalchemy as sa

revision = 'a1b2c3d4e5fa'
down_revision = '3d58c9a80d40'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'batch_filter_order_material_line',
        sa.Column('line_id', sa.Unicode(length=64), nullable=False),
        sa.Column('order_id', sa.Unicode(length=64), nullable=False),
        sa.Column('seq', sa.Integer(), nullable=False),
        sa.Column('material_id', sa.Unicode(length=64), nullable=True),
        sa.Column('material_name', sa.Unicode(length=255), nullable=True),
        sa.Column('uom', sa.Unicode(length=64), nullable=True),
        sa.Column('qty_planned', sa.Float(), nullable=False),
        sa.Column('stock_company_snapshot', sa.Float(), nullable=True),
        sa.Column('stock_workshop_snapshot', sa.Float(), nullable=True),
        sa.ForeignKeyConstraint(['order_id'], ['batch_filter_order.order_id']),
        sa.ForeignKeyConstraint(['material_id'], ['material.material_id']),
        sa.PrimaryKeyConstraint('line_id'),
    )
    op.create_index(op.f('ix_batch_filter_order_material_line_order_id'),
                     'batch_filter_order_material_line', ['order_id'])


def downgrade() -> None:
    op.drop_index(op.f('ix_batch_filter_order_material_line_order_id'),
                   table_name='batch_filter_order_material_line')
    op.drop_table('batch_filter_order_material_line')
