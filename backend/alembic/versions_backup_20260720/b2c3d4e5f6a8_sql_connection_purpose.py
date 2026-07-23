"""Gán kết nối SQL cho module MES (VD Năng lượng)

Revision ID: b2c3d4e5f6a8
Revises: a1b2c3d4e5f7
Create Date: 2026-07-10

- sql_connection.purpose: module MES được chỉ định dùng kết nối này (VD "energy") —
  chỉ là bước gán/khai báo, chưa thật sự truy vấn dữ liệu.
"""
from alembic import op
import sqlalchemy as sa

revision = 'b2c3d4e5f6a8'
down_revision = 'a1b2c3d4e5f7'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('sql_connection', sa.Column('purpose', sa.Unicode(length=64), nullable=True))


def downgrade() -> None:
    op.drop_column('sql_connection', 'purpose')
