"""brew_process_log: thêm braumat_batch_number (Batch Number thật từ Braumat)

Revision ID: d8e9f0a1b2c4
Revises: c7d8e9f0a1b3
Create Date: 2026-07-20

- brew_process_log.braumat_batch_number: Batch Number đọc được từ file Step Protocol PDF lúc
  import (services/braumat_import.py::import_step_protocols) — trước đây chỉ dùng tạm để so
  sánh với batch_code rồi bỏ, nay lưu lại để hiển thị ở Ghi chép lên men (Ghi chép lên men
  gộp braumat_order_number/braumat_batch_number của mọi mẻ nguồn — xem
  services/ferment_log.py::_braumat_fields_for_ferment).
"""
from alembic import op
import sqlalchemy as sa

revision = 'd8e9f0a1b2c4'
down_revision = 'c7d8e9f0a1b3'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('brew_process_log', sa.Column('braumat_batch_number', sa.Unicode(length=64), nullable=True))


def downgrade() -> None:
    op.drop_column('brew_process_log', 'braumat_batch_number')
