"""Kho TP (WMS): xóa vật lý 12 bảng của hệ vỉ/keg cũ (đã ngừng dùng từ migration
3313a1228281_wms_pallet_case_revive.py)

Revision ID: a4d6f89ff65e
Revises: 3313a1228281
Create Date: 2026-09-11

Người dùng xác nhận Kho TP thật (Đông Mai) chưa từng có dữ liệu và sẽ không bao giờ
dùng lại hệ vỉ/keg — xóa hẳn 12 bảng còn "mồ côi" trong DB (đã ngừng dùng trong code từ
migration trước, chỉ còn nằm im): finished_goods_unit, shipment, wms_transfer,
wms_transfer_line, near_expiry_entry, consigned_entry, factory_import_entry, load_order,
load_slip, load_slip_line, wms_vehicle, wms_warehouse.

KHÔNG đụng tới: wms_location/pallet/wms_case (hệ pallet/case đang dùng), audit_log (dọn
audit_log của các bảng này ĐÃ được xử lý riêng ở script data-cleanup, không phải ở đây —
audit_log là sổ hash-chain, không tự ý xóa qua migration), genealogy_edge (dọn cạnh trỏ
tới finished_goods_unit ngay trong migration này vì đây là dữ liệu suy ra, không phải sổ
audit).

QUAN TRỌNG: đây là DDL phá hủy — xóa cả bảng lẫn TOÀN BỘ dữ liệu bên trong (nếu có). Backup
database trước khi chạy trên production. downgrade() chỉ dựng lại ĐÚNG SCHEMA (cột/FK/index)
theo bản cuối cùng trước khi các bảng này bị xóa — KHÔNG khôi phục lại dữ liệu đã mất.
"""
from alembic import op
import sqlalchemy as sa

revision = 'a4d6f89ff65e'
down_revision = '3313a1228281'
branch_labels = None
depends_on = None

# Thứ tự XÓA — con trước cha (bảng nào có FK trỏ tới bảng khác thì xóa trước), tính toán đầy
# đủ theo FK giữa 12 bảng này với nhau (không tính FK ra ngoài — supplier/finished_product/
# bottle_record/factory_location vẫn còn nguyên, không bị đụng tới).
DROP_ORDER = [
    "wms_transfer_line", "near_expiry_entry", "consigned_entry", "factory_import_entry",
    "load_slip_line", "finished_goods_unit", "load_slip", "wms_transfer", "shipment",
    "load_order", "wms_vehicle", "wms_warehouse",
]


def upgrade() -> None:
    # Dọn cạnh gia phả (genealogy_edge) trỏ tới finished_goods_unit TRƯỚC khi xóa bảng —
    # đây là dữ liệu suy ra (không phải sổ audit hash-chain), an toàn để dọn cùng.
    op.execute(sa.text(
        "DELETE FROM genealogy_edge WHERE from_type = 'finished_goods_unit' "
        "OR to_type = 'finished_goods_unit'"
    ))
    for table in DROP_ORDER:
        op.drop_table(table)


