"""batch_pack_lot.pack_allocations — phân bổ quy cách đóng gói pallet khai trước Duyệt KCS

Revision ID: f7e8d9c0b1a2
Revises: d3c4b5a69788
Create Date: 2026-09-20

Cột mới, nullable — nhân viên chiết khai phân bổ quy cách đóng gói pallet (list [{"spec_id",
"quantity"}]) NGAY trong lúc chiết, không chờ Duyệt KCS/Giám đốc duyệt nhập kho (yêu cầu người
dùng 2026-09-20: "hiện ra luôn để nhân viên chiết thực hiện" — tách "Duyệt KCS" và "Tạo pallet
nhập kho" thành 2 luồng độc lập). Dữ liệu cũ để NULL."""
from alembic import op
import sqlalchemy as sa

revision = 'f7e8d9c0b1a2'
down_revision = 'd3c4b5a69788'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('batch_pack_lot') as batch_op:
        batch_op.add_column(sa.Column('pack_allocations', sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('batch_pack_lot') as batch_op:
        batch_op.drop_column('pack_allocations')
