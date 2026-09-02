"""batch_filter_order_kcs_lot_no

Revision ID: 6d89185e734f
Revises: 6da99eba6a92
Create Date: 2026-08-31 00:00:00.000000

Thêm "Số lô KCS" (kcs_lot_no) vào batch_filter_order — mirror FilterOrder.kcs_lot_no (module
Nấu-Lọc-Chiết cũ), để đồng bộ hiển thị với màn "Lệnh lọc" hiện có (2 bảng vẫn tách riêng).
"""
from alembic import op
import sqlalchemy as sa


revision = '6d89185e734f'
down_revision = '6da99eba6a92'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('batch_filter_order', sa.Column('kcs_lot_no', sa.Unicode(length=255), nullable=True))


def downgrade() -> None:
    op.drop_column('batch_filter_order', 'kcs_lot_no')
