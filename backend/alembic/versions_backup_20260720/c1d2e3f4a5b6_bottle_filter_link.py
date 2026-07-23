"""Liên kết Chiết → lô lọc/tank BBT nguồn để trừ/hoàn tồn BBT (on_hand_bbt)

Revision ID: c1d2e3f4a5b6
Revises: b0c1d2e3f4a5
Create Date: 2026-07-10

- bottle_record: thêm filter_id (FK filter_record) — ghi lại bản ghi lọc/tank BBT nguồn
  thật đã khớp lúc tạo (qua from_bbt), dùng để trừ on_hand_bbt khi tạo và hoàn lại khi xóa,
  cùng cơ chế với filter_record.ferment_id đã làm cho lô LM.
"""
from alembic import op
import sqlalchemy as sa

revision = 'c1d2e3f4a5b6'
down_revision = 'b0c1d2e3f4a5'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('bottle_record', sa.Column('filter_id', sa.Unicode(length=64),
                  sa.ForeignKey('filter_record.filter_id'), nullable=True))
    op.create_index('ix_bottle_record_filter_id', 'bottle_record', ['filter_id'])


def downgrade() -> None:
    op.drop_column('bottle_record', 'filter_id')
