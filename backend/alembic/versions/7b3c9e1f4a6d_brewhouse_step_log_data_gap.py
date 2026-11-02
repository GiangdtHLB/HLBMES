"""brewhouse_step_log_data_gap (danh dau dong log bi dong sau gian doan ghi bat thuong)

Revision ID: 7b3c9e1f4a6d
Revises: 48d7f493c7dd
Create Date: 2026-11-02

Them cot data_gap — xem models/brewhouse_log.py + services/brewhouse_log.py::GAP_THRESHOLD_SECONDS.
Sua su co 2026-11-02: tac vu ghi log chet am tham 2+ tieng, khi tu khoi dong lai se dong cac dong
dang mo voi duration_minutes SAI (tinh ca khoang gian doan) - can co de danh dau loai khoi bao cao.
"""
from alembic import op
import sqlalchemy as sa

from app.alembic_mssql import prep_drop_columns

revision = "7b3c9e1f4a6d"
down_revision = "48d7f493c7dd"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "brewhouse_step_log",
        sa.Column("data_gap", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    # server_default sinh ra 1 ràng buộc DEFAULT ĐƯỢC ĐẶT TÊN TỰ ĐỘNG trên MSSQL; drop_column
    # trần sẽ lỗi vì ràng buộc đó còn bám vào cột. prep_drop_columns() tra tên thật rồi gỡ trước
    # (DEPLOY-CONTRACT §2(B)). SQLite dựng lại bảng nên không cần, vì vậy bỏ sót không lộ khi
    # test trên SQLite — chỉ vỡ đúng lúc cần lùi, tức lúc đang có sự cố.
    prep_drop_columns(op.get_bind(), "brewhouse_step_log", ["data_gap"])
    op.drop_column("brewhouse_step_log", "data_gap")
