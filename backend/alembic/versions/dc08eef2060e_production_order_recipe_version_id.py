"""production order recipe version id

Revision ID: dc08eef2060e
Revises: 820cf3ff8be3
Create Date: 2026-08-20 07:36:56.344476

- production_order.recipe_version_id (nullable FK -> recipe_version.version_id): Công thức
  (BOM) người lập Lệnh SX (ERP) CHỌN, mirror brew_order.recipe_version_id — dùng để tính trước
  định mức NVL (xem services/orders.py::preview_bom / build_lines_from_recipe_version).
- production_order.planned_batch_count (nullable Integer): số mẻ kế hoạch để chia định mức
  NVL/mẻ — thuần thông tin kế hoạch, KHÔNG phải nguồn sự thật cho sản lượng (đó vẫn là
  planned_qty/uom sẵn có).
"""
from alembic import op
import sqlalchemy as sa


revision = 'dc08eef2060e'
down_revision = '820cf3ff8be3'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("production_order", sa.Column("recipe_version_id", sa.Unicode(64), nullable=True))
    op.add_column("production_order", sa.Column("planned_batch_count", sa.Integer(), nullable=True))
    op.create_index("ix_production_order_recipe_version_id", "production_order", ["recipe_version_id"])


def downgrade() -> None:
    op.drop_index("ix_production_order_recipe_version_id", table_name="production_order")
    op.drop_column("production_order", "planned_batch_count")
    op.drop_column("production_order", "recipe_version_id")
