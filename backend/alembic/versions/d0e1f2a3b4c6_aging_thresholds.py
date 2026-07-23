"""Cài đặt vận hành: thêm ngưỡng cảnh báo tuổi lô tồn kho

Revision ID: d0e1f2a3b4c6
Revises: c9d0e1f2a3b5
Create Date: 2026-07-22

- Thêm 3 cột aging_caution_days/aging_warning_days/aging_critical_days vào ops_setting
  (mặc định 30/60/90) — cho phép chỉnh ngưỡng cảnh báo của báo cáo "Tồn kho theo tuổi"
  (services/wms.py::lot_aging_report) qua Cài đặt vận hành thay vì hardcode.
"""
from alembic import op
import sqlalchemy as sa

revision = 'd0e1f2a3b4c6'
down_revision = 'c9d0e1f2a3b5'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('ops_setting', sa.Column('aging_caution_days', sa.Integer(),
                                           nullable=False, server_default='30'))
    op.add_column('ops_setting', sa.Column('aging_warning_days', sa.Integer(),
                                           nullable=False, server_default='60'))
    op.add_column('ops_setting', sa.Column('aging_critical_days', sa.Integer(),
                                           nullable=False, server_default='90'))


def downgrade() -> None:
    op.drop_column('ops_setting', 'aging_critical_days')
    op.drop_column('ops_setting', 'aging_warning_days')
    op.drop_column('ops_setting', 'aging_caution_days')
