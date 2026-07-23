"""brew_batch.batch_code: unique theo mã nấu, không phải toàn hệ thống

Revision ID: f8a9b0c1d2e3
Revises: e7f8a9b0c1d2
Create Date: 2026-07-16

- Trước đây batch_code (số mẻ, VD "1","2","3") duy nhất TOÀN HỆ THỐNG, khiến 2 mã nấu
  khác nhau không thể cùng có "mẻ 2" (xóa mẻ 2 ở mã nấu A rồi tạo "mẻ 2" ở mã nấu B khác
  vẫn báo trùng nếu batch_code "2" đang được mã nấu C khác dùng). Đổi sang unique theo
  cặp (brew_id, batch_code) — đúng thực tế mỗi mã nấu tự đánh số mẻ riêng.
- SQLite không cho DROP một UNIQUE constraint khai báo inline trong CREATE TABLE, nên phải
  tạo lại bảng (batch_id giữ nguyên nên các FK từ brew_process_step/brew_process_log/
  brew_material_usage trỏ tới brew_batch.batch_id không bị ảnh hưởng).
"""
from alembic import op
import sqlalchemy as sa

revision = 'f8a9b0c1d2e3'
down_revision = 'e7f8a9b0c1d2'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('brew_batch', recreate='always') as batch_op:
        batch_op.drop_constraint('uq_brew_batch_batch_code', type_='unique')
        batch_op.create_index(op.f('ix_brew_batch_batch_code'), ['batch_code'], unique=False)
        batch_op.create_unique_constraint('uq_brew_batch_brew_code', ['brew_id', 'batch_code'])


def downgrade() -> None:
    with op.batch_alter_table('brew_batch', recreate='always') as batch_op:
        batch_op.drop_constraint('uq_brew_batch_brew_code', type_='unique')
        batch_op.drop_index(op.f('ix_brew_batch_batch_code'))
        batch_op.create_unique_constraint('uq_brew_batch_batch_code', ['batch_code'])
