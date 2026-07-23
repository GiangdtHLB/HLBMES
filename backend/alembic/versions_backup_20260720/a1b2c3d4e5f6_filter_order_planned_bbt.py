"""filter_order: thêm planned_bbt (Tank TP dự kiến) + kcs_lot_no (Số lô KCS)

Revision ID: a1b2c3d4e5f6
Revises: d6e7f8a9b0c1
Create Date: 2026-07-17

- planned_bbt: tank BBT thành phẩm dự kiến, chọn lúc lập lệnh trong số tank đang trống/đã
  chiết hết (xem services/filter_order.py::available_bbt_tanks) — dùng để in biểu mẫu
  "LỆNH LỌC BIA", KHÔNG thay thế FilterRecord.to_bbt (tank thật khi vận hành lọc).
- kcs_lot_no: số lô KCS, người lập lệnh tự đánh số tay, không tự sinh/không validate.

Lưu ý: down_revision trỏ về 'd6e7f8a9b0c1' — id này hiện bị trùng giữa 2 file
(filter_order_material_line.py và wms_vehicle.py), một vấn đề đã biết trước migration này,
không sửa trong phạm vi migration này (xem task riêng theo dõi việc renumber lại chuỗi).
"""
from alembic import op
import sqlalchemy as sa

revision = 'a1b2c3d4e5f6'
down_revision = 'd6e7f8a9b0c1'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('filter_order', sa.Column('planned_bbt', sa.Unicode(255), nullable=True))
    op.add_column('filter_order', sa.Column('kcs_lot_no', sa.Unicode(255), nullable=True))


def downgrade() -> None:
    op.drop_column('filter_order', 'kcs_lot_no')
    op.drop_column('filter_order', 'planned_bbt')
