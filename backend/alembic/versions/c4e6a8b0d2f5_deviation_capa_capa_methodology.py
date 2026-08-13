"""Deviation/CAPA — thêm due_date + close_note cho cả 2 luồng, effectiveness_checked_at cho
CAPA, và nâng capa.deviation_id thành FK thật (trước đây chỉ là cột tự do, service tự check tồn
tại chứ DB không đảm bảo) — phục vụ việc bắt buộc Deviation major/critical phải có CAPA đã đóng
đúng chuẩn (root cause + action plan + effectiveness + ngày kiểm tra hiệu lực) trước khi đóng,
cả 2 đều bắt buộc ghi chú đóng + người đóng khác người mở, và có hạn xử lý để cảnh báo quá hạn.

Revision ID: c4e6a8b0d2f5
Revises: b3d5f7a9c1e2
Create Date: 2026-08-12
"""
from alembic import op
import sqlalchemy as sa


revision = 'c4e6a8b0d2f5'
down_revision = 'b3d5f7a9c1e2'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("deviation", sa.Column("due_date", sa.Date(), nullable=True))
    op.add_column("deviation", sa.Column("close_note", sa.UnicodeText(), nullable=True))
    op.add_column("capa", sa.Column("effectiveness_checked_at", sa.Date(), nullable=True))
    op.add_column("capa", sa.Column("close_note", sa.UnicodeText(), nullable=True))
    with op.batch_alter_table("capa") as batch_op:
        batch_op.create_foreign_key("fk_capa_deviation_id", "deviation",
                                     ["deviation_id"], ["deviation_id"])


def downgrade() -> None:
    with op.batch_alter_table("capa") as batch_op:
        batch_op.drop_constraint("fk_capa_deviation_id", type_="foreignkey")
    op.drop_column("capa", "close_note")
    op.drop_column("capa", "effectiveness_checked_at")
    op.drop_column("deviation", "close_note")
    op.drop_column("deviation", "due_date")
