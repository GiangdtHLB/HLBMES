"""batch_filter_lot_material_usage: thêm supply_date (Ngày cấp)

Revision ID: 6c148ccb1b06
Revises: d921c6f199cd
Create Date: 2026-09-15 23:04:21.858503

Cột mới, nullable, không ràng buộc gì — "Ngày cấp" cho từng dòng nguyên liệu đã dùng ở Lô lọc,
mốc HIỆU LỰC dùng để trừ tồn kho phân xưởng (truyền vào warehouse_svc.issue(issued_at=...)),
KHÁC created_at (giờ ghi vào hệ thống, không sửa được). Mirror requested_receipt_date
(migration c749b25aba5c) — cùng nguyên tắc "ngày hiệu lực" tách khỏi "ngày lập phiếu", áp dụng
cho Lọc (yêu cầu người dùng 2026-09-15: "ngày cấp chính là ngày trừ vào tồn kho... không được
lấy ngày tạo làm ngày trừ tồn kho"). Chiết không cần cột mới — đã có BatchPackLot.pack_date sẵn
ở mức lô (không phải mức từng dòng nguyên liệu), chỉ cần nối vào issue() (xem service).
"""
from alembic import op
import sqlalchemy as sa


revision = '6c148ccb1b06'
down_revision = 'd921c6f199cd'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('batch_filter_lot_material_usage') as batch_op:
        batch_op.add_column(sa.Column('supply_date', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('batch_filter_lot_material_usage') as batch_op:
        batch_op.drop_column('supply_date')
