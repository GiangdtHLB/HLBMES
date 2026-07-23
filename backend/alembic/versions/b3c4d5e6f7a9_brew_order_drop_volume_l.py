"""brew_order: bỏ planned_volume_l — chỉ còn 1 trường sản lượng kế hoạch (hl)

Revision ID: b3c4d5e6f7a9
Revises: a2b3c4d5e6f7
Create Date: 2026-07-18

- planned_volume_l (lít) và planned_volume_hl (hl) trùng ý nghĩa (cùng là "sản lượng nấu
  kế hoạch", chỉ khác đơn vị) — theo yêu cầu người dùng, gộp lại chỉ còn planned_volume_hl.
  Chỗ dùng planned_volume_l để scale định mức NVL theo BOM (build_lines_from_bom) nay tự
  quy đổi planned_volume_hl * 100 ra lít khi cần (xem services/brew_order.py).
"""
from alembic import op
import sqlalchemy as sa

from app.alembic_mssql import prep_drop_columns

revision = 'b3c4d5e6f7a9'
down_revision = '55089ca00c8f'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # MSSQL: planned_volume_l được thêm kèm server_default (ràng buộc DF__) nên
    # DROP COLUMN bị chặn tới khi gỡ default trước (SQLite/Postgres: no-op).
    prep_drop_columns(op.get_bind(), "brew_order", ("planned_volume_l",))
    op.drop_column('brew_order', 'planned_volume_l')


def downgrade() -> None:
    op.add_column('brew_order', sa.Column('planned_volume_l', sa.Float(), nullable=False, server_default='0'))
