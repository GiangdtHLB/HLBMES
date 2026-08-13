"""FinishedProduct: bỏ 2 field kế hoạch cũ (planned_packaging_date/planned_production_qty);
finished_product_monthly_plan: thêm cột lượng sản xuất dự kiến theo tháng

Revision ID: 8b2c3d4e5f6a
Revises: 7a1b2c3d4e5f
Create Date: 2026-08-13

- "Lượng SX dự kiến" chuyển từ 1 field thủ công trên FinishedProduct (sửa trực tiếp trên báo
  cáo NXT kho thành phẩm) sang khai báo theo THÁNG trong finished_product_monthly_plan, cùng
  bảng với initial_qty/adjusted_qty (Tồn mục tiêu tháng) — xem
  routers/master.py::update_monthly_plan.
- "Kế hoạch đóng bia" (planned_packaging_date) bị bỏ hẳn, không có field thay thế.
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "8b2c3d4e5f6a"
down_revision = "7a1b2c3d4e5f"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("finished_product_monthly_plan", sa.Column("expected_production_qty", sa.Float(), nullable=True))
    op.drop_column("finished_product", "planned_packaging_date")
    op.drop_column("finished_product", "planned_production_qty")


def downgrade():
    op.add_column("finished_product", sa.Column("planned_production_qty", sa.Float(), nullable=True))
    op.add_column("finished_product", sa.Column("planned_packaging_date", sa.Date(), nullable=True))
    op.drop_column("finished_product_monthly_plan", "expected_production_qty")
