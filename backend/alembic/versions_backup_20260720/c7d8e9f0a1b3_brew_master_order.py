"""lệnh nấu lớn / lệnh nấu nhỏ

Revision ID: c7d8e9f0a1b3
Revises: b3c4d5e6f7a9
Create Date: 2026-07-20

- brew_master_order: bảng mới — "lệnh nấu lớn" (số lệnh + phần hành chính chung: người ra
  lệnh/thực hiện/xuất hàng, căn cứ, thời gian thực hiện, biện pháp an toàn).
- brew_order: thêm master_order_id (FK -> brew_master_order, lệnh nấu lớn chứa lệnh này) +
  seq (thứ tự "Lệnh nấu nhỏ #N" trong lệnh lớn); bỏ issued_by/executor_unit/warehouse_keeper/
  reference_note/start_date/end_date/safety_note — các trường hành chính này chuyển hẳn sang
  brew_master_order (chỉ 1 lần cho cả tờ, không lặp lại theo từng dịch bia). BrewOrder giờ
  luôn là 1 "lệnh nấu nhỏ" (1 dịch bia riêng) — mọi field/FK khác giữ nguyên không đổi, mẫu
  y hệt filter_master_order/filter_order (c6d7e8f9a1b2).
"""
from alembic import op
import sqlalchemy as sa

revision = 'c7d8e9f0a1b3'
down_revision = 'b3c4d5e6f7a9'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'brew_master_order',
        sa.Column('brew_master_order_id', sa.Unicode(length=64), primary_key=True),
        sa.Column('order_code', sa.Unicode(length=64), nullable=False),
        sa.Column('issued_by', sa.Unicode(length=255), nullable=True),
        sa.Column('executor_unit', sa.Unicode(length=255), nullable=True),
        sa.Column('warehouse_keeper', sa.Unicode(length=255), nullable=True),
        sa.Column('reference_note', sa.UnicodeText(), nullable=True),
        sa.Column('start_date', sa.DateTime(timezone=True), nullable=True),
        sa.Column('end_date', sa.DateTime(timezone=True), nullable=True),
        sa.Column('safety_note', sa.UnicodeText(), nullable=True),
        sa.Column('created_by', sa.Unicode(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('locked', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('locked_by', sa.Unicode(length=255), nullable=True),
        sa.Column('locked_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index('ix_brew_master_order_order_code', 'brew_master_order', ['order_code'], unique=True)

    op.add_column('brew_order', sa.Column('master_order_id', sa.Unicode(length=64), nullable=True))
    op.add_column('brew_order', sa.Column('seq', sa.Integer(), nullable=False, server_default='1'))
    op.create_index('ix_brew_order_master_order_id', 'brew_order', ['master_order_id'])

    op.drop_column('brew_order', 'issued_by')
    op.drop_column('brew_order', 'executor_unit')
    op.drop_column('brew_order', 'warehouse_keeper')
    op.drop_column('brew_order', 'reference_note')
    op.drop_column('brew_order', 'start_date')
    op.drop_column('brew_order', 'end_date')
    op.drop_column('brew_order', 'safety_note')


def downgrade() -> None:
    op.add_column('brew_order', sa.Column('safety_note', sa.UnicodeText(), nullable=True))
    op.add_column('brew_order', sa.Column('end_date', sa.DateTime(timezone=True), nullable=True))
    op.add_column('brew_order', sa.Column('start_date', sa.DateTime(timezone=True), nullable=True))
    op.add_column('brew_order', sa.Column('reference_note', sa.UnicodeText(), nullable=True))
    op.add_column('brew_order', sa.Column('warehouse_keeper', sa.Unicode(length=255), nullable=True))
    op.add_column('brew_order', sa.Column('executor_unit', sa.Unicode(length=255), nullable=True))
    op.add_column('brew_order', sa.Column('issued_by', sa.Unicode(length=255), nullable=True))

    op.drop_index('ix_brew_order_master_order_id', table_name='brew_order')
    op.drop_column('brew_order', 'seq')
    op.drop_column('brew_order', 'master_order_id')

    op.drop_index('ix_brew_master_order_order_code', table_name='brew_master_order')
    op.drop_table('brew_master_order')
