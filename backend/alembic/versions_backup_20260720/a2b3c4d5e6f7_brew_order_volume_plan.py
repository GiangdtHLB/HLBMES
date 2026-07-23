"""brew_order: thêm sản lượng nấu kế hoạch (hl) + sai số cho phép

Revision ID: a2b3c4d5e6f7
Revises: f6a7b8c9d0ec
Create Date: 2026-07-18

- brew_order.planned_volume_hl / volume_tolerance_hl — mirror filter_order (xem
  c3d4e5f6a7b8_filter_order_volume_plan.py): 1 lệnh nấu có thể có nhiều mã nấu (nhiều tank
  lên men), sản lượng thực tế (BrewRecord.volume_hl) cộng dồn qua các mã nấu, so với kế
  hoạch ±sai số để tính lệnh đã hoàn thành hay chưa (xem services/brew_order.py::_is_complete).
  Khác planned_volume_l (lít, dùng để scale định mức NVL theo BOM) — planned_volume_hl (hl)
  chỉ dùng để so với sản lượng nấu thật, không liên quan BOM.
"""
from alembic import op
import sqlalchemy as sa

revision = 'a2b3c4d5e6f7'
down_revision = 'f6a7b8c9d0ec'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('brew_order', sa.Column('planned_volume_hl', sa.Float(), nullable=False, server_default='0'))
    op.add_column('brew_order', sa.Column('volume_tolerance_hl', sa.Float(), nullable=False, server_default='0'))


def downgrade() -> None:
    with op.batch_alter_table('brew_order') as batch_op:
        batch_op.drop_column('volume_tolerance_hl')
        batch_op.drop_column('planned_volume_hl')
