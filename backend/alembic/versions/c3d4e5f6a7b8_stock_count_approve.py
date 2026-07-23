"""Kiểm kê định kỳ: thêm Duyệt (giám đốc nhà máy trở lên) sau khi chốt

Revision ID: c3d4e5f6a7b8
Revises: 89f74fef30e3
Create Date: 2026-07-22

- stock_count.approved_by / approved_at (nullable): duyệt CHỈ áp dụng sau khi đã chốt (post),
  chỉ để xác nhận đã xem/đồng ý — không đổi lại số liệu tồn kho. Một khi đã duyệt thì khóa
  hẳn, không cho hoàn tác nữa (xem services/warehouse.py::approve_count/undo_count).
"""
from alembic import op
import sqlalchemy as sa

revision = 'c3d4e5f6a7b8'
down_revision = '89f74fef30e3'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('stock_count', sa.Column('approved_by', sa.Unicode(length=255), nullable=True))
    op.add_column('stock_count', sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column('stock_count', 'approved_at')
    op.drop_column('stock_count', 'approved_by')
