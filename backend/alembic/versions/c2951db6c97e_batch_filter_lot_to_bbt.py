"""batch_filter_lot_to_bbt

Revision ID: c2951db6c97e
Revises: 46f029f4dffb
Create Date: 2026-08-31 00:00:00.000000

Thêm to_bbt (tank thành phẩm đích, ProductionLine kind="tank_bbt") vào batch_filter_lot —
mirror FilterRecord.to_bbt (module Nấu-Lọc-Chiết cũ). Tạo Lô lọc mới giờ bắt buộc chọn tank
thành phẩm để biết dịch lọc xong sẽ đưa vào đâu.
"""
from alembic import op
import sqlalchemy as sa


revision = 'c2951db6c97e'
down_revision = '46f029f4dffb'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('batch_filter_lot', sa.Column('to_bbt', sa.Unicode(length=255), nullable=True))
    op.create_index('ix_batch_filter_lot_to_bbt', 'batch_filter_lot', ['to_bbt'])


def downgrade() -> None:
    op.drop_index('ix_batch_filter_lot_to_bbt', table_name='batch_filter_lot')
    op.drop_column('batch_filter_lot', 'to_bbt')
