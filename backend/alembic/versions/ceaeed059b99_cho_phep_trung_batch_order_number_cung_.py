"""cho phep trung batch order number cung lenh loc

Revision ID: ceaeed059b99
Revises: 4ae215c30cfb
Create Date: 2026-07-28 07:55:29.955979

1 lệnh lọc nhỏ có thể tách 1 mẻ vào nhiều tank BBT (tank bé) — các FilterRecord của CÙNG
filter_order_id nay được phép trùng batch_number/order_number (cùng 1 mẻ thật, chỉ khác tank
chứa). Chỉ số UNIQUE ở DB trước đây (ix_filter_record_batch_number/order_number) chặn luôn cả
trường hợp hợp lệ này — đổi thành index thường, chuyển việc chặn trùng SANG lệnh lọc KHÁC hẳn
lên tầng ứng dụng (xem routers/brewing.py::finish_filter_tank).
"""
from alembic import op
import sqlalchemy as sa


revision = 'ceaeed059b99'
down_revision = '4ae215c30cfb'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_index('ix_filter_record_batch_number', table_name='filter_record')
    op.drop_index('ix_filter_record_order_number', table_name='filter_record')
    op.create_index('ix_filter_record_batch_number', 'filter_record', ['batch_number'], unique=False)
    op.create_index('ix_filter_record_order_number', 'filter_record', ['order_number'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_filter_record_order_number', table_name='filter_record')
    op.drop_index('ix_filter_record_batch_number', table_name='filter_record')
    op.create_index('ix_filter_record_batch_number', 'filter_record', ['batch_number'], unique=True)
    op.create_index('ix_filter_record_order_number', 'filter_record', ['order_number'], unique=True)
