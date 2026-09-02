"""product_ferment_days_std_float

Revision ID: 8dc7d68e2bbe
Revises: 5c1d8e3a7b2f
Create Date: 2026-09-01 00:00:00.000000

Số ngày lên men chuẩn (Product.ferment_days_std) đổi từ INTEGER sang FLOAT — cho phép nhập số
thực (VD 7.5 ngày), yêu cầu người dùng 2026-09-01.
"""
from alembic import op
import sqlalchemy as sa


revision = '8dc7d68e2bbe'
down_revision = '5c1d8e3a7b2f'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('product', recreate='auto') as batch_op:
        batch_op.alter_column('ferment_days_std', existing_type=sa.Integer(), type_=sa.Float(), nullable=True)


def downgrade() -> None:
    with op.batch_alter_table('product', recreate='auto') as batch_op:
        batch_op.alter_column('ferment_days_std', existing_type=sa.Float(), type_=sa.Integer(), nullable=True)