def downgrade() -> None:
    op.create_table(
        'wms_warehouse',
        sa.Column('warehouse_id', sa.Unicode(length=64), nullable=False),
        sa.Column('code', sa.Unicode(length=64), nullable=False),
        sa.Column('name', sa.Unicode(length=255), nullable=False),
        sa.Column('address', sa.Unicode(length=255), nullable=True),
        sa.Column('active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('load_order_sheet_type', sa.Unicode(length=16), nullable=True),
        sa.PrimaryKeyConstraint('warehouse_id'),
    )
    op.create_index(op.f('ix_wms_warehouse_code'), 'wms_warehouse', ['code'], unique=True)

    op.create_table(
        'wms_vehicle',
        sa.Column('vehicle_id', sa.Unicode(length=64), nullable=False),
        sa.Column('vehicle_code', sa.Unicode(length=32), nullable=False),
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
    op.create_index(op.f('ix_wms_vehicle_vehicle_code'), 'wms_vehicle', ['vehicle_code'], unique=True)
    op.create_index(op.f('ix_wms_vehicle_plate'), 'wms_vehicle', ['plate'], unique=True)

    op.create_table(
        'load_order',
        sa.Column('load_order_id', sa.Unicode(length=64), nullable=False),
        sa.Column('order_code', sa.Unicode(length=64), nullable=False),
        sa.Column('sheet_type', sa.Unicode(length=16), nullable=False),
        sa.Column('warehouse_id', sa.Unicode(length=64), nullable=True),
        sa.Column('shift_label', sa.Unicode(length=64), nullable=True),
        sa.Column('order_date', sa.DateTime(timezone=True), nullable=True),
        sa.Column('source_file_name', sa.Unicode(length=255), nullable=True),
        sa.Column('created_by', sa.Unicode(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['warehouse_id'], ['wms_warehouse.warehouse_id']),
        sa.PrimaryKeyConstraint('load_order_id'),
    )
    op.create_index(op.f('ix_load_order_order_code'), 'load_order', ['order_code'], unique=True)
    op.create_index(op.f('ix_load_order_sheet_type'), 'load_order', ['sheet_type'], unique=False)
    op.create_index(op.f('ix_load_order_warehouse_id'), 'load_order', ['warehouse_id'], unique=False)

    op.create_table(
        'shipment',
        sa.Column('shipment_id', sa.Unicode(length=64), nullable=False),
        sa.Column('shipment_code', sa.Unicode(length=64), nullable=False),
        sa.Column('ship_to_id', sa.Unicode(length=64), nullable=False),
        sa.Column('warehouse_id', sa.Unicode(length=64), nullable=True),
        sa.Column('created_by', sa.Unicode(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('note', sa.Unicode(length=255), nullable=True),
        sa.Column('fifo_ok', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('shipment_type', sa.Unicode(length=32), nullable=False, server_default='normal'),
        sa.Column('recipient_name', sa.Unicode(length=255), nullable=True),
        sa.Column('recipient_dept', sa.Unicode(length=255), nullable=True),
        sa.Column('driver_name', sa.Unicode(length=255), nullable=True),
        sa.Column('vehicle_plate', sa.Unicode(length=64), nullable=True),
        sa.Column('from_location', sa.Unicode(length=255), nullable=True),
        sa.Column('delivery_place', sa.Unicode(length=255), nullable=True),
        sa.Column('vehicle_id', sa.Unicode(length=64), nullable=True),
        sa.Column('km', sa.Float(), nullable=True),
        sa.Column('fuel_liters', sa.Float(), nullable=True),
        sa.Column('confirmed_by', sa.Unicode(length=255), nullable=True),
        sa.Column('confirmed_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['ship_to_id'], ['supplier.supplier_id']),
        sa.ForeignKeyConstraint(['warehouse_id'], ['wms_warehouse.warehouse_id']),
        sa.ForeignKeyConstraint(['vehicle_id'], ['wms_vehicle.vehicle_id']),
        sa.PrimaryKeyConstraint('shipment_id'),
    )
    op.create_index(op.f('ix_shipment_shipment_code'), 'shipment', ['shipment_code'], unique=True)
    op.create_index(op.f('ix_shipment_ship_to_id'), 'shipment', ['ship_to_id'], unique=False)
    op.create_index(op.f('ix_shipment_warehouse_id'), 'shipment', ['warehouse_id'], unique=False)
    op.create_index(op.f('ix_shipment_vehicle_id'), 'shipment', ['vehicle_id'], unique=False)

    op.create_table(
        'wms_transfer',
        sa.Column('transfer_id', sa.Unicode(length=64), nullable=False),
        sa.Column('transfer_code', sa.Unicode(length=64), nullable=False),
        sa.Column('to_location_id', sa.Unicode(length=64), nullable=True),
        sa.Column('created_by', sa.Unicode(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('note', sa.Unicode(length=255), nullable=True),
        sa.Column('fifo_ok', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('driver_name', sa.Unicode(length=255), nullable=True),
        sa.Column('vehicle_plate', sa.Unicode(length=64), nullable=True),
        sa.Column('vehicle_id', sa.Unicode(length=64), nullable=True),
        sa.Column('from_location', sa.Unicode(length=255), nullable=True),
        sa.Column('km', sa.Float(), nullable=True),
        sa.Column('fuel_liters', sa.Float(), nullable=True),
        sa.Column('confirmed_by', sa.Unicode(length=255), nullable=True),
        sa.Column('confirmed_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['to_location_id'], ['wms_location.loc_id']),
        sa.ForeignKeyConstraint(['vehicle_id'], ['wms_vehicle.vehicle_id']),
        sa.PrimaryKeyConstraint('transfer_id'),
    )
    op.create_index(op.f('ix_wms_transfer_transfer_code'), 'wms_transfer', ['transfer_code'], unique=True)
    op.create_index(op.f('ix_wms_transfer_to_location_id'), 'wms_transfer', ['to_location_id'], unique=False)
    op.create_index(op.f('ix_wms_transfer_vehicle_id'), 'wms_transfer', ['vehicle_id'], unique=False)

    op.create_table(
        'finished_goods_unit',
        sa.Column('unit_id', sa.Unicode(length=64), nullable=False),
        sa.Column('unit_code', sa.Unicode(length=64), nullable=False),
        sa.Column('unit_type', sa.Unicode(length=16), nullable=False),
        sa.Column('finished_product_id', sa.Unicode(length=64), nullable=True),
        sa.Column('product_name', sa.Unicode(length=255), nullable=True),
        sa.Column('lot_code', sa.Unicode(length=64), nullable=True),
        sa.Column('quantity', sa.Float(), nullable=False, server_default='0'),
        sa.Column('status', sa.Unicode(length=255), nullable=False, server_default='stored'),
        sa.Column('location_id', sa.Unicode(length=64), nullable=True),
        sa.Column('created_by', sa.Unicode(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('shipped_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('shipment_id', sa.Unicode(length=64), nullable=True),
        sa.Column('ship_to_id', sa.Unicode(length=64), nullable=True),
        sa.Column('is_near_expiry', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('is_consigned', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('is_factory_import', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('source', sa.Unicode(length=32), nullable=True),
        sa.Column('received_confirmed_by', sa.Unicode(length=255), nullable=True),
        sa.Column('received_confirmed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('shipment_line_type', sa.Unicode(length=32), nullable=True),
        sa.Column('transfer_id', sa.Unicode(length=64), nullable=True),
        sa.ForeignKeyConstraint(['finished_product_id'], ['finished_product.finished_product_id']),
        sa.ForeignKeyConstraint(['location_id'], ['wms_location.loc_id']),
        sa.ForeignKeyConstraint(['shipment_id'], ['shipment.shipment_id']),
        sa.ForeignKeyConstraint(['ship_to_id'], ['supplier.supplier_id']),
        sa.ForeignKeyConstraint(['transfer_id'], ['wms_transfer.transfer_id']),
        sa.PrimaryKeyConstraint('unit_id'),
    )
    op.create_index(op.f('ix_finished_goods_unit_unit_code'), 'finished_goods_unit', ['unit_code'], unique=True)
    op.create_index(op.f('ix_finished_goods_unit_unit_type'), 'finished_goods_unit', ['unit_type'], unique=False)
    op.create_index(op.f('ix_finished_goods_unit_finished_product_id'), 'finished_goods_unit', ['finished_product_id'], unique=False)
    op.create_index(op.f('ix_finished_goods_unit_status'), 'finished_goods_unit', ['status'], unique=False)
    op.create_index(op.f('ix_finished_goods_unit_location_id'), 'finished_goods_unit', ['location_id'], unique=False)
    op.create_index(op.f('ix_finished_goods_unit_shipment_id'), 'finished_goods_unit', ['shipment_id'], unique=False)
    op.create_index(op.f('ix_finished_goods_unit_ship_to_id'), 'finished_goods_unit', ['ship_to_id'], unique=False)
    op.create_index(op.f('ix_finished_goods_unit_is_near_expiry'), 'finished_goods_unit', ['is_near_expiry'], unique=False)
    op.create_index(op.f('ix_finished_goods_unit_is_consigned'), 'finished_goods_unit', ['is_consigned'], unique=False)
    op.create_index(op.f('ix_finished_goods_unit_is_factory_import'), 'finished_goods_unit', ['is_factory_import'], unique=False)
    op.create_index(op.f('ix_finished_goods_unit_source'), 'finished_goods_unit', ['source'], unique=False)
    op.create_index(op.f('ix_finished_goods_unit_shipment_line_type'), 'finished_goods_unit', ['shipment_line_type'], unique=False)
    op.create_index(op.f('ix_finished_goods_unit_transfer_id'), 'finished_goods_unit', ['transfer_id'], unique=False)

    op.create_table(
        'load_slip',
        sa.Column('load_slip_id', sa.Unicode(length=64), nullable=False),
        sa.Column('slip_code', sa.Unicode(length=64), nullable=False),
        sa.Column('sheet_type', sa.Unicode(length=16), nullable=False),
        sa.Column('load_order_id', sa.Unicode(length=64), nullable=True),
        sa.Column('shipment_id', sa.Unicode(length=64), nullable=True),
        sa.Column('shift_label', sa.Unicode(length=64), nullable=True),
        sa.Column('order_date', sa.DateTime(timezone=True), nullable=True),
        sa.Column('vehicle_plate', sa.Unicode(length=64), nullable=False),
        sa.Column('driver_name', sa.Unicode(length=255), nullable=True),
        sa.Column('routes', sa.UnicodeText(), nullable=True),
        sa.Column('note', sa.UnicodeText(), nullable=True),
        sa.Column('source_file_name', sa.Unicode(length=255), nullable=True),
        sa.Column('issuer_name', sa.Unicode(length=255), nullable=True),
        sa.Column('issuer_title', sa.Unicode(length=255), nullable=True),
        sa.Column('issuer_dept', sa.Unicode(length=255), nullable=True),
        sa.Column('recipient_name', sa.Unicode(length=255), nullable=True),
        sa.Column('recipient_title', sa.Unicode(length=255), nullable=True),
        sa.Column('recipient_unit', sa.Unicode(length=255), nullable=True),
        sa.Column('created_by', sa.Unicode(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['load_order_id'], ['load_order.load_order_id']),
        sa.ForeignKeyConstraint(['shipment_id'], ['shipment.shipment_id']),
        sa.PrimaryKeyConstraint('load_slip_id'),
    )
    op.create_index(op.f('ix_load_slip_slip_code'), 'load_slip', ['slip_code'], unique=True)
    op.create_index(op.f('ix_load_slip_sheet_type'), 'load_slip', ['sheet_type'], unique=False)
    op.create_index(op.f('ix_load_slip_load_order_id'), 'load_slip', ['load_order_id'], unique=False)
    op.create_index(op.f('ix_load_slip_shipment_id'), 'load_slip', ['shipment_id'], unique=False)
    op.create_index(op.f('ix_load_slip_vehicle_plate'), 'load_slip', ['vehicle_plate'], unique=False)

    op.create_table(
        'load_slip_line',
        sa.Column('line_id', sa.Unicode(length=64), nullable=False),
        sa.Column('load_slip_id', sa.Unicode(length=64), nullable=False),
        sa.Column('seq', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('product_name', sa.Unicode(length=255), nullable=False),
        sa.Column('uom', sa.Unicode(length=64), nullable=False),
        sa.Column('quantity', sa.Float(), nullable=False, server_default='0'),
        sa.Column('is_promo', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('note', sa.Unicode(length=255), nullable=True),
        sa.Column('product_code', sa.Unicode(length=64), nullable=True),
        sa.Column('finished_product_id', sa.Unicode(length=64), nullable=True),
        sa.ForeignKeyConstraint(['load_slip_id'], ['load_slip.load_slip_id']),
        sa.ForeignKeyConstraint(['finished_product_id'], ['finished_product.finished_product_id']),
        sa.PrimaryKeyConstraint('line_id'),
    )
    op.create_index(op.f('ix_load_slip_line_load_slip_id'), 'load_slip_line', ['load_slip_id'], unique=False)
    op.create_index(op.f('ix_load_slip_line_finished_product_id'), 'load_slip_line', ['finished_product_id'], unique=False)

    op.create_table(
        'factory_import_entry',
        sa.Column('entry_id', sa.Unicode(length=64), nullable=False),
        sa.Column('finished_product_id', sa.Unicode(length=64), nullable=True),
        sa.Column('product_name', sa.Unicode(length=255), nullable=True),
        sa.Column('lot_code', sa.Unicode(length=64), nullable=True),
        sa.Column('unit_type', sa.Unicode(length=16), nullable=False),
        sa.Column('quantity', sa.Integer(), nullable=False),
        sa.Column('location_id', sa.Unicode(length=64), nullable=True),
        sa.Column('factory_id', sa.Unicode(length=64), nullable=True),
        sa.Column('declared_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('note', sa.UnicodeText(), nullable=True),
        sa.Column('created_by', sa.Unicode(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('unit_codes', sa.UnicodeText(), nullable=True),
        sa.Column('reversed', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('approved_by', sa.Unicode(length=255), nullable=True),
        sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['finished_product_id'], ['finished_product.finished_product_id']),
        sa.ForeignKeyConstraint(['location_id'], ['wms_location.loc_id']),
        sa.ForeignKeyConstraint(['factory_id'], ['factory_location.factory_id']),
        sa.PrimaryKeyConstraint('entry_id'),
    )
    op.create_index(op.f('ix_factory_import_entry_finished_product_id'), 'factory_import_entry', ['finished_product_id'], unique=False)
    op.create_index(op.f('ix_factory_import_entry_location_id'), 'factory_import_entry', ['location_id'], unique=False)
    op.create_index(op.f('ix_factory_import_entry_factory_id'), 'factory_import_entry', ['factory_id'], unique=False)

    op.create_table(
        'consigned_entry',
        sa.Column('entry_id', sa.Unicode(length=64), nullable=False),
        sa.Column('direction', sa.Unicode(length=16), nullable=False),
        sa.Column('finished_product_id', sa.Unicode(length=64), nullable=True),
        sa.Column('product_name', sa.Unicode(length=255), nullable=True),
        sa.Column('lot_code', sa.Unicode(length=64), nullable=True),
        sa.Column('unit_type', sa.Unicode(length=16), nullable=False),
        sa.Column('quantity', sa.Integer(), nullable=False),
        sa.Column('location_id', sa.Unicode(length=64), nullable=True),
        sa.Column('declared_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('vehicle_id', sa.Unicode(length=64), nullable=True),
        sa.Column('shipment_id', sa.Unicode(length=64), nullable=True),
        sa.Column('note', sa.UnicodeText(), nullable=True),
        sa.Column('created_by', sa.Unicode(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('unit_codes', sa.UnicodeText(), nullable=True),
        sa.Column('reversed', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('approved_by', sa.Unicode(length=255), nullable=True),
        sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['finished_product_id'], ['finished_product.finished_product_id']),
        sa.ForeignKeyConstraint(['location_id'], ['wms_location.loc_id']),
        sa.ForeignKeyConstraint(['vehicle_id'], ['wms_vehicle.vehicle_id']),
        sa.ForeignKeyConstraint(['shipment_id'], ['shipment.shipment_id']),
        sa.PrimaryKeyConstraint('entry_id'),
    )
    op.create_index(op.f('ix_consigned_entry_direction'), 'consigned_entry', ['direction'], unique=False)
    op.create_index(op.f('ix_consigned_entry_finished_product_id'), 'consigned_entry', ['finished_product_id'], unique=False)
    op.create_index(op.f('ix_consigned_entry_location_id'), 'consigned_entry', ['location_id'], unique=False)
    op.create_index(op.f('ix_consigned_entry_vehicle_id'), 'consigned_entry', ['vehicle_id'], unique=False)
    op.create_index(op.f('ix_consigned_entry_shipment_id'), 'consigned_entry', ['shipment_id'], unique=False)

    op.create_table(
        'near_expiry_entry',
        sa.Column('entry_id', sa.Unicode(length=64), nullable=False),
        sa.Column('direction', sa.Unicode(length=16), nullable=False),
        sa.Column('finished_product_id', sa.Unicode(length=64), nullable=True),
        sa.Column('product_name', sa.Unicode(length=255), nullable=True),
        sa.Column('lot_code', sa.Unicode(length=64), nullable=True),
        sa.Column('unit_type', sa.Unicode(length=16), nullable=False),
        sa.Column('quantity', sa.Integer(), nullable=False),
        sa.Column('location_id', sa.Unicode(length=64), nullable=True),
        sa.Column('declared_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('bottle_id', sa.Unicode(length=64), nullable=True),
        sa.Column('shipment_id', sa.Unicode(length=64), nullable=True),
        sa.Column('note', sa.UnicodeText(), nullable=True),
        sa.Column('created_by', sa.Unicode(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('unit_codes', sa.UnicodeText(), nullable=True),
        sa.Column('reversed', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('approved_by', sa.Unicode(length=255), nullable=True),
        sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['finished_product_id'], ['finished_product.finished_product_id']),
        sa.ForeignKeyConstraint(['location_id'], ['wms_location.loc_id']),
        sa.ForeignKeyConstraint(['bottle_id'], ['bottle_record.bottle_id']),
        sa.ForeignKeyConstraint(['shipment_id'], ['shipment.shipment_id']),
        sa.PrimaryKeyConstraint('entry_id'),
    )
    op.create_index(op.f('ix_near_expiry_entry_direction'), 'near_expiry_entry', ['direction'], unique=False)
    op.create_index(op.f('ix_near_expiry_entry_finished_product_id'), 'near_expiry_entry', ['finished_product_id'], unique=False)
    op.create_index(op.f('ix_near_expiry_entry_location_id'), 'near_expiry_entry', ['location_id'], unique=False)
    op.create_index(op.f('ix_near_expiry_entry_bottle_id'), 'near_expiry_entry', ['bottle_id'], unique=False)
    op.create_index(op.f('ix_near_expiry_entry_shipment_id'), 'near_expiry_entry', ['shipment_id'], unique=False)

    op.create_table(
        'wms_transfer_line',
        sa.Column('line_id', sa.Unicode(length=64), nullable=False),
        sa.Column('transfer_id', sa.Unicode(length=64), nullable=False),
        sa.Column('unit_id', sa.Unicode(length=64), nullable=False),
        sa.Column('from_location_id', sa.Unicode(length=64), nullable=True),
        sa.ForeignKeyConstraint(['transfer_id'], ['wms_transfer.transfer_id']),
        sa.ForeignKeyConstraint(['unit_id'], ['finished_goods_unit.unit_id']),
        sa.ForeignKeyConstraint(['from_location_id'], ['wms_location.loc_id']),
        sa.PrimaryKeyConstraint('line_id'),
    )
    op.create_index(op.f('ix_wms_transfer_line_transfer_id'), 'wms_transfer_line', ['transfer_id'], unique=False)
    op.create_index(op.f('ix_wms_transfer_line_unit_id'), 'wms_transfer_line', ['unit_id'], unique=False)
