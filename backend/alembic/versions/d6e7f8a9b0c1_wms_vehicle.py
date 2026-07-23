"""Danh mục xe/lái xe (wms_vehicle)

Revision ID: d6e7f8a9b0c1
Revises: c4d5e6f7a8b9
Create Date: 2026-07-15

- wms_vehicle: danh mục xe vận chuyển kèm lái xe/tải trọng/số pallet chở được — tra cứu
  nhanh khi lập Lệnh đóng hàng hoặc Phiếu xuất kho.
"""
from alembic import op
import sqlalchemy as sa

revision = 'd6e7f8a9b0c1'
down_revision = '130d08b9e003'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'wms_vehicle',
        sa.Column('vehicle_id', sa.Unicode(length=64), nullable=False),
        sa.Column('plate', sa.Unicode(length=32), nullable=False),
        sa.Column('driver_name', sa.Unicode(length=255), nullable=True),
        sa.Column('driver_short_name', sa.Unicode(length=64), nullable=True),
        sa.Column('capacity_kg', sa.Float(), nullable=True),
        sa.Column('pallet_capacity', sa.Integer(), nullable=True),
        sa.Column('phone', sa.Unicode(length=32), nullable=True),
        sa.Column('team', sa.Unicode(length=64), nullable=True),
        sa.Column('active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.PrimaryKeyConstraint('vehicle_id'),
    )
    op.create_index(op.f('ix_wms_vehicle_plate'), 'wms_vehicle', ['plate'], unique=True)


def downgrade() -> None:
    op.drop_index(op.f('ix_wms_vehicle_plate'), table_name='wms_vehicle')
    op.drop_table('wms_vehicle')
