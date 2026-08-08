"""Loại xuất (normal/promo/return) chuyển từ Shipment (header) sang từng dòng FinishedGoodsUnit

Revision ID: b7c8d9e0f1a2
Revises: a5b6c7d8e9f1
Create Date: 2026-08-06

1 phiếu xuất kho (Shipment) giờ cho phép gồm nhiều sản phẩm với "Loại xuất" khác nhau (VD 1
dòng khuyến mại + 1 dòng đổi trả + 1 dòng thường, cùng 1 nhà phân phối, 1 phiếu duy nhất) —
trước đây mỗi phiếu chỉ có 1 giá trị Shipment.shipment_type áp cho TOÀN BỘ dòng, khiến frontend
phải tách thành nhiều phiếu nếu giỏ có dòng khác loại. finished_goods_unit.shipment_line_type
lưu loại xuất CỦA CHÍNH dòng đó tại thời điểm xuất — Shipment.shipment_type (cột cũ) vẫn giữ
lại, nay chỉ còn ý nghĩa tóm tắt (xem services/wms.py::create_shipment).
"""
from alembic import op
import sqlalchemy as sa

revision = 'b7c8d9e0f1a2'
down_revision = 'a5b6c7d8e9f1'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('finished_goods_unit',
                   sa.Column('shipment_line_type', sa.Unicode(length=32), nullable=True))
    op.create_index('ix_finished_goods_unit_shipment_line_type', 'finished_goods_unit',
                     ['shipment_line_type'])


def downgrade() -> None:
    op.drop_index('ix_finished_goods_unit_shipment_line_type', table_name='finished_goods_unit')
    op.drop_column('finished_goods_unit', 'shipment_line_type')
