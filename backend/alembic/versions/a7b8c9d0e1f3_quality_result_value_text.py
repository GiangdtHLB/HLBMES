"""QualityResult: thêm value_text (chỉ tiêu kiểu "text")

Revision ID: a7b8c9d0e1f3
Revises: d8f3a1c2b4e6
Create Date: 2026-08-07

- Thêm cột value_text cho quality_result — dùng khi QCParameter.value_type == "text": ghi chú
  tự do do người vận hành nhập, không so target/USL/LSL, không tính pass/fail (khác numeric/
  pass_fail hiện có). NULL ở mọi chỉ tiêu số/đạt-không đạt.
"""
from alembic import op
import sqlalchemy as sa

revision = 'a7b8c9d0e1f3'
down_revision = 'd8f3a1c2b4e6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('quality_result', sa.Column('value_text', sa.Unicode(1000), nullable=True))


def downgrade() -> None:
    op.drop_column('quality_result', 'value_text')
