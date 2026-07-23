"""Lệnh lọc — filter_order/filter_order_tank + filter_record.filter_order_id

Revision ID: c5d6e7f8a9b0
Revises: b4c5d6e7f8a9
Create Date: 2026-07-17

- filter_order: Lệnh lọc (không phối = 1 tank, phối = nhiều tank), lập trước, chọn 1 lệnh
  CHƯA DÙNG khi tạo bản ghi lọc (mirror BrewOrder/Lệnh nấu).
- filter_order_tank: 1 dòng cho mỗi tank lên men tham gia lệnh lọc — kết quả lọc (giờ kết
  thúc/dịch nha lọc/nước bài khí) điền RIÊNG cho từng dòng khi vận hành bấm "Kết thúc" cho
  tank đó; FilterRecord tổng hợp (sum) các dòng này.
- filter_record.filter_order_id: liên kết tới lệnh lọc đã dùng để tạo bản ghi này.
"""
from alembic import op
import sqlalchemy as sa

revision = 'c5d6e7f8a9b0'
down_revision = 'b4c5d6e7f8a9'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'filter_order',
        sa.Column('filter_order_id', sa.Unicode(length=64), nullable=False),
        sa.Column('order_code', sa.Unicode(length=64), nullable=False),
        sa.Column('blend_mode', sa.Unicode(length=32), nullable=False),
        sa.Column('note', sa.UnicodeText(), nullable=True),
        sa.Column('created_by', sa.Unicode(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('filter_order_id'),
    )
    op.create_index(op.f('ix_filter_order_order_code'), 'filter_order', ['order_code'], unique=True)

    op.create_table(
        'filter_order_tank',
        sa.Column('line_id', sa.Unicode(length=64), nullable=False),
        sa.Column('filter_order_id', sa.Unicode(length=64), nullable=False),
        sa.Column('ferment_id', sa.Unicode(length=64), nullable=False),
        sa.Column('seq', sa.Integer(), nullable=False),
        sa.Column('ended_at', sa.DateTime(), nullable=True),
        sa.Column('v_dich_hl', sa.Float(), nullable=True),
        sa.Column('nuoc_bai_khi_hl', sa.Float(), nullable=True),
        sa.ForeignKeyConstraint(['filter_order_id'], ['filter_order.filter_order_id']),
        sa.ForeignKeyConstraint(['ferment_id'], ['ferment_record.ferment_id']),
        sa.PrimaryKeyConstraint('line_id'),
    )
    op.create_index(op.f('ix_filter_order_tank_filter_order_id'), 'filter_order_tank', ['filter_order_id'])
    op.create_index(op.f('ix_filter_order_tank_ferment_id'), 'filter_order_tank', ['ferment_id'])

    with op.batch_alter_table('filter_record') as batch_op:
        batch_op.add_column(sa.Column('filter_order_id', sa.Unicode(length=64), nullable=True))
        batch_op.create_foreign_key('fk_filter_record_filter_order', 'filter_order', ['filter_order_id'], ['filter_order_id'])
        batch_op.create_index(op.f('ix_filter_record_filter_order_id'), ['filter_order_id'])


def downgrade() -> None:
    with op.batch_alter_table('filter_record') as batch_op:
        batch_op.drop_index(op.f('ix_filter_record_filter_order_id'))
        batch_op.drop_constraint('fk_filter_record_filter_order', type_='foreignkey')
        batch_op.drop_column('filter_order_id')
    op.drop_index(op.f('ix_filter_order_tank_ferment_id'), table_name='filter_order_tank')
    op.drop_index(op.f('ix_filter_order_tank_filter_order_id'), table_name='filter_order_tank')
    op.drop_table('filter_order_tank')
    op.drop_index(op.f('ix_filter_order_order_code'), table_name='filter_order')
    op.drop_table('filter_order')
