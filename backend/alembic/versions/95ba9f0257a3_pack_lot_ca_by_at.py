"""batch_pack_lot ca1/ca2/ca3 _by/_at

Revision ID: 95ba9f0257a3
Revises: 494df5047b5d
Create Date: 2026-09-16 23:05:00.000000

Cột mới, nullable — "Người nhập/ngày giờ nhập" RIÊNG cho từng ca chiết (Ca 1/2/3), để mỗi ca có
nút Lưu/Sửa/Xóa độc lập (yêu cầu người dùng 2026-09-16), mirror batch_tank_daily_reading.
measured_by/measured_at. Dữ liệu cũ để NULL."""
from alembic import op
import sqlalchemy as sa


revision = '95ba9f0257a3'
down_revision = '494df5047b5d'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('batch_pack_lot') as batch_op:
        batch_op.add_column(sa.Column('ca1_by', sa.Unicode(255), nullable=True))
        batch_op.add_column(sa.Column('ca1_at', sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column('ca2_by', sa.Unicode(255), nullable=True))
        batch_op.add_column(sa.Column('ca2_at', sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column('ca3_by', sa.Unicode(255), nullable=True))
        batch_op.add_column(sa.Column('ca3_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('batch_pack_lot') as batch_op:
        batch_op.drop_column('ca3_at')
        batch_op.drop_column('ca3_by')
        batch_op.drop_column('ca2_at')
        batch_op.drop_column('ca2_by')
        batch_op.drop_column('ca1_at')
        batch_op.drop_column('ca1_by')
