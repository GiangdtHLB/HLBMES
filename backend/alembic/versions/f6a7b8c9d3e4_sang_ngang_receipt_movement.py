"""Sang ngang request: link to originating receipt movement (Sua/Xoa)

Them cot sang_ngang_request.receipt_movement_id -- tro toi StockMovement type=receipt goc tao ra
lo luc create_sang_ngang, KHAC movement_id hien co (do la movement type=transfer chi co SAU KHI
duyet). Dung de Sua/Xoa 1 de nghi con pending/rejected tai dung update_receipt/delete_receipt (da
co san rang buoc an toan: chan neu lo da dung hoac da khai bao QC). Xem
services/warehouse.py::update_sang_ngang/delete_sang_ngang.

Revision ID: f6a7b8c9d3e4
Revises: e5f6a7b8c9d3
Create Date: 2026-08-15
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "f6a7b8c9d3e4"
down_revision = "e5f6a7b8c9d3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("sang_ngang_request") as batch_op:
        batch_op.add_column(sa.Column("receipt_movement_id", sa.Unicode(64), nullable=True))
        batch_op.create_foreign_key(
            "fk_sang_ngang_request_receipt_movement_id", "stock_movement",
            ["receipt_movement_id"], ["movement_id"])


def downgrade() -> None:
    with op.batch_alter_table("sang_ngang_request") as batch_op:
        batch_op.drop_constraint("fk_sang_ngang_request_receipt_movement_id", type_="foreignkey")
        batch_op.drop_column("receipt_movement_id")
