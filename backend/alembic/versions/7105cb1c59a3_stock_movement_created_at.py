"""StockMovement: thêm created_at (ngày tạo phiếu thật, tách khỏi ts)

Revision ID: 7105cb1c59a3
Revises: b47e1a06c8d4
Create Date: 2026-09-07

- stock_movement: thêm created_at (nullable) — ngày THẬT sự tạo bản ghi (audit, luôn utcnow()
  lúc tạo, xem services/warehouse.py::_move()), tách biệt với `ts` (ngày HIỆU LỰC của giao dịch,
  có thể khai lùi — "Nhập tồn đầu"/"Ngày xuất tự do"). Backfill giao dịch cũ bằng chính `ts` của
  nó (không có cách khôi phục ngày tạo thật cho dữ liệu cũ, coi `ts` cũ là xấp xỉ tốt nhất).
"""
from alembic import op
import sqlalchemy as sa

revision = '7105cb1c59a3'
down_revision = 'b47e1a06c8d4'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('stock_movement', recreate='auto') as batch_op:
        batch_op.add_column(sa.Column('created_at', sa.DateTime(timezone=True), nullable=True))
    op.execute(sa.text('UPDATE stock_movement SET created_at = ts WHERE created_at IS NULL'))


def downgrade() -> None:
    with op.batch_alter_table('stock_movement', recreate='auto') as batch_op:
        batch_op.drop_column('created_at')
