"""Mã xe cố định + km/lít xăng chuyến xuất + khối lượng SKU (kg)

Revision ID: f2a3b4c5d6e8
Revises: e17b49fe0d06
Create Date: 2026-08-06

- wms_vehicle.vehicle_code: mã cố định do hệ thống tự sinh ("XE0001", ...) — biển số có thể
  đổi nhưng mã này không đổi, dùng làm liên kết ổn định cho báo cáo lượt xe. Backfill xe cũ
  ngay trong upgrade() theo thứ tự created_at/rowid trước khi tạo unique index.
- shipment.vehicle_id (FK wms_vehicle, nullable): liên kết ổn định tới Danh mục lái xe, khác
  driver_name/vehicle_plate (free-text, giữ nguyên để in phiếu). shipment.km/fuel_liters: chỉ
  điền được sau khi phiếu đã Duyệt (xem services/wms.py::update_shipment_trip).
- consigned_entry.vehicle_id (FK wms_vehicle, nullable ở DB, bắt buộc ở tầng service cho
  direction="in") — xe đã mang bia gửi về, dùng hiện "xe đã gửi" ở picker Xuất kho.
- finished_product.weight_primary_kg/weight_single_kg: khối lượng (kg) 1 đơn vị đóng gói
  chính (vỉ/keg) và 1 lon-chai lẻ — dùng tính tải trọng chuyến xe (vehicle_trip_report).
"""
from alembic import op
import sqlalchemy as sa

revision = 'a5b6c7d8e9f1'
down_revision = 'e17b49fe0d06'
branch_labels = None
depends_on = None


# Dev/staging DBs migrated through the ship_to_location->supplier merge (e9f0a1b2c3d5) before
# that migration's DDL had been fully applied everywhere may still carry the OLD dangling FK
# `shipment.ship_to_id -> ship_to_location(ship_to_id)` baked into SQLite's stored CREATE TABLE
# text, even though `ship_to_location` itself no longer exists. batch_alter_table's default
# reflect step chokes on that (NoSuchTableError) before we ever get to add our own columns —
# so we hand it an explicit `copy_from` Table describing the CURRENT real shape (FK to
# supplier only), skipping reflection entirely.
_SHIPMENT_BEFORE = sa.Table(
    'shipment', sa.MetaData(),
    sa.Column('shipment_id', sa.Unicode(length=64), primary_key=True),
    sa.Column('shipment_code', sa.Unicode(length=64), nullable=False, unique=True, index=True),
    sa.Column('ship_to_id', sa.Unicode(length=64),
              sa.ForeignKey('supplier.supplier_id', name='fk_shipment_ship_to_id_supplier'),
              nullable=False, index=True),
    sa.Column('created_by', sa.Unicode(length=255), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('note', sa.Unicode(length=255), nullable=True),
    sa.Column('fifo_ok', sa.Boolean(), nullable=False, server_default=sa.true()),
    sa.Column('recipient_name', sa.Unicode(length=255), nullable=True),
    sa.Column('recipient_dept', sa.Unicode(length=255), nullable=True),
    sa.Column('driver_name', sa.Unicode(length=255), nullable=True),
    sa.Column('vehicle_plate', sa.Unicode(length=64), nullable=True),
    sa.Column('from_location', sa.Unicode(length=255), nullable=True),
    sa.Column('delivery_place', sa.Unicode(length=255), nullable=True),
    sa.Column('shipment_type', sa.Unicode(length=32), nullable=True, server_default='normal'),
    sa.Column('confirmed_by', sa.Unicode(length=255), nullable=True),
    sa.Column('confirmed_at', sa.DateTime(), nullable=True),
)


def upgrade() -> None:
    op.add_column('wms_vehicle', sa.Column('vehicle_code', sa.Unicode(length=32), nullable=True))
    bind = op.get_bind()
    rows = bind.execute(sa.text(
        "SELECT vehicle_id FROM wms_vehicle ORDER BY plate")).fetchall()
    for i, (vehicle_id,) in enumerate(rows, start=1):
        bind.execute(sa.text("UPDATE wms_vehicle SET vehicle_code = :code WHERE vehicle_id = :vid"),
                     {"code": f"XE{i:04d}", "vid": vehicle_id})
    with op.batch_alter_table('wms_vehicle', recreate='auto') as batch_op:
        batch_op.alter_column('vehicle_code', existing_type=sa.Unicode(length=32), nullable=False)
        batch_op.create_index('ix_wms_vehicle_vehicle_code', ['vehicle_code'], unique=True)

    with op.batch_alter_table('shipment', recreate='auto', copy_from=_SHIPMENT_BEFORE) as batch_op:
        batch_op.add_column(sa.Column('vehicle_id', sa.Unicode(length=64),
            sa.ForeignKey('wms_vehicle.vehicle_id', name='fk_shipment_vehicle_id_wms_vehicle'),
            nullable=True))
        batch_op.add_column(sa.Column('km', sa.Float(), nullable=True))
        batch_op.add_column(sa.Column('fuel_liters', sa.Float(), nullable=True))
    op.create_index('ix_shipment_vehicle_id', 'shipment', ['vehicle_id'])

    with op.batch_alter_table('consigned_entry', recreate='auto') as batch_op:
        batch_op.add_column(sa.Column('vehicle_id', sa.Unicode(length=64),
            sa.ForeignKey('wms_vehicle.vehicle_id', name='fk_consigned_entry_vehicle_id_wms_vehicle'),
            nullable=True))
    op.create_index('ix_consigned_entry_vehicle_id', 'consigned_entry', ['vehicle_id'])

    op.add_column('finished_product', sa.Column('weight_primary_kg', sa.Float(), nullable=True))
    op.add_column('finished_product', sa.Column('weight_single_kg', sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column('finished_product', 'weight_single_kg')
    op.drop_column('finished_product', 'weight_primary_kg')

    op.drop_index('ix_consigned_entry_vehicle_id', table_name='consigned_entry')
    with op.batch_alter_table('consigned_entry', recreate='auto') as batch_op:
        batch_op.drop_constraint('fk_consigned_entry_vehicle_id_wms_vehicle', type_='foreignkey')
        batch_op.drop_column('vehicle_id')

    op.drop_index('ix_shipment_vehicle_id', table_name='shipment')
    with op.batch_alter_table('shipment', recreate='auto') as batch_op:
        batch_op.drop_constraint('fk_shipment_vehicle_id_wms_vehicle', type_='foreignkey')
        batch_op.drop_column('fuel_liters')
        batch_op.drop_column('km')
        batch_op.drop_column('vehicle_id')

    with op.batch_alter_table('wms_vehicle', recreate='auto') as batch_op:
        batch_op.drop_index('ix_wms_vehicle_vehicle_code')
        batch_op.drop_column('vehicle_code')
