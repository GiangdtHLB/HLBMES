"""dispense_line_fifo_reason

Revision ID: 9a4d2e6c1f8b
Revises: 7c3e1a9f5d2b
Create Date: 2026-08-31 00:00:00.000000

Cho phép chọn lô KHÁC lô FIFO/FEFO gợi ý khi cấp liệu (bắt buộc nêu lý do) — thêm 2 cột trên
dispense_line: fifo_ok (có phải lô FIFO/FEFO đúng thứ tự không) + reason (lý do khi chọn lệch).
"""
from alembic import op
import sqlalchemy as sa


revision = '9a4d2e6c1f8b'
down_revision = '7c3e1a9f5d2b'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('dispense_line', sa.Column('fifo_ok', sa.Boolean(), nullable=False, server_default=sa.true()))
    op.add_column('dispense_line', sa.Column('reason', sa.UnicodeText(), nullable=True))


def downgrade() -> None:
    op.drop_column('dispense_line', 'reason')
    op.drop_column('dispense_line', 'fifo_ok')
