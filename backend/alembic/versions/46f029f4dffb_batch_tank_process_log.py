"""batch_tank_process_log

Revision ID: 46f029f4dffb
Revises: 6d89185e734f
Create Date: 2026-08-31 00:00:00.000000

Thêm "Ghi chép lên men" cho BatchTank (Mẻ SX) — mirror FermentProcessLog/FermentDailyReading
(module Nấu-Lọc-Chiết cũ, xem services/ferment_log.py): batch_tank_process_log (bảng thông tin
đầu, biểu mẫu BM 1.11 (06)) + batch_tank_daily_reading (bảng theo ngày).
"""
from alembic import op
import sqlalchemy as sa


revision = '46f029f4dffb'
down_revision = '6d89185e734f'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'batch_tank_process_log',
        sa.Column('log_id', sa.Unicode(length=64), primary_key=True),
        sa.Column('tank_id', sa.Unicode(length=64), nullable=False),
        sa.Column('manual_json', sa.UnicodeText(), nullable=True),
        sa.Column('note', sa.UnicodeText(), nullable=True),
        sa.Column('updated_by', sa.Unicode(length=255), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
    )
    op.create_index('ix_batch_tank_process_log_tank_id', 'batch_tank_process_log', ['tank_id'], unique=True)

    op.create_table(
        'batch_tank_daily_reading',
        sa.Column('reading_id', sa.Unicode(length=64), primary_key=True),
        sa.Column('tank_id', sa.Unicode(length=64), nullable=False),
        sa.Column('day_no', sa.Integer(), nullable=False),
        sa.Column('reading_date', sa.Unicode(length=32), nullable=True),
        sa.Column('nhiet_do_c', sa.Float(), nullable=True),
        sa.Column('do_s', sa.Float(), nullable=True),
        sa.Column('mat_do_tb', sa.Float(), nullable=True),
        sa.Column('measured_by', sa.Unicode(length=255), nullable=True),
        sa.Column('measured_at', sa.DateTime(), nullable=True),
        sa.Column('kcs', sa.Unicode(length=64), nullable=True),
        sa.Column('kcs_by', sa.Unicode(length=255), nullable=True),
        sa.Column('kcs_at', sa.DateTime(), nullable=True),
        sa.Column('truc_ca', sa.Unicode(length=64), nullable=True),
        sa.Column('truc_ca_by', sa.Unicode(length=255), nullable=True),
        sa.Column('truc_ca_at', sa.DateTime(), nullable=True),
        sa.UniqueConstraint('tank_id', 'day_no', name='uq_batch_tank_daily_reading_day'),
    )
    op.create_index('ix_batch_tank_daily_reading_tank_id', 'batch_tank_daily_reading', ['tank_id'])


def downgrade() -> None:
    op.drop_table('batch_tank_daily_reading')
    op.drop_table('batch_tank_process_log')
