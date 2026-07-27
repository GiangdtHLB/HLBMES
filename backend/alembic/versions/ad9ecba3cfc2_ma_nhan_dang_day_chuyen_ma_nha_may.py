"""Ma nhan dang day chuyen + ma nha may

Revision ID: ad9ecba3cfc2
Revises: f90aea3eaf40
Create Date: 2026-07-26 23:31:04.136194

- production_line.identification_code: mã nhận dạng dây chuyền (kind="line") in/dập trên bao
  bì thực tế — khác với `code` (mã nội bộ dùng để tham chiếu trong hệ thống), giúp truy vết
  ngoài thị trường sản phẩm được chiết ở dây chuyền nào.
- ops_setting.factory_code: mã nhận dạng nhà máy (cấu hình toàn hệ thống, 1 dòng duy nhất),
  khai báo ở Danh mục cùng "Cài đặt vận hành" — giúp truy vết sản phẩm được chiết từ nhà máy nào.
"""
from alembic import op
import sqlalchemy as sa


revision = 'ad9ecba3cfc2'
down_revision = 'f90aea3eaf40'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('production_line', sa.Column('identification_code', sa.Unicode(length=32), nullable=True))
    op.add_column('ops_setting', sa.Column('factory_code', sa.Unicode(length=32), nullable=True))


def downgrade() -> None:
    op.drop_column('ops_setting', 'factory_code')
    op.drop_column('production_line', 'identification_code')
