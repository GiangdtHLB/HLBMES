"""Kho TP (WMS): khôi phục pallet/wms_case (hạ cấp khỏi finished_goods_unit)

Revision ID: 3313a1228281
Revises: 3e0894f298ab
Create Date: 2026-09-10

Khôi phục lại đúng 2 bảng pallet/wms_case (đã bị f6a7b8c9d0e2_finished_goods_unit.py xóa
23/07/2026 khi chuyển sang hệ vỉ/keg) — schema y hệt migration gốc d4e5f6a7b8c9_wms.py. Kho
thành phẩm ở bản triển khai thật chưa từng có dữ liệu, người dùng xác nhận quay lại hệ pallet/
case cũ, bỏ hệ vỉ/keg. wms_location KHÔNG bị đụng — bảng đó chưa từng bị xóa (chỉ được thêm cột
warehouse_id/layout_row/layout_col ở các migration sau, nay để nguyên không dùng tới). 11 bảng
khác của hệ vỉ/keg (finished_goods_unit, shipment, wms_transfer, wms_transfer_line,
near_expiry_entry, consigned_entry, factory_import_entry, load_order, load_slip, load_slip_line,
wms_vehicle, wms_warehouse) CỐ TÌNH không DROP ở đây — dữ liệu đang trống, để nguyên vật lý cho an
toàn (DDL phá hủy trên production không cần thiết), dọn tay sau nếu cần.
"""
from alembic import op
import sqlalchemy as sa

revision = '3313a1228281'
down_revision = '3e0894f298ab'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'pallet',
        sa.Column('pallet_id', sa.Unicode(length=64), nullable=False),
        sa.Column('pallet_code', sa.Unicode(length=64), nullable=False),
        sa.Column('product', sa.Unicode(length=255), nullable=True),
        sa.Column('lot_code', sa.Unicode(length=64), nullable=True),
        sa.Column('case_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('units_per_case', sa.Integer(), nullable=False, server_default='24'),
        sa.Column('status', sa.Unicode(length=255), nullable=False, server_default='building'),
        sa.Column('location_id', sa.Unicode(length=64), nullable=True),
        sa.Column('created_by', sa.Unicode(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['location_id'], ['wms_location.loc_id']),
        sa.PrimaryKeyConstraint('pallet_id'),
    )
    op.create_index(op.f('ix_pallet_pallet_code'), 'pallet', ['pallet_code'], unique=True)
    op.create_index(op.f('ix_pallet_status'), 'pallet', ['status'], unique=False)
    op.create_index(op.f('ix_pallet_location_id'), 'pallet', ['location_id'], unique=False)
    op.create_table(
        'wms_case',
        sa.Column('case_id', sa.Unicode(length=64), nullable=False),
        sa.Column('case_code', sa.Unicode(length=64), nullable=False),
        sa.Column('pallet_id', sa.Unicode(length=64), nullable=False),
        sa.Column('product', sa.Unicode(length=255), nullable=True),
        sa.Column('units', sa.Float(), nullable=False, server_default='24'),
        sa.Column('lot_code', sa.Unicode(length=64), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['pallet_id'], ['pallet.pallet_id']),
        sa.PrimaryKeyConstraint('case_id'),
    )
    op.create_index(op.f('ix_wms_case_case_code'), 'wms_case', ['case_code'], unique=True)
    op.create_index(op.f('ix_wms_case_pallet_id'), 'wms_case', ['pallet_id'], unique=False)


def downgrade() -> None:
    op.drop_table('wms_case')
    op.drop_table('pallet')
