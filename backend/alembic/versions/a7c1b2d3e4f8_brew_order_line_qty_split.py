"""Lệnh nấu: tách SL thực xuất theo 2 nguồn (Kho công ty / Kho phân xưởng)

Them 2 cot brew_order_material_line.qty_from_company / qty_from_workshop -- gia tri GOI Y (uu
tien dung het ton dang co tai Kho phan xuong, phan con thieu lay tai Kho cong ty), nguoi lap
lenh nau co the sua lai truoc khi luu. Xem services/brew_order.py::_suggest_qty_split.

Revision ID: a1b2c3d4e5f7
Revises: f6a7b8c9d3e4
Create Date: 2026-08-15
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "a7c1b2d3e4f8"
down_revision = "f6a7b8c9d3e4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("brew_order_material_line") as batch_op:
        batch_op.add_column(sa.Column("qty_from_company", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("qty_from_workshop", sa.Float(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("brew_order_material_line") as batch_op:
        batch_op.drop_column("qty_from_workshop")
        batch_op.drop_column("qty_from_company")
