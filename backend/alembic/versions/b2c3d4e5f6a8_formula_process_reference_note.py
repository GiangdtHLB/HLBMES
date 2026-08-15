"""Công thức: thêm cột nội dung quyết định ban hành + quy trình sản xuất

Them cot formula.process_reference_note -- noi dung QD ban hanh cong thuc/quy trinh san xuat
(so QD, bieu cong nghe, lan ban hanh...), khai bao 1 lan tren cong thuc, in nguyen van vao
phieu Lenh nau moi khi cong thuc nay duoc chon cho 1 lenh nau nho. Xem
services/brew_order.py::_child_summary/get_order va frontend/app.js::printBrewOrder.

Revision ID: b2c3d4e5f6a8
Revises: a1b2c3d4e5f7
Create Date: 2026-08-15
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "b2c3d4e5f6a8"
down_revision = "a1b2c3d4e5f7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("formula") as batch_op:
        batch_op.add_column(sa.Column("process_reference_note", sa.UnicodeText(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("formula") as batch_op:
        batch_op.drop_column("process_reference_note")
