"""Chỉ tiêu chất lượng: thêm value_type (numeric|pass_fail)

Revision ID: c9d0e1f2a3b5
Revises: b6c7d8e9f0a2
Create Date: 2026-07-21

- Thêm cột value_type cho qc_parameter (mặc định "numeric") — cho phép khai báo 1 chỉ tiêu
  chỉ ghi nhận Đạt/Không đạt thay vì nhập số. Quy ước khi lưu kết quả pass_fail: value=1,
  lower_limit=1, upper_limit=1 là Đạt; value=0, lower_limit=1, upper_limit=1 là Không đạt —
  tái dùng nguyên vẹn hàm đánh giá numeric hiện có, không đổi logic đánh giá.
"""
from alembic import op
import sqlalchemy as sa

revision = 'c9d0e1f2a3b5'
down_revision = 'b6c7d8e9f0a2'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('qc_parameter', sa.Column('value_type', sa.Unicode(16),
                                            nullable=False, server_default='numeric'))


def downgrade() -> None:
    op.drop_column('qc_parameter', 'value_type')
