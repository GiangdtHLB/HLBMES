"""Lệnh nấu: chọn công thức (formula_id) khi lập lệnh nhỏ

Revision ID: a0613c8733c2
Revises: d4e6f8a0b2c9
Create Date: 2026-08-12

- brew_order.formula_id (nullable FK -> formula.formula_id): công thức (BOM) người lập lệnh
  CHỌN dùng cho lệnh nhỏ này — nhiều công thức/dịch bia có thể cùng hiệu lực đồng thời
  (xem services/formula.py::activate_formula), không còn tự suy ra "công thức hiệu lực duy
  nhất" như trước. Nullable vì lệnh cũ trước field này không cần backfill (BOM đã snapshot
  cứng trong brew_order_material_line).
"""
from alembic import op
import sqlalchemy as sa

revision = 'a0613c8733c2'
down_revision = 'd4e6f8a0b2c9'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("brew_order", sa.Column("formula_id", sa.Unicode(64), nullable=True))
    op.create_index("ix_brew_order_formula_id", "brew_order", ["formula_id"])


def downgrade() -> None:
    op.drop_index("ix_brew_order_formula_id", table_name="brew_order")
    op.drop_column("brew_order", "formula_id")
