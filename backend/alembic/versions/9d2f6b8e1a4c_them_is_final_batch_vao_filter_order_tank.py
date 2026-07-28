"""them is_final_batch vao filter_order_tank

Revision ID: 9d2f6b8e1a4c
Revises: 7c1e4a2b9f3d
Create Date: 2026-07-29 08:00:00.000000

Cờ đánh dấu 1 dòng "mẻ lọc số" (FilterOrderTank) là đợt rút CUỐI của 1 mẻ lọc thật (thường là
phần "vét" tank, sản lượng thấp một cách bình thường) — báo cáo sản lượng theo mẻ lọc số
(services/filter_yield_report.py) loại các dòng/nhóm này khỏi phân loại Thấp/Cao.
"""
from alembic import op
import sqlalchemy as sa


revision = '9d2f6b8e1a4c'
down_revision = '7c1e4a2b9f3d'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('filter_order_tank', sa.Column('is_final_batch', sa.Boolean(),
                                                 nullable=False, server_default=sa.false()))


def downgrade() -> None:
    op.drop_column('filter_order_tank', 'is_final_batch')
