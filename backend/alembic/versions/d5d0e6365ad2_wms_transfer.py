"""Điều chuyển nội bộ — phiếu điều chuyển mirror Shipment (WmsTransfer/WmsTransferLine)

Revision ID: d5d0e6365ad2
Revises: b7c8d9e0f1a2
Create Date: 2026-08-06

- wms_transfer: 1 phiếu điều chuyển nội bộ — mirror Shipment (chọn theo sản phẩm/lô/loại đơn
  vị/số lượng, tự chọn FIFO cũ nhất, có xe/lái xe/km/lít xăng, Duyệt/Hoàn tác, in phiếu, lịch
  sử riêng) NHƯNG đích là 1 WmsLocation (không phải Supplier/ship_to) và KHÔNG làm giảm tổng
  tồn kho toàn công ty (xem services/wms.py::create_transfer).
- wms_transfer_line: ghi vị trí TRƯỚC khi chuyển của mỗi FinishedGoodsUnit — để Hoàn tác trả
  đúng lại (khác Shipment, Xuất kho luôn xóa location_id nên không có gì để trả lại).
- finished_goods_unit.transfer_id: phiếu điều chuyển GẦN NHẤT đã chạm vào dòng này — mirror
  shipment_id, dùng để undo_transfer() phát hiện đơn vị đã bị thao tác khác chạm vào sau đó.
"""
from alembic import op
import sqlalchemy as sa

revision = 'd5d0e6365ad2'
down_revision = 'b7c8d9e0f1a2'
branch_labels = None
depends_on = None


# Dev/staging DBs migrated through the ship_to_location->supplier merge (e9f0a1b2c3d5) before
# that migration's DDL had been fully applied everywhere may still carry an OLD dangling FK
# `finished_goods_unit.ship_to_id -> ship_to_location(ship_to_id)` baked into SQLite's stored
# CREATE TABLE text ALONGSIDE the current real FK to supplier — batch_alter_table's default
# reflect step chokes on that (NoSuchTableError) before we ever get to add our own column, same
# issue already worked around for `shipment` in a5b6c7d8e9f1. Hand it an explicit `copy_from`
# Table describing the CURRENT real shape instead of reflecting.
_FGU_BEFORE = sa.Table(
    'finished_goods_unit', sa.MetaData(),
    sa.Column('unit_id', sa.Unicode(length=64), primary_key=True),
    sa.Column('unit_code', sa.Unicode(length=64), nullable=False, unique=True, index=True),
    sa.Column('unit_type', sa.Unicode(length=16), nullable=False, index=True),
    sa.Column('finished_product_id', sa.Unicode(length=64), sa.ForeignKey('finished_product.finished_product_id'), nullable=True, index=True),
    sa.Column('product_name', sa.Unicode(length=255), nullable=True),
    sa.Column('lot_code', sa.Unicode(length=64), nullable=True),
    sa.Column('quantity', sa.Float(), nullable=False, server_default='0'),
    sa.Column('status', sa.Unicode(length=255), nullable=False, server_default='stored', index=True),
    sa.Column('location_id', sa.Unicode(length=64), sa.ForeignKey('wms_location.loc_id'), nullable=True, index=True),
    sa.Column('created_by', sa.Unicode(length=255), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('shipped_at', sa.DateTime(), nullable=True),
    sa.Column('shipment_id', sa.Unicode(length=64), sa.ForeignKey('shipment.shipment_id'), nullable=True, index=True),
    sa.Column('ship_to_id', sa.Unicode(length=64),
              sa.ForeignKey('supplier.supplier_id', name='fk_finished_goods_unit_ship_to_id_supplier'),
              nullable=True, index=True),
    sa.Column('is_near_expiry', sa.Boolean(), nullable=False, server_default=sa.false(), index=True),
    sa.Column('is_consigned', sa.Boolean(), nullable=False, server_default=sa.false(), index=True),
    sa.Column('source', sa.Unicode(length=32), nullable=True, index=True),
    sa.Column('received_confirmed_by', sa.Unicode(length=255), nullable=True),
    sa.Column('received_confirmed_at', sa.DateTime(), nullable=True),
    sa.Column('shipment_line_type', sa.Unicode(length=32), nullable=True, index=True),
)


def upgrade() -> None:
    op.create_table(
        'wms_transfer',
        sa.Column('transfer_id', sa.Unicode(length=64), nullable=False),
        sa.Column('transfer_code', sa.Unicode(length=64), nullable=False),
        sa.Column('to_location_id', sa.Unicode(length=64), sa.ForeignKey('wms_location.loc_id'), nullable=False),
        sa.Column('created_by', sa.Unicode(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('note', sa.Unicode(length=255), nullable=True),
        sa.Column('fifo_ok', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('driver_name', sa.Unicode(length=255), nullable=True),
        sa.Column('vehicle_plate', sa.Unicode(length=64), nullable=True),
        sa.Column('vehicle_id', sa.Unicode(length=64), sa.ForeignKey('wms_vehicle.vehicle_id'), nullable=True),
        sa.Column('from_location', sa.Unicode(length=255), nullable=True),
        sa.Column('km', sa.Float(), nullable=True),
        sa.Column('fuel_liters', sa.Float(), nullable=True),
        sa.Column('confirmed_by', sa.Unicode(length=255), nullable=True),
        sa.Column('confirmed_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('transfer_id'),
    )
    op.create_index('ix_wms_transfer_transfer_code', 'wms_transfer', ['transfer_code'], unique=True)
    op.create_index('ix_wms_transfer_to_location_id', 'wms_transfer', ['to_location_id'])
    op.create_index('ix_wms_transfer_vehicle_id', 'wms_transfer', ['vehicle_id'])

    op.create_table(
        'wms_transfer_line',
        sa.Column('line_id', sa.Unicode(length=64), nullable=False),
        sa.Column('transfer_id', sa.Unicode(length=64), sa.ForeignKey('wms_transfer.transfer_id'), nullable=False),
        sa.Column('unit_id', sa.Unicode(length=64), sa.ForeignKey('finished_goods_unit.unit_id'), nullable=False),
        sa.Column('from_location_id', sa.Unicode(length=64), sa.ForeignKey('wms_location.loc_id'), nullable=True),
        sa.PrimaryKeyConstraint('line_id'),
    )
    op.create_index('ix_wms_transfer_line_transfer_id', 'wms_transfer_line', ['transfer_id'])
    op.create_index('ix_wms_transfer_line_unit_id', 'wms_transfer_line', ['unit_id'])

    with op.batch_alter_table('finished_goods_unit', recreate='auto', copy_from=_FGU_BEFORE) as batch_op:
        batch_op.add_column(sa.Column('transfer_id', sa.Unicode(length=64),
            sa.ForeignKey('wms_transfer.transfer_id', name='fk_finished_goods_unit_transfer_id_wms_transfer'),
            nullable=True))
    op.create_index('ix_finished_goods_unit_transfer_id', 'finished_goods_unit', ['transfer_id'])


def downgrade() -> None:
    op.drop_index('ix_finished_goods_unit_transfer_id', table_name='finished_goods_unit')
    with op.batch_alter_table('finished_goods_unit', recreate='auto') as batch_op:
        batch_op.drop_constraint('fk_finished_goods_unit_transfer_id_wms_transfer', type_='foreignkey')
        batch_op.drop_column('transfer_id')

    op.drop_table('wms_transfer_line')
    op.drop_table('wms_transfer')
