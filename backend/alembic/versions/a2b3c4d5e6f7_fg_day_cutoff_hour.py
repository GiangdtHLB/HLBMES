"""Ops setting: gio cat "ngay van hanh" cho bao cao NXT kho thanh pham theo ngay

Them cot ops_setting.fg_day_cutoff_hour (0-23, gio VN) -- 1 "ngay" = tu gio nay hom truoc den
dung gio nay hom sau, khong co dinh 00h-24h (khop thuc te ca dem 22h-06h khong bi cat doi giua
2 ngay lich). Xem services/wms.py::finished_goods_daily_stock_report.

Revision ID: a2b3c4d5e6f7
Revises: f6a7b8c9d3e4
Create Date: 2026-08-16
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "a2b3c4d5e6f7"
down_revision = "f6a7b8c9d3e4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("ops_setting") as batch_op:
        batch_op.add_column(sa.Column("fg_day_cutoff_hour", sa.Integer(), nullable=False, server_default="0"))


def downgrade() -> None:
    with op.batch_alter_table("ops_setting") as batch_op:
        batch_op.drop_column("fg_day_cutoff_hour")
