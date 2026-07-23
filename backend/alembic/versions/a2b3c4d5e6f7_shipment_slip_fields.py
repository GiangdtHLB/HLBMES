"""Shipment: thêm các trường in phiếu xuất kho (Mẫu số 02-VT)

Revision ID: a2b3c4d5e6f7
Revises: f6a7b8c9d0ec
Create Date: 2026-07-15

- shipment.recipient_name, recipient_dept, driver_name, vehicle_plate,
  from_location, delivery_place: các trường nhập tay để in đúng mẫu giấy
  "PHIẾU XUẤT KHO" (Mẫu số 02-VT, kèm theo Thông tư số 99/2025/TT-BTC).
  note (đã có sẵn) dùng làm "Lý do xuất kho".
"""
from alembic import op
import sqlalchemy as sa

revision = 'a2b3c4d5e6f7'
down_revision = 'f6a7b8c9d0ec'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('shipment') as batch_op:
        batch_op.add_column(sa.Column('recipient_name', sa.Unicode(length=255), nullable=True))
        batch_op.add_column(sa.Column('recipient_dept', sa.Unicode(length=255), nullable=True))
        batch_op.add_column(sa.Column('driver_name', sa.Unicode(length=255), nullable=True))
        batch_op.add_column(sa.Column('vehicle_plate', sa.Unicode(length=64), nullable=True))
        batch_op.add_column(sa.Column('from_location', sa.Unicode(length=255), nullable=True))
        batch_op.add_column(sa.Column('delivery_place', sa.Unicode(length=255), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('shipment') as batch_op:
        batch_op.drop_column('delivery_place')
        batch_op.drop_column('from_location')
        batch_op.drop_column('vehicle_plate')
        batch_op.drop_column('driver_name')
        batch_op.drop_column('recipient_dept')
        batch_op.drop_column('recipient_name')
