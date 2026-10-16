"""ops_setting: ngưỡng số phút nấu chuẩn tối đa (mẻ nấu) để cảnh báo (không chặn) khi vượt

Revision ID: 9b4c3e2a1d7f
Revises: c39d10057e93
Create Date: 2026-10-16

- ops_setting.max_brewing_minutes: số PHÚT nấu chuẩn tối đa (từ "Bắt đầu" tới "Kết thúc" mẻ
  nấu) — vượt ngưỡng này KHÔNG chặn ghi, chỉ hiện ghi chú cảnh báo (yêu cầu người dùng
  2026-10-16). Mặc định 480 phút (8 giờ 00).
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "9b4c3e2a1d7f"
down_revision = "c39d10057e93"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("ops_setting", sa.Column("max_brewing_minutes", sa.Integer(),
                                           nullable=False, server_default="480"))


def downgrade():
    op.drop_column("ops_setting", "max_brewing_minutes")
