"""brew_batch.batch_code: unique toàn hệ thống trong 1 năm (không phải riêng từng mã nấu)

Revision ID: a2b3c4d5e6f8
Revises: f8a9b0c1d2e3
Create Date: 2026-07-18

- Đảo ngược lại quyết định trước (f8a9b0c1d2e3): thực tế vận hành yêu cầu số mẻ (batch_code)
  KHÔNG được trùng giữa 2 mã nấu khác nhau — số mẻ là 1 dãy đếm chung toàn nhà máy, chỉ
  reset lại từ đầu mỗi năm (không phải theo từng mã nấu). Thêm cột batch_year (năm của
  started_at) và đổi khóa duy nhất sang (batch_year, batch_code) — vừa khóa trùng số mẻ
  trong cùng năm, vừa cho phép đánh lại số mẻ từ 1 khi sang năm mới.
- SQLite không cho DROP UNIQUE constraint khai báo inline, phải tạo lại bảng.
"""
from alembic import op
import sqlalchemy as sa

revision = 'a2b3c4d5e6f8'
down_revision = 'b3c4d5e6f7a9'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('brew_batch', sa.Column('batch_year', sa.Integer(), nullable=True))
    op.execute("""
        UPDATE brew_batch SET batch_year = CAST(
            strftime('%Y', COALESCE(started_at, created_at)) AS INTEGER
        )
    """)
    with op.batch_alter_table('brew_batch', recreate='always') as batch_op:
        batch_op.alter_column('batch_year', nullable=False)
        batch_op.drop_constraint('uq_brew_batch_brew_code', type_='unique')
        batch_op.create_index(op.f('ix_brew_batch_batch_year'), ['batch_year'], unique=False)
        batch_op.create_unique_constraint('uq_brew_batch_year_code', ['batch_year', 'batch_code'])


def downgrade() -> None:
    with op.batch_alter_table('brew_batch', recreate='always') as batch_op:
        batch_op.drop_constraint('uq_brew_batch_year_code', type_='unique')
        batch_op.drop_index(op.f('ix_brew_batch_batch_year'))
        batch_op.create_unique_constraint('uq_brew_batch_brew_code', ['brew_id', 'batch_code'])
        batch_op.drop_column('batch_year')
