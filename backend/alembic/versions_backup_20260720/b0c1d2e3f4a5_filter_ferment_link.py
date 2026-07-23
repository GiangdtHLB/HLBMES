"""Liên kết Lọc → lô LM nguồn để trừ/hoàn tồn CCT (on_hand_cct)

Revision ID: b0c1d2e3f4a5
Revises: a9b0c1d2e3f4
Create Date: 2026-07-09

- filter_record: thêm ferment_id (FK ferment_record) — ghi lại lô LM nguồn thật đã khớp
  lúc tạo bản ghi lọc (qua from_cct), dùng để trừ on_hand_cct khi tạo và hoàn lại khi xóa,
  thay vì chỉ khớp lại theo tank_lm (có thể trỏ nhầm lô LM khác nếu tank được tái sử dụng).
"""
from alembic import op
import sqlalchemy as sa

revision = 'b0c1d2e3f4a5'
down_revision = 'a9b0c1d2e3f4'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('filter_record', sa.Column('ferment_id', sa.Unicode(length=64),
                  sa.ForeignKey('ferment_record.ferment_id'), nullable=True))
    op.create_index('ix_filter_record_ferment_id', 'filter_record', ['ferment_id'])


def downgrade() -> None:
    op.drop_column('filter_record', 'ferment_id')
