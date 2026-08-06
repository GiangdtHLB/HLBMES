"""Vật tư: thêm đơn vị phụ + tỷ lệ quy đổi (VD 1 Lon = 2 kg)

Revision ID: b624e7bc6d4d
Revises: 9a0b1c2d3e4f
Create Date: 2026-08-05

- material.alt_uom (nullable): đơn vị phụ, VD "kg" cho vật tư có uom chính là "Lon".
- material.alt_uom_ratio (nullable): 1 uom chính = alt_uom_ratio đơn vị phụ (VD 2 nghĩa là
  1 Lon = 2kg). Chỉ dùng để cho phép nhập/xuất theo đơn vị phụ ở 1 số màn hình (frontend tự
  quy đổi về uom chính trước khi gọi API) — không đổi cách lưu trữ/tính tồn kho.
"""
from alembic import op
import sqlalchemy as sa

revision = 'b624e7bc6d4d'
down_revision = '9a0b1c2d3e4f'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('material', sa.Column('alt_uom', sa.Unicode(length=64), nullable=True))
    op.add_column('material', sa.Column('alt_uom_ratio', sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column('material', 'alt_uom_ratio')
    op.drop_column('material', 'alt_uom')
