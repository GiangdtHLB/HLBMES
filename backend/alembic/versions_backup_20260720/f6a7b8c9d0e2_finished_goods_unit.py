"""kho thành phẩm quản lý theo vỉ/keg — thay pallet/case/shipment_line

Revision ID: f6a7b8c9d0e2
Revises: e5f6a7b8c9d0
Create Date: 2026-07-18

- finished_goods_unit: đơn vị tồn kho độc lập (1 vỉ = 24 lon cố định theo SKU, 1 keg =
  1 đơn vị) — thay hẳn Pallet+Case (không còn lớp gom nhóm phía trên). Sinh tự động khi
  duyệt chiết (routers/brewing.py::approve_bottle, mỗi dòng = 1 vỉ/keg, dòng cuối có thể
  lẻ) hoặc nhập tay (services/wms.py::build_units).
- shipment: bỏ bảng shipment_line — mỗi FinishedGoodsUnit gắn thẳng shipment_id khi xuất
  (không còn xuất một phần 1 vỉ/keg nên không cần bảng dòng riêng); in phiếu xuất kho gom
  nhóm theo (product, lot_code) trực tiếp trên các unit thuộc phiếu.
- finished_product: đổi tên units_per_case -> pack_size (Lon/vỉ hoặc 1 cho keg), thêm
  unit_type (vi|keg) để approve_bottle biết sinh loại đơn vị nào.
- Xóa bảng pallet/wms_case/shipment_line + dọn genealogy_edge kiểu "pallet" (mồ côi sau
  khi xóa bảng, mirror cách dọn cạnh mồ côi đã làm ở lần trước).
"""
from alembic import op
import sqlalchemy as sa

revision = 'f6a7b8c9d0e2'
down_revision = 'e5f6a7b8c9d0'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'finished_goods_unit',
        sa.Column('unit_id', sa.Unicode(length=64), nullable=False),
        sa.Column('unit_code', sa.Unicode(length=64), nullable=False),
        sa.Column('unit_type', sa.Unicode(length=16), nullable=False),
        sa.Column('finished_product_id', sa.Unicode(length=64), sa.ForeignKey('finished_product.finished_product_id'), nullable=True),
        sa.Column('product_name', sa.Unicode(length=255), nullable=True),
        sa.Column('lot_code', sa.Unicode(length=64), nullable=True),
        sa.Column('quantity', sa.Float(), nullable=False, server_default='0'),
        sa.Column('status', sa.Unicode(length=255), nullable=False, server_default='stored'),
        sa.Column('location_id', sa.Unicode(length=64), sa.ForeignKey('wms_location.loc_id'), nullable=True),
        sa.Column('created_by', sa.Unicode(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('shipped_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('shipment_id', sa.Unicode(length=64), sa.ForeignKey('shipment.shipment_id'), nullable=True),
        sa.Column('ship_to_id', sa.Unicode(length=64), sa.ForeignKey('ship_to_location.ship_to_id'), nullable=True),
        sa.PrimaryKeyConstraint('unit_id'),
    )
    op.create_index('ix_finished_goods_unit_unit_code', 'finished_goods_unit', ['unit_code'], unique=True)
    op.create_index('ix_finished_goods_unit_unit_type', 'finished_goods_unit', ['unit_type'])
    op.create_index('ix_finished_goods_unit_finished_product_id', 'finished_goods_unit', ['finished_product_id'])
    op.create_index('ix_finished_goods_unit_status', 'finished_goods_unit', ['status'])
    op.create_index('ix_finished_goods_unit_location_id', 'finished_goods_unit', ['location_id'])
    op.create_index('ix_finished_goods_unit_shipment_id', 'finished_goods_unit', ['shipment_id'])
    op.create_index('ix_finished_goods_unit_ship_to_id', 'finished_goods_unit', ['ship_to_id'])

    op.drop_table('shipment_line')
    op.drop_table('wms_case')
    op.drop_table('pallet')

    with op.batch_alter_table('finished_product') as batch_op:
        batch_op.alter_column('units_per_case', new_column_name='pack_size')
        batch_op.add_column(sa.Column('unit_type', sa.Unicode(length=16), nullable=False, server_default='vi'))


def downgrade() -> None:
    with op.batch_alter_table('finished_product') as batch_op:
        batch_op.drop_column('unit_type')
        batch_op.alter_column('pack_size', new_column_name='units_per_case')
    op.drop_table('finished_goods_unit')
