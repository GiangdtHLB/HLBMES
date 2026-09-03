"""workorder_brewhouse_line

Revision ID: 3f7b2c9a1e6d
Revises: 9a4d2e6c1f8b
Create Date: 2026-08-31 00:00:00.000000

Chọn Dây chuyền nấu (ProductionLine kind="brewhouse") ngay lúc lập Lệnh sản xuất (điều độ)
thay vì chọn lại lúc "Phát mẻ" — thêm work_order.brewhouse_line_id.
"""
from alembic import op
import sqlalchemy as sa


revision = '3f7b2c9a1e6d'
down_revision = '9a4d2e6c1f8b'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('work_order', sa.Column('brewhouse_line_id', sa.Unicode(length=64), nullable=True))
    op.create_index('ix_work_order_brewhouse_line_id', 'work_order', ['brewhouse_line_id'])


def downgrade() -> None:
    op.drop_index('ix_work_order_brewhouse_line_id', table_name='work_order')
    op.drop_column('work_order', 'brewhouse_line_id')
