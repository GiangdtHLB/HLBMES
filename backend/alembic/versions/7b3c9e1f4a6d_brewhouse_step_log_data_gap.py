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
    op.drop_column("brewhouse_step_log", "data_gap")
