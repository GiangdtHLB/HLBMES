"""Lệnh lọc hỗ trợ Nhóm vật tư thay thế trong dòng vật tư sử dụng

Revision ID: 6f7a8b9c0d1e
Revises: 585b9bb8e072
Create Date: 2026-08-01

- filter_order_material_line: material_id nới sang nullable (SQLite cần rebuild bảng qua
  batch_alter_table) + thêm material_group_code (mã Nhóm vật tư thay thế — xem
  models/master.py::MaterialAltGroup) — cho phép 1 dòng vật tư dùng cho Lệnh lọc khai theo
  nhóm thay vì 1 material_id cụ thể, mirror brew_order_material_line.material_group_code.
Không backfill dữ liệu.
"""
from alembic import op
import sqlalchemy as sa

revision = '6f7a8b9c0d1e'
down_revision = '585b9bb8e072'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('filter_order_material_line', recreate='auto') as batch_op:
        batch_op.alter_column('material_id', existing_type=sa.Unicode(64), nullable=True)
        batch_op.add_column(sa.Column('material_group_code', sa.Unicode(64), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('filter_order_material_line', recreate='auto') as batch_op:
        batch_op.drop_column('material_group_code')
        batch_op.alter_column('material_id', existing_type=sa.Unicode(64), nullable=False)
