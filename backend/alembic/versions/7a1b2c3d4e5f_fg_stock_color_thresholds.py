"""ops_setting: 2 ngưỡng màu cho báo cáo NXT kho thành phẩm (Số ngày tồn dự kiến/Số ngày lưu kho)

Revision ID: 7a1b2c3d4e5f
Revises: 10b08a0df0d2
Create Date: 2026-08-13

- ops_setting.fg_days_of_stock_critical_days: ngưỡng Đỏ cho "Số ngày tồn dự kiến" — dưới ngưỡng
  này là Đỏ, dưới finished_goods_restock_days (đã có) là Vàng, còn lại Xanh.
- ops_setting.fg_days_in_stock_warning_days: ngưỡng Vàng cho "Số ngày lưu kho" — trên ngưỡng
  này là Vàng, còn lại (hoặc chưa từng sản xuất) là Xanh/—.
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "7a1b2c3d4e5f"
down_revision = "10b08a0df0d2"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("ops_setting", sa.Column("fg_days_of_stock_critical_days", sa.Float(),
                                            nullable=False, server_default="3.0"))
    op.add_column("ops_setting", sa.Column("fg_days_in_stock_warning_days", sa.Float(),
                                            nullable=False, server_default="30.0"))


def downgrade():
    op.drop_column("ops_setting", "fg_days_in_stock_warning_days")
    op.drop_column("ops_setting", "fg_days_of_stock_critical_days")
