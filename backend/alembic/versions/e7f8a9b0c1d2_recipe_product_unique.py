"""Recipe.product_id unique (1 dịch bia = đúng 1 công thức)

Revision ID: e7f8a9b0c1d2
Revises: d6e7f8a9b0c1
Create Date: 2026-07-16

- recipe.product_id: thêm unique index — trước đây không có ràng buộc nên có thể tạo
  nhiều Recipe cho cùng 1 dịch bia, khiến services/brew_order.py::_effective_bom()
  chọn nhầm recipe (không có version nào "effective") thay vì recipe thật đang dùng,
  làm Lệnh nấu không tự nạp được định mức NVL từ Công thức.
"""
from alembic import op
import sqlalchemy as sa

revision = 'e7f8a9b0c1d2'
down_revision = 'd6e7f8a9b0c1'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(op.f('ix_recipe_product_id_unique'), 'recipe', ['product_id'], unique=True)


def downgrade() -> None:
    op.drop_index(op.f('ix_recipe_product_id_unique'), table_name='recipe')
