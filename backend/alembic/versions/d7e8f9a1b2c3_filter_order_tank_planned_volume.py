"""kế hoạch dịch lọc riêng từng tank (lệnh lọc nhỏ)

Revision ID: d7e8f9a1b2c3
Revises: c6d7e8f9a1b2
Create Date: 2026-07-18

- filter_order_tank: thêm planned_v_dich_hl (kế hoạch dịch lọc RIÊNG của tank này, khai báo
  lúc lập lệnh nhỏ) — FilterOrder.planned_volume_hl giờ = tổng planned_v_dich_hl của các
  dòng "template" (filter_id IS NULL) thuộc lệnh nhỏ đó, thay vì người dùng gõ tay 1 số tổng.
"""
from alembic import op
import sqlalchemy as sa

revision = 'd7e8f9a1b2c3'
down_revision = 'c6d7e8f9a1b2'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('filter_order_tank', sa.Column('planned_v_dich_hl', sa.Float(), nullable=False, server_default='0'))


def downgrade() -> None:
    op.drop_column('filter_order_tank', 'planned_v_dich_hl')
