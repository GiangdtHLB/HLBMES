"""duyệt KCS mẻ lọc (FilterRecord)

Revision ID: b5c6d7e8f9a1
Revises: a2b3c4d5e6f8
Create Date: 2026-07-18

- filter_record: thêm qc_approved/qc_approved_by/qc_approved_at (KCS ký xác nhận mẻ
  lọc đạt) — chỉ ký được khi đã nhập đủ chỉ tiêu lọc bắt buộc (mirror ferment_record).
"""
from alembic import op
import sqlalchemy as sa

revision = 'b5c6d7e8f9a1'
down_revision = 'a2b3c4d5e6f8'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('filter_record', sa.Column('qc_approved', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column('filter_record', sa.Column('qc_approved_by', sa.Unicode(length=255), nullable=True))
    op.add_column('filter_record', sa.Column('qc_approved_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column('filter_record', 'qc_approved_at')
    op.drop_column('filter_record', 'qc_approved_by')
    op.drop_column('filter_record', 'qc_approved')
