"""Cài đặt vận hành: ngưỡng cảnh báo tuổi lô cho phép số thực (không chỉ số nguyên)

Revision ID: e1f2a3b4c5d8
Revises: d0e1f2a3b4c6
Create Date: 2026-07-22

- Đổi aging_caution_days/aging_warning_days/aging_critical_days từ Integer sang Float —
  cho phép nhập ngưỡng lẻ (vd 1.5 ngày) thay vì chỉ số ngày tròn. SQLite lưu trữ theo kiểu
  động (type affinity) nên các giá trị số thực đã được lưu đúng ngay cả trước migration này;
  migration chỉ cập nhật khai báo cột cho đúng với model (quan trọng nếu sau này đổi sang DB
  khác có kiểu dữ liệu chặt như Postgres).
"""
from alembic import op
import sqlalchemy as sa

from app.alembic_mssql import prep_drop_columns

revision = 'e1f2a3b4c5d8'
down_revision = 'd0e1f2a3b4c6'
branch_labels = None
depends_on = None

# Ngưỡng aging_* được thêm kèm server_default (30/60/90) ở d0e1f2a3b4c6 → có ràng buộc
# DF__ trên MSSQL. MSSQL từ chối ALTER COLUMN đổi kiểu khi cột còn DEFAULT phụ thuộc
# (error 5074) → phải gỡ DEFAULT trước, đổi kiểu, rồi gắn lại DEFAULT.
_AGING = (('aging_caution_days', '30'), ('aging_warning_days', '60'), ('aging_critical_days', '90'))


def _retype(new_type, defaults):
    d = op.get_bind().dialect.name
    if d == 'mssql':
        conn = op.get_bind()
        cols = [c for c, _ in _AGING]
        prep_drop_columns(conn, 'ops_setting', cols)   # gỡ DEFAULT (DF__) trước
        for c in cols:
            op.alter_column('ops_setting', c, type_=new_type, existing_nullable=False)
        for c, dv in defaults:                          # gắn lại DEFAULT
            conn.execute(sa.text(f"ALTER TABLE ops_setting ADD CONSTRAINT df_ops_setting_{c} DEFAULT {dv} FOR {c}"))
    else:
        with op.batch_alter_table('ops_setting') as batch_op:
            for c in (c for c, _ in _AGING):
                batch_op.alter_column(c, type_=new_type, existing_nullable=False)


def upgrade() -> None:
    _retype(sa.Float(), _AGING)


def downgrade() -> None:
    _retype(sa.Integer(), _AGING)
