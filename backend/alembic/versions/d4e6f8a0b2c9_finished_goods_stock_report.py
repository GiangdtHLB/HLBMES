"""Báo cáo NXT kho thành phẩm: 2 field kế hoạch/SKU + ngưỡng đề xuất đóng bổ sung

Revision ID: d4e6f8a0b2c9
Revises: c4e6a8b0d2f5
Create Date: 2026-08-12

- finished_product.planned_packaging_date (Date, nullable): Kế hoạch đóng bia.
- finished_product.planned_production_qty (Float, nullable): Lượng SX dự kiến.
- ops_setting.finished_goods_restock_days (Float, default 7.0): ngưỡng số ngày tồn dự kiến để
  đề xuất "Đóng bổ sung" trên báo cáo trên — áp dụng chung mọi SKU.

(Tồn mục tiêu tháng đã chuyển sang bảng riêng finished_product_monthly_plan — xem migration
10b08a0df0d2_finished_product_monthly_plan.py — nên không còn field monthly_target_stock ở đây.)

(Revision id đổi từ a1b2c3d4e5f6 sang d4e6f8a0b2c9 — id cũ trùng với migration
a1b2c3d4e5f6_jobs.py đã có sẵn từ trước (bảng job hàng đợi AI), gây collision revision id.)
"""
from alembic import op
import sqlalchemy as sa

revision = 'd4e6f8a0b2c9'
down_revision = 'c4e6a8b0d2f5'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("finished_product", sa.Column("planned_packaging_date", sa.Date(), nullable=True))
    op.add_column("finished_product", sa.Column("planned_production_qty", sa.Float(), nullable=True))
    op.add_column("ops_setting", sa.Column(
        "finished_goods_restock_days", sa.Float(), nullable=False, server_default="7.0"))


def downgrade() -> None:
    op.drop_column("ops_setting", "finished_goods_restock_days")
    op.drop_column("finished_product", "planned_production_qty")
    op.drop_column("finished_product", "planned_packaging_date")
