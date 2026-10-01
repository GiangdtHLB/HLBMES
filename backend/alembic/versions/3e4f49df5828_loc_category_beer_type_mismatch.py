"""loc_category_beer_type_mismatch

Thêm "Loại sản phẩm" (category — Bia chai/Bia lon/Bia hơi/Bia tươi, mirror
FinishedProduct.category) làm mức tra chỉ tiêu Lọc trung gian giữa Loại bia và Sản phẩm/SKU cụ
thể — lúc lập Lệnh lọc thường CHƯA biết đúng 1 SKU (1 tank BBT có thể chiết ra nhiều SKU khác
nhau) nhưng biết chắc Loại sản phẩm (yêu cầu người dùng 2026-09-30).

Đồng thời thêm cờ `beer_type_mismatch` trên batch_filter_order/batch_filter_lot: True khi
Loại bia do người dùng CHỌN TAY khác với Loại bia suy được từ chính Dịch bia của (các) tank/lô
lọc nguồn (VD lọc phối 2 Dịch bia khác Loại bia, không có đáp án "đúng" duy nhất) — lưu lại để
biết đây KHÔNG phải Loại bia gốc thật của dịch, tránh hiểu lầm khi tra cứu/kiểm toán sau này.

Revision ID: 3e4f49df5828
Revises: c4d8e2f1a936
Create Date: 2026-09-30 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = '3e4f49df5828'
down_revision = 'c4d8e2f1a936'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('stage_qc_group') as batch_op:
        batch_op.add_column(sa.Column('category', sa.Unicode(length=64), nullable=True))
        batch_op.create_index('ix_stage_qc_group_category', ['category'])
    with op.batch_alter_table('batch_filter_order') as batch_op:
        batch_op.add_column(sa.Column('category', sa.Unicode(length=64), nullable=True))
        batch_op.create_index('ix_batch_filter_order_category', ['category'])
        batch_op.add_column(sa.Column('beer_type_mismatch', sa.Boolean(), nullable=False,
                                      server_default=sa.false()))
    with op.batch_alter_table('batch_filter_lot') as batch_op:
        batch_op.add_column(sa.Column('category', sa.Unicode(length=64), nullable=True))
        batch_op.create_index('ix_batch_filter_lot_category', ['category'])
        batch_op.add_column(sa.Column('beer_type_mismatch', sa.Boolean(), nullable=False,
                                      server_default=sa.false()))


def downgrade() -> None:
    with op.batch_alter_table('batch_filter_lot') as batch_op:
        batch_op.drop_column('beer_type_mismatch')
        batch_op.drop_index('ix_batch_filter_lot_category')
        batch_op.drop_column('category')
    with op.batch_alter_table('batch_filter_order') as batch_op:
        batch_op.drop_column('beer_type_mismatch')
        batch_op.drop_index('ix_batch_filter_order_category')
        batch_op.drop_column('category')
    with op.batch_alter_table('stage_qc_group') as batch_op:
        batch_op.drop_index('ix_stage_qc_group_category')
        batch_op.drop_column('category')
