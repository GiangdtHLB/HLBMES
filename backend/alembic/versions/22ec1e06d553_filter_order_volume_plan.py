"""filter_order: thay "chọn tank BBT dự kiến" bằng "thể tích dịch lọc kế hoạch"

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-07-17

- Bỏ filter_order_bbt (chọn tank BBT dự kiến, vừa thêm migration trước) — không cần chọn
  tank thành phẩm trước nữa, tank BBT chọn tự do lúc tạo bản ghi lọc như ban đầu.
- filter_order.planned_volume_hl / volume_tolerance_hl — thể tích dịch lọc kế hoạch (đã gồm
  nước bài khí) + sai số cho phép; nhiều bản ghi lọc ("mẻ lọc") của cùng 1 lệnh cộng dồn
  v_beer_hl lại, so với kế hoạch ±sai số để tính lệnh đã hoàn thành hay chưa (xem
  services/filter_order.py::_is_complete).
"""
from alembic import op
import sqlalchemy as sa

revision = '22ec1e06d553'
down_revision = '1e55b05f84fd'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_index('ix_filter_order_bbt_filter_order_id', table_name='filter_order_bbt')
    op.drop_table('filter_order_bbt')

    op.add_column('filter_order', sa.Column('planned_volume_hl', sa.Float(), nullable=False, server_default='0'))
    op.add_column('filter_order', sa.Column('volume_tolerance_hl', sa.Float(), nullable=False, server_default='0'))


def downgrade() -> None:
    with op.batch_alter_table('filter_order') as batch_op:
        batch_op.drop_column('volume_tolerance_hl')
        batch_op.drop_column('planned_volume_hl')

    op.create_table(
        'filter_order_bbt',
        sa.Column('line_id', sa.Unicode(64), primary_key=True),
        sa.Column('filter_order_id', sa.Unicode(64), sa.ForeignKey('filter_order.filter_order_id'), nullable=False),
        sa.Column('seq', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('tank_code', sa.Unicode(255), nullable=False),
    )
    op.create_index('ix_filter_order_bbt_filter_order_id', 'filter_order_bbt', ['filter_order_id'])
