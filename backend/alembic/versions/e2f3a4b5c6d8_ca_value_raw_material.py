"""Giá trị CA (bao bì NCC) cho chỉ tiêu chất lượng NVL + cờ nhóm nguyên liệu

Revision ID: e2f3a4b5c6d8
Revises: d1e2f3a4b5c7
Create Date: 2026-07-26

- Thêm material_group.is_raw_material (mặc định False, mirror is_packaging) — nhóm được
  đánh dấu cờ này (VD "Nguyên liệu chính", "Nguyên liệu phụ") sẽ khiến modal khai báo chỉ
  tiêu chất lượng NVL (openLotQcModal) hiện thêm cột "Giá trị CA".
- Thêm quality_result.ca_value (nullable) — giá trị in trên bao bì/CA của nhà cung cấp, khác
  `value` (nhà máy tự đo); chỉ tham khảo/báo cáo, KHÔNG dùng để tính pass/fail.
"""
from alembic import op
import sqlalchemy as sa

revision = 'e2f3a4b5c6d8'
down_revision = 'd1e2f3a4b5c7'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('material_group', sa.Column('is_raw_material', sa.Boolean(),
                                              nullable=False, server_default=sa.false()))
    op.add_column('quality_result', sa.Column('ca_value', sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column('quality_result', 'ca_value')
    op.drop_column('material_group', 'is_raw_material')
