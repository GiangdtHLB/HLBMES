"""Kho TP: đánh dấu nguồn gốc dòng nhập kho (chiết/nhập tay) + Trưởng bộ phận kho duyệt nhập
kho từ chiết — sau khi duyệt không xóa được nữa

Revision ID: c9d0e1f2a3b4
Revises: b8c9d0e1f2a3
Create Date: 2026-08-02

- finished_goods_unit: thêm source/received_confirmed_by/received_confirmed_at (xem
  services/wms.py::confirm_receipt_by_lot, routers/brewing.py::approve_bottle).
"""
from alembic import op
import sqlalchemy as sa

revision = 'c9d0e1f2a3b4'
down_revision = 'b8c9d0e1f2a3'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('finished_goods_unit', recreate='auto') as batch_op:
        batch_op.add_column(sa.Column('source', sa.Unicode(length=32), nullable=True))
        batch_op.add_column(sa.Column('received_confirmed_by', sa.Unicode(length=255), nullable=True))
        batch_op.add_column(sa.Column('received_confirmed_at', sa.DateTime(timezone=True), nullable=True))
        batch_op.create_index('ix_finished_goods_unit_source', ['source'])


def downgrade() -> None:
    with op.batch_alter_table('finished_goods_unit', recreate='auto') as batch_op:
        batch_op.drop_index('ix_finished_goods_unit_source')
        batch_op.drop_column('received_confirmed_at')
        batch_op.drop_column('received_confirmed_by')
        batch_op.drop_column('source')
