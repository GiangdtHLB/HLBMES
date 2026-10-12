"""ops_setting_session_hours

ops_setting.session_hours — thời hạn phiên đăng nhập (giờ), cấu hình được ở Cài đặt vận hành
thay vì chỉ đọc biến môi trường MES_SESSION_HOURS (yêu cầu người dùng 2026-10-12: "cho tôi cài
trong cài đặt được không, sẽ cài thời gian đăng nhập"). server_default = config.SESSION_HOURS
hiện tại (giá trị đang thật sự áp dụng trước migration này) — backfill đúng cho dòng ops_setting
đã có sẵn, không đổi hành vi ngay lúc deploy.

Revision ID: e5f7a9b2c4d6
Revises: d2e4f6a8b1c3
Create Date: 2026-10-12 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

from app.config import SESSION_HOURS

revision = 'e5f7a9b2c4d6'
down_revision = 'd2e4f6a8b1c3'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('ops_setting') as batch_op:
        batch_op.add_column(sa.Column('session_hours', sa.Integer(), nullable=False,
                                      server_default=str(SESSION_HOURS)))


def downgrade() -> None:
    with op.batch_alter_table('ops_setting') as batch_op:
        batch_op.drop_column('session_hours')
