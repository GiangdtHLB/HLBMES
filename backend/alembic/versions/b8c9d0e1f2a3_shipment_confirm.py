"""Xuất kho thành phẩm: Trưởng bộ phận kho xác nhận phiếu — sau khi xác nhận chỉ ADMIN hoàn tác

Revision ID: b8c9d0e1f2a3
Revises: a1c2d3e4f5b8
Create Date: 2026-08-02

- shipment: thêm confirmed_by/confirmed_at (xem services/wms.py::confirm_shipment/undo_shipment).
"""
from alembic import op
import sqlalchemy as sa

revision = 'b8c9d0e1f2a3'
down_revision = 'a1c2d3e4f5b8'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('shipment', recreate='auto') as batch_op:
        batch_op.add_column(sa.Column('confirmed_by', sa.Unicode(length=255), nullable=True))
        batch_op.add_column(sa.Column('confirmed_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('shipment', recreate='auto') as batch_op:
        batch_op.drop_column('confirmed_at')
        batch_op.drop_column('confirmed_by')
