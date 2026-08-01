"""8 mã/số hiệu (mã nấu, lệnh nấu lớn/nhỏ, lô lên men, lệnh lọc lớn/nhỏ, mã lọc, mã chiết):
unique TRONG 1 năm thay vì toàn hệ thống

Revision ID: b4c5d6e7f8b0
Revises: 1f8a7f187deb
Create Date: 2026-07-31

- Mirror chính xác cách brew_batch.batch_code đã được sửa (xem
  a2b3c4d5e6f8_brew_batch_year_scoped_unique.py): thêm 1 cột "*_year" (snapshot năm tại lúc
  tạo bản ghi — KHÔNG tính lại khi ngày liên quan bị sửa sau này) + đổi unique-index đơn trên
  cột mã thành UniqueConstraint(year, code) + giữ lại 1 index thường (không unique) trên cột
  mã để tra cứu theo mã vẫn nhanh.
- Thực tế vận hành: các mã/số hiệu này được đánh theo quy ước giấy tờ reset lại mỗi năm — năm
  nay đã dùng "N-0715" thì năm sau vẫn phải dùng lại được "N-0715", nhưng trong CÙNG 1 năm thì
  không được trùng.
- brew_record/filter_record/bottle_record dùng chính cột ngày nghiệp vụ của bảng đó
  (brew_date/filter_date/bottle_date, luôn NOT NULL). brew_master_order/brew_order/
  filter_master_order/filter_order dùng created_at (luôn NOT NULL). ferment_record dùng
  brew_date nếu có, nếu không (API /ferments độc lập không bắt buộc) rơi về kt_date, cuối
  cùng rơi về năm hiện tại của lúc chạy migration (rất hiếm, chỉ dữ liệu cũ không có cả 2).
- SQLite không cho DROP UNIQUE INDEX/constraint khai báo inline, phải tạo lại bảng
  (batch_alter_table recreate='auto') — giống hệt migration mẫu.
"""
from alembic import op
import sqlalchemy as sa

revision = 'b4c5d6e7f8b0'
down_revision = '1f8a7f187deb'
branch_labels = None
depends_on = None


def _year_expr(dialect, date_col):
    if dialect == "sqlite":
        return f"CAST(strftime('%Y', {date_col}) AS INTEGER)"
    if dialect == "postgresql":
        return f"EXTRACT(YEAR FROM {date_col})"
    return f"YEAR({date_col})"   # mssql & mặc định


# (table, code_col, year_col, sql_expr_for_year_value, uq_name, old_unique_index_name)
_SIMPLE = [
    ("brew_record", "brew_code", "brew_year", "brew_date", "uq_brew_record_year_code", "ix_brew_record_brew_code"),
    ("brew_master_order", "order_code", "order_year", "created_at", "uq_brew_master_order_year_code", "ix_brew_master_order_order_code"),
    ("brew_order", "order_code", "order_year", "created_at", "uq_brew_order_year_code", "ix_brew_order_order_code"),
    ("filter_master_order", "order_code", "order_year", "created_at", "uq_filter_master_order_year_code", "ix_filter_master_order_order_code"),
    ("filter_order", "order_code", "order_year", "created_at", "uq_filter_order_year_code", "ix_filter_order_order_code"),
    ("filter_record", "filter_code", "filter_year", "filter_date", "uq_filter_record_year_code", "ix_filter_record_filter_code"),
    ("bottle_record", "bottle_code", "bottle_year", "bottle_date", "uq_bottle_record_year_code", "ix_bottle_record_bottle_code"),
]


def upgrade() -> None:
    _d = op.get_bind().dialect.name

    for table, code_col, year_col, date_col, uq_name, old_ix in _SIMPLE:
        op.add_column(table, sa.Column(year_col, sa.Integer(), nullable=True))
        op.execute(f"UPDATE {table} SET {year_col} = {_year_expr(_d, date_col)}")
        with op.batch_alter_table(table, recreate='auto') as batch_op:
            batch_op.alter_column(year_col, existing_type=sa.Integer(), nullable=False)
            batch_op.drop_index(old_ix)
            batch_op.create_index(op.f(f'ix_{table}_{code_col}'), [code_col], unique=False)
            batch_op.create_index(op.f(f'ix_{table}_{year_col}'), [year_col], unique=False)
            batch_op.create_unique_constraint(uq_name, [year_col, code_col])

    # ferment_record: không có created_at — COALESCE(brew_date, kt_date), fallback năm chạy
    # migration nếu cả 2 đều NULL (chỉ xảy ra với dữ liệu rất cũ/hỏng).
    op.add_column('ferment_record', sa.Column('ferment_year', sa.Integer(), nullable=True))
    _yr = _year_expr(_d, "COALESCE(brew_date, kt_date)")
    _now_year = _year_expr(_d, "CURRENT_TIMESTAMP") if _d != "sqlite" else "CAST(strftime('%Y', 'now') AS INTEGER)"
    op.execute(f"UPDATE ferment_record SET ferment_year = COALESCE({_yr}, {_now_year})")
    with op.batch_alter_table('ferment_record', recreate='auto') as batch_op:
        batch_op.alter_column('ferment_year', existing_type=sa.Integer(), nullable=False)
        batch_op.drop_index('ix_ferment_record_lm_code')
        batch_op.create_index(op.f('ix_ferment_record_lm_code'), ['lm_code'], unique=False)
        batch_op.create_index(op.f('ix_ferment_record_ferment_year'), ['ferment_year'], unique=False)
        batch_op.create_unique_constraint('uq_ferment_record_year_code', ['ferment_year', 'lm_code'])


def downgrade() -> None:
    with op.batch_alter_table('ferment_record', recreate='auto') as batch_op:
        batch_op.drop_constraint('uq_ferment_record_year_code', type_='unique')
        batch_op.drop_index(op.f('ix_ferment_record_ferment_year'))
        batch_op.drop_index(op.f('ix_ferment_record_lm_code'))
        batch_op.create_index('ix_ferment_record_lm_code', 'ferment_record', ['lm_code'], unique=True)
        batch_op.drop_column('ferment_year')

    for table, code_col, year_col, date_col, uq_name, old_ix in reversed(_SIMPLE):
        with op.batch_alter_table(table, recreate='auto') as batch_op:
            batch_op.drop_constraint(uq_name, type_='unique')
            batch_op.drop_index(op.f(f'ix_{table}_{year_col}'))
            batch_op.drop_index(op.f(f'ix_{table}_{code_col}'))
            batch_op.create_index(old_ix, [code_col], unique=True)
            batch_op.drop_column(year_col)
