"""filter_record: thêm nước bài khí — Dịch nha lọc/Sản lượng lọc điền khi kết thúc lọc

Revision ID: b4c5d6e7f8a9
Revises: a3b4c5d6e7f8
Create Date: 2026-07-16

- Trước đây "Dịch nha lọc/hl" (v_dich_hl) và "Sản lượng lọc/hl" (v_beer_hl) phải nhập tay
  ngay lúc tạo bản ghi lọc. Nay vận hành bắt đầu lọc mà chưa cần biết 2 số này — chỉ điền
  "Dịch nha lọc" + "Nước bài khí" (nuoc_bai_khi_hl, cột mới) khi bấm "Kết thúc"; sản lượng
  lọc tự tính = dịch nha lọc + nước bài khí (xem finish_filter, routers/brewing.py).
"""
from alembic import op
import sqlalchemy as sa

revision = 'b4c5d6e7f8a9'
down_revision = 'a3b4c5d6e7f8'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('filter_record') as batch_op:
        batch_op.add_column(sa.Column('nuoc_bai_khi_hl', sa.Float(), nullable=False, server_default='0'))


def downgrade() -> None:
    with op.batch_alter_table('filter_record') as batch_op:
        batch_op.drop_column('nuoc_bai_khi_hl')
