"""them batch_seq_no vao filter_order_tank

Revision ID: 23db474e3e99
Revises: ceaeed059b99
Create Date: 2026-07-28 22:07:36.599704

"Mẻ lọc số" — vận hành tự gõ tay lúc "Kết thúc" mỗi dòng rút dịch (FilterOrderTank), KHÁC
với batch_number/order_number của FilterRecord (khớp phiếu giấy, duy nhất toàn hệ thống) —
số này CHO PHÉP TRÙNG giữa các mẻ lọc/lệnh lọc khác nhau nên không tạo unique index.
"""
from alembic import op
import sqlalchemy as sa


revision = '23db474e3e99'
down_revision = 'ceaeed059b99'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('filter_order_tank', sa.Column('batch_seq_no', sa.Unicode(64), nullable=True))


def downgrade() -> None:
    op.drop_column('filter_order_tank', 'batch_seq_no')
