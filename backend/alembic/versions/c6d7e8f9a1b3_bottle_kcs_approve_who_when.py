"""ghi ai/khi nào duyệt chiết (BottleRecord)

Revision ID: c6d7e8f9a1b3
Revises: e9f0a1b2c3d5
Create Date: 2026-07-21

- bottle_record: thêm approved_by/approved_at (KCS ký duyệt chiết đạt) — mirror
  filter_record.qc_approved_by/qc_approved_at, để hiện "ai duyệt, ngày giờ duyệt"
  giống tab Lên men/Lọc thay vì chỉ có cờ approved trần trụi.
"""
from alembic import op
import sqlalchemy as sa

revision = 'c6d7e8f9a1b3'
down_revision = 'e9f0a1b2c3d5'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('bottle_record', sa.Column('approved_by', sa.Unicode(length=255), nullable=True))
    op.add_column('bottle_record', sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column('bottle_record', 'approved_at')
    op.drop_column('bottle_record', 'approved_by')
