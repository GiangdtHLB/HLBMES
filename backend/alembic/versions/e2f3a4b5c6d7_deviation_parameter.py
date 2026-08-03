"""Deviation: thêm parameter (mã chỉ tiêu liên quan, người mở tự chọn) để người xem biết ngay
vì sao mở deviation thay vì chỉ có lý do tự do

Revision ID: e2f3a4b5c6d7
Revises: c9d0e1f2a3b4
Create Date: 2026-08-02

- deviation: thêm cột parameter (nullable, danh sách mã chỉ tiêu nối dấu phẩy).
"""
from alembic import op
import sqlalchemy as sa

revision = 'e2f3a4b5c6d7'
down_revision = 'c9d0e1f2a3b4'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('deviation', recreate='auto') as batch_op:
        batch_op.add_column(sa.Column('parameter', sa.Unicode(length=500), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('deviation', recreate='auto') as batch_op:
        batch_op.drop_column('parameter')
