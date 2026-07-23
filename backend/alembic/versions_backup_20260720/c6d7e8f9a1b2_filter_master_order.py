"""lệnh lọc lớn / lệnh lọc nhỏ

Revision ID: c6d7e8f9a1b2
Revises: b5c6d7e8f9a1
Create Date: 2026-07-18

- filter_master_order: bảng mới — "lệnh lọc lớn" (số lệnh + ghi chú người lập).
- filter_order: thêm master_order_id (FK -> filter_master_order, lệnh lọc lớn chứa lệnh
  này) + seq (thứ tự "Lệnh lọc nhỏ #N" trong lệnh lớn). FilterOrder giờ luôn là 1 "lệnh lọc
  nhỏ" thuộc về 1 lệnh lớn — mọi field/FK khác của FilterOrder giữ nguyên không đổi.
"""
from alembic import op
import sqlalchemy as sa

revision = 'c6d7e8f9a1b2'
down_revision = 'b5c6d7e8f9a1'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'filter_master_order',
        sa.Column('filter_master_order_id', sa.Unicode(length=64), primary_key=True),
        sa.Column('order_code', sa.Unicode(length=64), nullable=False),
        sa.Column('note', sa.UnicodeText(), nullable=True),
        sa.Column('created_by', sa.Unicode(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_filter_master_order_order_code', 'filter_master_order', ['order_code'], unique=True)

    op.add_column('filter_order', sa.Column('master_order_id', sa.Unicode(length=64), nullable=True))
    op.add_column('filter_order', sa.Column('seq', sa.Integer(), nullable=False, server_default='1'))
    op.create_index('ix_filter_order_master_order_id', 'filter_order', ['master_order_id'])


def downgrade() -> None:
    op.drop_index('ix_filter_order_master_order_id', table_name='filter_order')
    op.drop_column('filter_order', 'seq')
    op.drop_column('filter_order', 'master_order_id')
    op.drop_index('ix_filter_master_order_order_code', table_name='filter_master_order')
    op.drop_table('filter_master_order')
