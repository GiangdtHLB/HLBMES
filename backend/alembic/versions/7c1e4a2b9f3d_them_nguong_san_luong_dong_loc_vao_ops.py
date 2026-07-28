"""them nguong san luong dong loc (lit) vao ops_setting

Revision ID: 7c1e4a2b9f3d
Revises: 2a3804de8ad9
Create Date: 2026-07-28 23:50:00.000000

Ngưỡng sản lượng (lít) để phân loại từng dòng "mẻ lọc số" (1 đợt rút dịch) đã kết thúc
Thấp/Bình thường/Cao trên báo cáo "Theo mẻ lọc số" (xem services/filter_yield_report.py) —
mặc định 500/2000 lít.
"""
from alembic import op
import sqlalchemy as sa


revision = '7c1e4a2b9f3d'
down_revision = '2a3804de8ad9'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('ops_setting', sa.Column('filter_line_yield_low_l', sa.Float(),
                                           nullable=False, server_default='500.0'))
    op.add_column('ops_setting', sa.Column('filter_line_yield_high_l', sa.Float(),
                                           nullable=False, server_default='2000.0'))


def downgrade() -> None:
    op.drop_column('ops_setting', 'filter_line_yield_high_l')
    op.drop_column('ops_setting', 'filter_line_yield_low_l')
