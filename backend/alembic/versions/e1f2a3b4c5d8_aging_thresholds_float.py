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

revision = 'e1f2a3b4c5d8'
down_revision = 'd0e1f2a3b4c6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('ops_setting') as batch_op:
        batch_op.alter_column('aging_caution_days', type_=sa.Float(), existing_nullable=False)
        batch_op.alter_column('aging_warning_days', type_=sa.Float(), existing_nullable=False)
        batch_op.alter_column('aging_critical_days', type_=sa.Float(), existing_nullable=False)


def downgrade() -> None:
    with op.batch_alter_table('ops_setting') as batch_op:
        batch_op.alter_column('aging_caution_days', type_=sa.Integer(), existing_nullable=False)
        batch_op.alter_column('aging_warning_days', type_=sa.Integer(), existing_nullable=False)
        batch_op.alter_column('aging_critical_days', type_=sa.Integer(), existing_nullable=False)
