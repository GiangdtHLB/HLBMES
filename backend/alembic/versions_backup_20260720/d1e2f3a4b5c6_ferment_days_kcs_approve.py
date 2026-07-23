"""số ngày lên men chuẩn (Product) + duyệt KCS lên men (FermentRecord)

Revision ID: d1e2f3a4b5c6
Revises: c0d1e2f3a4b5
Create Date: 2026-07-09

- product: thêm ferment_days_std (số ngày lên men chuẩn để tính ngày sẵn sàng chiết).
- ferment_record: thêm qc_approved/qc_approved_by/qc_approved_at (KCS ký xác nhận
  tank lên men đạt, đồng ý cho chiết) — gate cho việc tạo bản ghi lọc từ tank đó.
"""
from alembic import op
import sqlalchemy as sa

revision = 'd1e2f3a4b5c6'
down_revision = 'c0d1e2f3a4b5'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('product', sa.Column('ferment_days_std', sa.Integer(), nullable=True))

    op.add_column('ferment_record', sa.Column('qc_approved', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column('ferment_record', sa.Column('qc_approved_by', sa.Unicode(length=255), nullable=True))
    op.add_column('ferment_record', sa.Column('qc_approved_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column('ferment_record', 'qc_approved_at')
    op.drop_column('ferment_record', 'qc_approved_by')
    op.drop_column('ferment_record', 'qc_approved')
    op.drop_column('product', 'ferment_days_std')
