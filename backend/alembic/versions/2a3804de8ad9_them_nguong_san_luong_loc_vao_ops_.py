"""them nguong san luong loc vao ops_setting

Revision ID: 2a3804de8ad9
Revises: 23db474e3e99
Create Date: 2026-07-28 22:28:01.218910

Ngưỡng sản lượng (hl) để phân loại 1 mẻ lọc đã kết thúc Thấp/Bình thường/Cao trên báo cáo
sản lượng lọc theo mẻ (xem services/filter_yield_report.py) — mặc định 50/150 hl.
"""
from alembic import op
import sqlalchemy as sa


revision = '2a3804de8ad9'
down_revision = '23db474e3e99'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('ops_setting', sa.Column('filter_yield_low_hl', sa.Float(),
                                           nullable=False, server_default='50.0'))
    op.add_column('ops_setting', sa.Column('filter_yield_high_hl', sa.Float(),
                                           nullable=False, server_default='150.0'))


def downgrade() -> None:
    op.drop_column('ops_setting', 'filter_yield_high_hl')
    op.drop_column('ops_setting', 'filter_yield_low_hl')
