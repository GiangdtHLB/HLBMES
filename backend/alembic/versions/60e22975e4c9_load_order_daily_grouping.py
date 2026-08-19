"""load_order_daily_grouping

Revision ID: 60e22975e4c9
Revises: 2d59542db9d4
Create Date: 2026-08-17 22:57:34.800306

- load_order: "Lệnh đóng hàng" theo ngày — 1 file Excel import tạo 1 (hoặc 2, nếu file có cả
  2 sheet HL/ĐM) LoadOrder, gộp tất cả xe (LoadSlip) của sheet đó trong lần import — dùng để
  in lại đúng layout bảng ngang của file Excel gốc.
- load_slip.load_order_id: liên kết mỗi Biên bản bàn giao (xe) với đúng 1 Lệnh đóng hàng.
"""
from alembic import op
import sqlalchemy as sa


revision = '60e22975e4c9'
down_revision = '2d59542db9d4'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'load_order',
        sa.Column('load_order_id', sa.Unicode(length=64), nullable=False),
        sa.Column('order_code', sa.Unicode(length=64), nullable=False),
        sa.Column('sheet_type', sa.Unicode(length=16), nullable=False),
        sa.Column('shift_label', sa.Unicode(length=64), nullable=True),
        sa.Column('order_date', sa.DateTime(timezone=True), nullable=True),
        sa.Column('source_file_name', sa.Unicode(length=255), nullable=True),
        sa.Column('created_by', sa.Unicode(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('load_order_id'),
    )
    op.create_index(op.f('ix_load_order_order_code'), 'load_order', ['order_code'], unique=True)
    op.create_index(op.f('ix_load_order_sheet_type'), 'load_order', ['sheet_type'], unique=False)

    op.add_column('load_slip', sa.Column('load_order_id', sa.Unicode(length=64), nullable=True))
    with op.batch_alter_table('load_slip') as batch_op:
        batch_op.create_foreign_key(
            'fk_load_slip_load_order', 'load_order', ['load_order_id'], ['load_order_id'])
    op.create_index(op.f('ix_load_slip_load_order_id'), 'load_slip', ['load_order_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_load_slip_load_order_id'), table_name='load_slip')
    with op.batch_alter_table('load_slip') as batch_op:
        batch_op.drop_constraint('fk_load_slip_load_order', type_='foreignkey')
    op.drop_column('load_slip', 'load_order_id')

    op.drop_index(op.f('ix_load_order_sheet_type'), table_name='load_order')
    op.drop_index(op.f('ix_load_order_order_code'), table_name='load_order')
    op.drop_table('load_order')
