"""filter_order: chia sản lượng ra nhiều tank BBT (nhiều "lệnh nhỏ" mỗi lệnh lọc)

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-07-17

- filter_order.planned_bbt (string đơn, vừa thêm) bị bỏ, thay bằng bảng filter_order_bbt
  (list) — 1 lệnh lọc có thể khai nhiều tank BBT dự kiến, mỗi tank ứng với 1 FilterRecord
  riêng (xem routers/brewing.py::add_filter).
- filter_order_tank.filter_id (nullable FK filter_record) — phân biệt dòng "template" (tạo
  lúc lập lệnh, filter_id NULL) với dòng "kết thúc" nhân bản riêng cho từng FilterRecord khi
  1 lệnh có nhiều bản ghi lọc (tránh double-count số liệu giữa các bản ghi dùng chung lệnh).
"""
from alembic import op
import sqlalchemy as sa

revision = 'b2c3d4e5f6a7'
down_revision = 'a1b2c3d4e5f6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('filter_order') as batch_op:
        batch_op.drop_column('planned_bbt')

    op.create_table(
        'filter_order_bbt',
        sa.Column('line_id', sa.Unicode(64), primary_key=True),
        sa.Column('filter_order_id', sa.Unicode(64), sa.ForeignKey('filter_order.filter_order_id'), nullable=False),
        sa.Column('seq', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('tank_code', sa.Unicode(255), nullable=False),
    )
    op.create_index('ix_filter_order_bbt_filter_order_id', 'filter_order_bbt', ['filter_order_id'])

    op.add_column('filter_order_tank', sa.Column('filter_id', sa.Unicode(64), sa.ForeignKey('filter_record.filter_id'), nullable=True))
    op.create_index('ix_filter_order_tank_filter_id', 'filter_order_tank', ['filter_id'])


def downgrade() -> None:
    op.drop_index('ix_filter_order_tank_filter_id', table_name='filter_order_tank')
    with op.batch_alter_table('filter_order_tank') as batch_op:
        batch_op.drop_column('filter_id')

    op.drop_index('ix_filter_order_bbt_filter_order_id', table_name='filter_order_bbt')
    op.drop_table('filter_order_bbt')

    with op.batch_alter_table('filter_order') as batch_op:
        batch_op.add_column(sa.Column('planned_bbt', sa.Unicode(255), nullable=True))
