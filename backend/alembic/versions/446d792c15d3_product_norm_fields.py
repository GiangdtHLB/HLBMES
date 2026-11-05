"""Dịch bia (Product) — thêm Định mức V dịch + Định mức năng lượng

Revision ID: 446d792c15d3
Revises: 7b3c9e1f4a6d
Create Date: 2026-11-05

product.v_dich_norm_hl (nullable): Định mức V dịch chuẩn/mẻ (hl).
product.energy_norm_kwh_per_hl (nullable): Định mức năng lượng chuẩn (kWh/hl thành phẩm).
Cho báo cáo "BC hiệu suất tổng + định mức dịch + định mức năng lượng" (Nhóm D, port phần mềm
QLSX cũ) — yêu cầu người dùng 2026-11-05, chọn khai định mức theo TỪNG dịch bia thay vì 1 cặp
định mức chung cho cả nhà máy.
"""
from alembic import op
import sqlalchemy as sa


revision = '446d792c15d3'
down_revision = '7b3c9e1f4a6d'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('product', sa.Column('v_dich_norm_hl', sa.Float(), nullable=True))
    op.add_column('product', sa.Column('energy_norm_kwh_per_hl', sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column('product', 'energy_norm_kwh_per_hl')
    op.drop_column('product', 'v_dich_norm_hl')
