"""batch_execution_brewhouse_line

Revision ID: 5c1d8e3a7b2f
Revises: 3f7b2c9a1e6d
Create Date: 2026-08-31 00:00:00.000000

Cho phép chọn/sửa Dây chuyền nấu (ProductionLine kind="brewhouse") NGAY ở "Tạo mẻ" (Mẻ sản
xuất), độc lập với Lệnh SX (điều độ) — thêm batch_execution.brewhouse_line_id.
"""
from alembic import op
import sqlalchemy as sa


revision = '5c1d8e3a7b2f'
down_revision = '3f7b2c9a1e6d'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('batch_execution', sa.Column('brewhouse_line_id', sa.Unicode(length=64), nullable=True))
    op.create_index('ix_batch_execution_brewhouse_line_id', 'batch_execution', ['brewhouse_line_id'])


def downgrade() -> None:
    op.drop_index('ix_batch_execution_brewhouse_line_id', table_name='batch_execution')
    op.drop_column('batch_execution', 'brewhouse_line_id')
