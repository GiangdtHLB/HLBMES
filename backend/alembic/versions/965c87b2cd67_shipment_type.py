"""shipment: thêm shipment_type (nhãn phân loại phiếu xuất kho)

Revision ID: a1b2c3d4e5f6
Revises: f6a7b8c9d0e2
Create Date: 2026-07-18

- shipment.shipment_type: normal|promo|return — nhãn phân loại để in phiếu + lọc lịch
  sử xuất kho (Bán hàng thường/Khuyến mại/Đổi trả), không đổi cách trừ tồn kho.
"""
from alembic import op
import sqlalchemy as sa

from app.alembic_mssql import prep_drop_columns

revision = '965c87b2cd67'
down_revision = 'f6a7b8c9d0e2'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('shipment') as batch_op:
        batch_op.add_column(sa.Column('shipment_type', sa.Unicode(length=32), nullable=False, server_default='normal'))


def downgrade() -> None:
    prep_drop_columns(op.get_bind(), 'shipment', ['shipment_type'])
    with op.batch_alter_table('shipment') as batch_op:
        batch_op.drop_column('shipment_type')
