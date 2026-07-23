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
    with op.batch_alter_table('bottle_record') as batch_op:
        batch_op.add_column(sa.Column('filter_id', sa.Unicode(length=64),
                      sa.ForeignKey('filter_record.filter_id', name='fk_bottle_record_filter_id_filter_record'), nullable=True))
        batch_op.create_index('ix_bottle_record_filter_id', ['filter_id'])


def downgrade() -> None:
    with op.batch_alter_table('bottle_record') as batch_op:
        batch_op.drop_index('ix_bottle_record_filter_id')
        batch_op.drop_column('filter_id')
