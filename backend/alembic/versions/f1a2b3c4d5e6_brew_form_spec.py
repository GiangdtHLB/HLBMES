"""Biểu mẫu công nghệ nấu đầy đủ (QT-KCS-QT-BM-05) — Quy định theo sản phẩm + ghi chép JSON

Revision ID: f1a2b3c4d5e6
Revises: d2e3f4a5b6c7
Create Date: 2026-07-10

- product.spec_json: Quy định (giá trị/mục tiêu chuẩn công nghệ nấu) theo từng dịch bia —
  chỉ admin (master.manage) sửa được, xem services/braumat_import.py::FORM_FIELDS.
- brew_process_log.manual_json: thay cho ~35 cột riêng lẻ trước đây — biểu mẫu giấy đầy
  đủ có rất nhiều trường (header + nhiệt độ từng bước + thời gian lọc/đun hoa...), lưu
  JSON để không cần migration mỗi lần thêm field. Các cột cũ (rc_gao_truoc_kg...) vẫn còn
  trong bảng nhưng không còn dùng — không xoá để tránh rủi ro trên SQLite.
"""
from alembic import op
import sqlalchemy as sa

revision = 'f1a2b3c4d5e6'
down_revision = 'd2e3f4a5b6c7'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('product', sa.Column('spec_json', sa.UnicodeText(), nullable=True))
    op.add_column('brew_process_log', sa.Column('manual_json', sa.UnicodeText(), nullable=True))


def downgrade() -> None:
    op.drop_column('brew_process_log', 'manual_json')
    op.drop_column('product', 'spec_json')
