"""Kiểm kê định kỳ: thêm ngày bắt đầu/kết thúc kỳ kiểm kê

Revision ID: f4a5b6c7d8e0
Revises: d3e4f5a6b7c9
Create Date: 2026-08-02

- stock_count: thêm start_date/end_date (kỳ kiểm kê thực tế khai báo tay, khác created_at/
  posted_at vốn là mốc thao tác trên hệ thống — xem services/warehouse.py::create_count).
"""
from alembic import op
import sqlalchemy as sa

revision = 'f4a5b6c7d8e0'
down_revision = 'd3e4f5a6b7c9'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('stock_count', recreate='auto') as batch_op:
        batch_op.add_column(sa.Column('start_date', sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column('end_date', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('stock_count', recreate='auto') as batch_op:
        batch_op.drop_column('end_date')
        batch_op.drop_column('start_date')
