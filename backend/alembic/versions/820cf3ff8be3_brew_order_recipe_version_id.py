"""brew order recipe version id

Revision ID: 820cf3ff8be3
Revises: fdf26676925d
Create Date: 2026-08-19 18:12:36.599940

- brew_order.recipe_version_id (nullable FK -> recipe_version.version_id): công thức (BOM)
  người lập lệnh CHỌN dùng cho lệnh nhỏ này, nay nạp từ RecipeVersion (đưa màn "Công thức" về
  lại hệ Recipe/RecipeVersion gốc, thay Formula — xem services/brew_order.py). Giữ nguyên cột
  formula_id cũ (không xóa, không còn code nào đọc/ghi) để tránh đổi schema không cần thiết
  trên MSSQL.
"""
from alembic import op
import sqlalchemy as sa


revision = '820cf3ff8be3'
down_revision = 'fdf26676925d'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("brew_order", sa.Column("recipe_version_id", sa.Unicode(64), nullable=True))
    op.create_index("ix_brew_order_recipe_version_id", "brew_order", ["recipe_version_id"])


def downgrade() -> None:
    op.drop_index("ix_brew_order_recipe_version_id", table_name="brew_order")
    op.drop_column("brew_order", "recipe_version_id")
