"""Ghi chép lên men (Tank lên men, Mẻ SX) — thêm cột Áp suất, bar

Revision ID: 3e0894f298ab
Revises: 7105cb1c59a3
Create Date: 2026-09-09 10:49:53.185975

batch_tank_daily_reading.ap_suat_bar (nullable): thêm vào bảng theo ngày (mirror
nhiet_do_c/do_s/mat_do_tb) + biểu đồ theo dõi lên men — chỉ áp dụng cho pipeline
"Mẻ SX" (BatchTank), không đụng module Nấu-Lọc-Chiết cũ (FermentDailyReading).
"""
from alembic import op
import sqlalchemy as sa


revision = '3e0894f298ab'
down_revision = '7105cb1c59a3'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('batch_tank_daily_reading', sa.Column('ap_suat_bar', sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column('batch_tank_daily_reading', 'ap_suat_bar')
