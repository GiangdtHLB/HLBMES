"""batch_filter_order_completed

Revision ID: b3f8c1d97a02
Revises: a7d4e29f6c51
Create Date: 2026-09-23 00:00:00.000000

Thêm completed/completed_by/completed_at vào batch_filter_order — mốc "Hoàn thành lệnh lọc"
xác nhận riêng của vận hành (mirror batch_pack_lot_finished a7d4e29f6c51 — "Hoàn thành chiết"),
TÁCH BIỆT khỏi việc từng Lô lọc (BatchFilterLot) con tự "Hoàn thành lọc" của riêng nó. Đặt tên
`completed` (không phải `finished`) để không trùng nghĩa với cột finished_product_id (FK) đã có
sẵn trên bảng này.
"""
from alembic import op
import sqlalchemy as sa


revision = 'b3f8c1d97a02'
down_revision = 'a7d4e29f6c51'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('batch_filter_order', sa.Column('completed', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column('batch_filter_order', sa.Column('completed_by', sa.Unicode(length=255), nullable=True))
    op.add_column('batch_filter_order', sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column('batch_filter_order', 'completed_at')
    op.drop_column('batch_filter_order', 'completed_by')
    op.drop_column('batch_filter_order', 'completed')
