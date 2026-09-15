"""batch_pack_lot_material_usage: thêm supply_date (Ngày cấp)

Revision ID: a8201554dd44
Revises: 6c148ccb1b06
Create Date: 2026-09-16 00:14:34.487248

Cột mới, nullable — "Ngày cấp" cho từng dòng nguyên liệu đã dùng ở Lô thành phẩm, LUÔN =
BatchPackLot.ended_at tại thời điểm ghi dòng (server tự gán, không nhận input — yêu cầu người
dùng 2026-09-16), lưu theo từng dòng để hiển thị nhất quán với Lọc (mirror migration
6c148ccb1b06_batch_filter_lot_material_usage_supply_date)."""
from alembic import op
import sqlalchemy as sa


revision = 'a8201554dd44'
down_revision = '6c148ccb1b06'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('batch_pack_lot_material_usage') as batch_op:
        batch_op.add_column(sa.Column('supply_date', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('batch_pack_lot_material_usage') as batch_op:
        batch_op.drop_column('supply_date')
