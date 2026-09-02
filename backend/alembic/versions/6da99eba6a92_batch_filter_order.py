"""batch_filter_order

Revision ID: 6da99eba6a92
Revises: de2bb6b4548b
Create Date: 2026-08-30 00:00:00.000000

Thêm "Lệnh lọc" (BatchFilterOrder + BatchFilterOrderSource) cho pipeline "Mẻ sản xuất" — mirror
FilterOrder/FilterOrderTank của module Nấu-Lọc-Chiết cũ (khai báo nguồn TRƯỚC, chọn lệnh lọc còn
dùng được khi tạo Lô lọc thật thay vì tự chọn lại nguồn). Thêm cột order_id (nullable) vào
batch_filter_lot để biết Lô lọc nào được tạo từ lệnh nào — batch_filter_lot tạo thủ công (không
qua lệnh lọc) vẫn hợp lệ, order_id để NULL.
"""
from alembic import op
import sqlalchemy as sa


revision = '6da99eba6a92'
down_revision = 'de2bb6b4548b'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'batch_filter_order',
        sa.Column('order_id', sa.Unicode(length=64), primary_key=True),
        sa.Column('order_code', sa.Unicode(length=64), nullable=False),
        sa.Column('order_year', sa.Integer(), nullable=False),
        sa.Column('blend_mode', sa.Unicode(length=32), nullable=False),
        sa.Column('planned_volume_hl', sa.Float(), nullable=False),
        sa.Column('volume_tolerance_hl', sa.Float(), nullable=False),
        sa.Column('beer_type_id', sa.Unicode(length=64), nullable=True),
        sa.Column('finished_product_id', sa.Unicode(length=64), nullable=True),
        sa.Column('note', sa.UnicodeText(), nullable=True),
        sa.Column('created_by', sa.Unicode(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('locked', sa.Boolean(), nullable=False),
        sa.Column('locked_by', sa.Unicode(length=255), nullable=True),
        sa.Column('locked_at', sa.DateTime(), nullable=True),
        sa.UniqueConstraint('order_year', 'order_code', name='uq_batch_filter_order_year_code'),
    )
    op.create_index('ix_batch_filter_order_order_code', 'batch_filter_order', ['order_code'])
    op.create_index('ix_batch_filter_order_order_year', 'batch_filter_order', ['order_year'])
    op.create_index('ix_batch_filter_order_beer_type_id', 'batch_filter_order', ['beer_type_id'])
    op.create_index('ix_batch_filter_order_finished_product_id', 'batch_filter_order', ['finished_product_id'])

    op.create_table(
        'batch_filter_order_source',
        sa.Column('link_id', sa.Unicode(length=64), primary_key=True),
        sa.Column('order_id', sa.Unicode(length=64), nullable=False),
        sa.Column('source_type', sa.Unicode(length=16), nullable=False),
        sa.Column('source_tank_id', sa.Unicode(length=64), nullable=True),
        sa.Column('source_filter_lot_id', sa.Unicode(length=64), nullable=True),
        sa.Column('reason', sa.UnicodeText(), nullable=True),
        sa.Column('planned_v_dich_hl', sa.Float(), nullable=False),
        sa.Column('seq', sa.Integer(), nullable=False),
    )
    op.create_index('ix_batch_filter_order_source_order_id', 'batch_filter_order_source', ['order_id'])
    op.create_index('ix_batch_filter_order_source_source_tank_id', 'batch_filter_order_source', ['source_tank_id'])
    op.create_index('ix_batch_filter_order_source_source_filter_lot_id', 'batch_filter_order_source',
                    ['source_filter_lot_id'])

    op.add_column('batch_filter_lot', sa.Column('order_id', sa.Unicode(length=64), nullable=True))
    op.create_index('ix_batch_filter_lot_order_id', 'batch_filter_lot', ['order_id'])


def downgrade() -> None:
    op.drop_index('ix_batch_filter_lot_order_id', table_name='batch_filter_lot')
    op.drop_column('batch_filter_lot', 'order_id')
    op.drop_table('batch_filter_order_source')
    op.drop_table('batch_filter_order')
