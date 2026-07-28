"""them batch_number order_number vao filter_record

Revision ID: 4ae215c30cfb
Revises: 1c51cd465435
Create Date: 2026-07-28 00:19:28.430538

Số mẻ (batch_number)/số lệnh (order_number) do vận hành tự gõ tay khi bấm "Kết thúc" mẻ
lọc — khớp phiếu giấy thực tế, duy nhất trong toàn bộ mẻ lọc. Đi kèm thay đổi chính sách
chia sẻ tank BBT: nhiều Lệnh lọc khác nhau được phép cùng đổ vào 1 tank vật lý (thể tích
cộng dồn) miễn tank chưa được KCS duyệt — xem services/filter_order.py::_bbt_target_blocked_by.
"""
from alembic import op
import sqlalchemy as sa


revision = '4ae215c30cfb'
down_revision = '1c51cd465435'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('filter_record', sa.Column('batch_number', sa.Unicode(255), nullable=True))
    op.add_column('filter_record', sa.Column('order_number', sa.Unicode(255), nullable=True))
    op.create_index('ix_filter_record_batch_number', 'filter_record', ['batch_number'], unique=True)
    op.create_index('ix_filter_record_order_number', 'filter_record', ['order_number'], unique=True)


def downgrade() -> None:
    op.drop_index('ix_filter_record_order_number', table_name='filter_record')
    op.drop_index('ix_filter_record_batch_number', table_name='filter_record')
    op.drop_column('filter_record', 'order_number')
    op.drop_column('filter_record', 'batch_number')
