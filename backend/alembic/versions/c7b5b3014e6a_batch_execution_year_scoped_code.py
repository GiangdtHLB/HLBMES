"""batch_execution.batch_code: unique theo năm (batch_year), không phải toàn hệ thống

Revision ID: c7b5b3014e6a
Revises: 5511d69dd844
Create Date: 2026-09-02

- Mirror chính xác b4c5d6e7f8b0_year_scoped_code_uniqueness.py (đã áp dụng cho brew_code/
  lm_code/filter_code/bottle_code...): thêm cột "batch_year" (snapshot năm tại lúc tạo mẻ, lấy
  từ created_at — cột này luôn NOT NULL nên không cần fallback như ferment_record) + đổi UNIQUE
  INDEX đơn trên batch_code thành UniqueConstraint(batch_year, batch_code) + giữ 1 index thường
  (không unique) trên batch_code để tra cứu vẫn nhanh.
- Yêu cầu người dùng 2026-09-02: "Ép định dạng số nguyên cho mẻ từ giờ trở đi và khi hết năm
  thì sẽ tự tính lại từ đầu... năm sau sẽ lặp lại được" — validate số nguyên nằm ở
  services/batches.py::create_batch (tầng service, không phải migration này); migration chỉ lo
  phần schema cho phép TRÙNG mã giữa các năm khác nhau.
- Dữ liệu cũ (mã dạng chữ như "B-LIVEWIP1" tạo trước ràng buộc số nguyên) KHÔNG bị đụng tới,
  chỉ backfill batch_year theo created_at — vẫn hợp lệ vì validate số nguyên chỉ áp dụng cho
  bản ghi tạo MỚI qua service, không retro-fit dữ liệu cũ.
- SQLite không cho DROP UNIQUE INDEX khai báo inline, phải tạo lại bảng (batch_alter_table
  recreate='auto') — giống hệt migration mẫu.
"""
from alembic import op
import sqlalchemy as sa

revision = 'c7b5b3014e6a'
down_revision = '5511d69dd844'
branch_labels = None
depends_on = None


def _year_expr(dialect, date_col):
    if dialect == "sqlite":
        return f"CAST(strftime('%Y', {date_col}) AS INTEGER)"
    if dialect == "postgresql":
        return f"EXTRACT(YEAR FROM {date_col})"
    return f"YEAR({date_col})"   # mssql & mặc định


def upgrade() -> None:
    d = op.get_bind().dialect.name
    op.add_column('batch_execution', sa.Column('batch_year', sa.Integer(), nullable=True))
    op.execute(f"UPDATE batch_execution SET batch_year = {_year_expr(d, 'created_at')}")
    with op.batch_alter_table('batch_execution', recreate='auto') as batch_op:
        batch_op.alter_column('batch_year', existing_type=sa.Integer(), nullable=False)
        batch_op.drop_index('ix_batch_execution_batch_code')
        batch_op.create_index(op.f('ix_batch_execution_batch_code'), ['batch_code'], unique=False)
        batch_op.create_index(op.f('ix_batch_execution_batch_year'), ['batch_year'], unique=False)
        batch_op.create_unique_constraint('uq_batch_execution_year_code', ['batch_year', 'batch_code'])


def downgrade() -> None:
    with op.batch_alter_table('batch_execution', recreate='auto') as batch_op:
        batch_op.drop_constraint('uq_batch_execution_year_code', type_='unique')
        batch_op.drop_index(op.f('ix_batch_execution_batch_year'))
        batch_op.drop_index(op.f('ix_batch_execution_batch_code'))
        batch_op.create_index('ix_batch_execution_batch_code', 'batch_execution', ['batch_code'], unique=True)
        batch_op.drop_column('batch_year')
