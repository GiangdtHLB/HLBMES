"""Ghi chép lên men — bảng theo ngày: audit trail riêng cho từng nhóm trường

Revision ID: a1b2c3d4e5f7
Revises: f2a3b4c5d6e8
Create Date: 2026-07-19

Thay cn_van_hanh/gio_kt_cnvh/gio_kt_kcs/updated_by/updated_at (nhập tay tên người + giờ)
bằng audit trail tự động theo 3 nhóm trường độc lập — measured_by/measured_at (nhiệt độ/°S/
mật độ tb), kcs_by/kcs_at (KCS — kcs giờ là "dat"|"khong_dat"), truc_ca_by/truc_ca_at (trực
ca) — ghi tự động khi có giá trị, không nhập tay (xem services/ferment_log.py::
upsert_daily_readings). Bảng vừa tạo trong cùng đợt, chưa có dữ liệu thật cần giữ nên drop+
tạo lại thay vì ALTER từng cột.
"""
from alembic import op
import sqlalchemy as sa

revision = '55dcafa5a7f9'
down_revision = 'f2a3b4c5d6e8'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_table('ferment_daily_reading')
    op.create_table(
        'ferment_daily_reading',
        sa.Column('reading_id', sa.Unicode(length=64), nullable=False),
        sa.Column('ferment_id', sa.Unicode(length=64), sa.ForeignKey('ferment_record.ferment_id'), nullable=False),
        sa.Column('day_no', sa.Integer(), nullable=False),
        sa.Column('reading_date', sa.Unicode(length=32), nullable=True),
        sa.Column('nhiet_do_c', sa.Float(), nullable=True),
        sa.Column('do_s', sa.Float(), nullable=True),
        sa.Column('mat_do_tb', sa.Float(), nullable=True),
        sa.Column('measured_by', sa.Unicode(length=255), nullable=True),
        sa.Column('measured_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('kcs', sa.Unicode(length=64), nullable=True),
        sa.Column('kcs_by', sa.Unicode(length=255), nullable=True),
        sa.Column('kcs_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('truc_ca', sa.Unicode(length=64), nullable=True),
        sa.Column('truc_ca_by', sa.Unicode(length=255), nullable=True),
        sa.Column('truc_ca_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('reading_id'),
        sa.UniqueConstraint('ferment_id', 'day_no', name='uq_ferment_daily_reading_day'),
    )
    op.create_index('ix_ferment_daily_reading_ferment_id', 'ferment_daily_reading', ['ferment_id'])


def downgrade() -> None:
    op.drop_table('ferment_daily_reading')
