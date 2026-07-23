"""Ghi chép lên men — biểu mẫu BM 1.11 (06) BIỂU THEO DÕI LÊN MEN

Revision ID: f2a3b4c5d6e8
Revises: e1f2a3b4c5d7
Create Date: 2026-07-19

- ferment_process_log: các trường nhập tay ở bảng thông tin đầu (Kiểu men, mật độ
  B/C/D/E/F/G/J, lưu lượng khí bs, tách men, mốc Hạ phụ...) dồn vào manual_json — xem
  services/ferment_log.py::HEADER_FIELDS. 1:1 với ferment_record.
- ferment_daily_reading: 1 dòng / 1 ngày theo dõi (nhiệt độ/°S/mật độ tb/CN vận hành/giờ KT
  đột xuất/KCS/trực ca) — bảng con riêng (không dồn vào JSON) để vẽ biểu đồ theo ngày.
"""
from alembic import op
import sqlalchemy as sa

revision = 'f2a3b4c5d6e8'
down_revision = 'e1f2a3b4c5d7'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'ferment_process_log',
        sa.Column('log_id', sa.Unicode(length=64), nullable=False),
        sa.Column('ferment_id', sa.Unicode(length=64), sa.ForeignKey('ferment_record.ferment_id'), nullable=False),
        sa.Column('manual_json', sa.UnicodeText(), nullable=True),
        sa.Column('note', sa.UnicodeText(), nullable=True),
        sa.Column('updated_by', sa.Unicode(length=255), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('log_id'),
        sa.UniqueConstraint('ferment_id'),
    )
    op.create_index('ix_ferment_process_log_ferment_id', 'ferment_process_log', ['ferment_id'])

    op.create_table(
        'ferment_daily_reading',
        sa.Column('reading_id', sa.Unicode(length=64), nullable=False),
        sa.Column('ferment_id', sa.Unicode(length=64), sa.ForeignKey('ferment_record.ferment_id'), nullable=False),
        sa.Column('day_no', sa.Integer(), nullable=False),
        sa.Column('reading_date', sa.Unicode(length=32), nullable=True),
        sa.Column('nhiet_do_c', sa.Float(), nullable=True),
        sa.Column('do_s', sa.Float(), nullable=True),
        sa.Column('mat_do_tb', sa.Float(), nullable=True),
        sa.Column('cn_van_hanh', sa.Unicode(length=64), nullable=True),
        sa.Column('gio_kt_cnvh', sa.Unicode(length=32), nullable=True),
        sa.Column('kcs', sa.Unicode(length=64), nullable=True),
        sa.Column('gio_kt_kcs', sa.Unicode(length=32), nullable=True),
        sa.Column('truc_ca', sa.Unicode(length=64), nullable=True),
        sa.Column('updated_by', sa.Unicode(length=255), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('reading_id'),
        sa.UniqueConstraint('ferment_id', 'day_no', name='uq_ferment_daily_reading_day'),
    )
    op.create_index('ix_ferment_daily_reading_ferment_id', 'ferment_daily_reading', ['ferment_id'])


def downgrade() -> None:
    op.drop_table('ferment_daily_reading')
    op.drop_table('ferment_process_log')
