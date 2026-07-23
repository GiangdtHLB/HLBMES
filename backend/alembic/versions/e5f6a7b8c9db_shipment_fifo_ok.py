"""Ghi lại phiếu xuất kho có tuân đúng FIFO không

Revision ID: e5f6a7b8c9db
Revises: d4e5f6a7b8ca
Create Date: 2026-07-15

- shipment.fifo_ok: tính lúc tạo phiếu — có pallet cùng sản phẩm cũ hơn còn dư chưa lấy
  hết trước khi lấy tới pallet mới hơn không, để hiện rõ ở Lịch sử xuất kho.
"""
from alembic import op
import sqlalchemy as sa

revision = 'e5f6a7b8c9db'
down_revision = 'd4e5f6a7b8ca'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('shipment', sa.Column('fifo_ok', sa.Boolean(), nullable=False, server_default=sa.true()))


def downgrade() -> None:
    op.drop_column('shipment', 'fifo_ok')
