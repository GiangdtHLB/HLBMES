"""material alt group selection mode and brew order member qty snapshot

Revision ID: 8a09fb60a835
Revises: dc08eef2060e
Create Date: 2026-08-20 15:05:04.784084

- material_alt_group.selection_mode (Unicode, default "single"): "single" = chọn đúng 1 thành
  viên khi ghi NVL (hành vi gốc), "multi" = được ghi nhận nhiều thành viên cùng lúc cho 1 mẻ.
  server_default='single' để mọi nhóm đã có sẵn tự động giữ nguyên hành vi cũ.
- brew_order_material_line.member_qty_snapshot (JSON, nullable): snapshot định mức riêng từng
  thành viên lúc lập Lệnh nấu — chỉ có khi Công thức khai dòng nhóm theo kiểu mỗi thành viên 1
  định mức (xem services/brew_order.py::build_lines_from_recipe_version). NULL cho dòng nhóm
  kiểu cũ (giữ nguyên qty_per_batch/qty_total dùng chung).
"""
from alembic import op
import sqlalchemy as sa


revision = '8a09fb60a835'
down_revision = 'dc08eef2060e'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("material_alt_group",
                   sa.Column("selection_mode", sa.Unicode(32), nullable=False, server_default="single"))
    op.add_column("brew_order_material_line", sa.Column("member_qty_snapshot", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("brew_order_material_line", "member_qty_snapshot")
    op.drop_column("material_alt_group", "selection_mode")
