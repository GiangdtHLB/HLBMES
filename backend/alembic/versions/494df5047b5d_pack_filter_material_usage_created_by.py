"""batch_pack_lot_material_usage / batch_filter_lot_material_usage created_by

Revision ID: 494df5047b5d
Revises: 6855852e132d
Create Date: 2026-09-16 22:50:00.000000

Cột mới, nullable — "Người nhập" cho từng dòng nguyên liệu cấp cho lô lọc/lô thành phẩm
(yêu cầu người dùng 2026-09-16: "Nguyên liệu cấp cho lọc, chiết ... cũng phải thêm thông tin
người nhập, ngày giờ nhập" — created_at đã có sẵn, chỉ thiếu created_by). Dữ liệu cũ để NULL
(không suy đoán được ai đã nhập trước khi có cột này)."""
from alembic import op
import sqlalchemy as sa


revision = '494df5047b5d'
down_revision = '6855852e132d'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('batch_pack_lot_material_usage') as batch_op:
        batch_op.add_column(sa.Column('created_by', sa.Unicode(255), nullable=True))
    with op.batch_alter_table('batch_filter_lot_material_usage') as batch_op:
        batch_op.add_column(sa.Column('created_by', sa.Unicode(255), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('batch_filter_lot_material_usage') as batch_op:
        batch_op.drop_column('created_by')
    with op.batch_alter_table('batch_pack_lot_material_usage') as batch_op:
        batch_op.drop_column('created_by')
