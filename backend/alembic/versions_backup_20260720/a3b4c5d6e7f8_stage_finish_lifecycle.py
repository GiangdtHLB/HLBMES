"""Bắt đầu/Kết thúc thực thi cho Nấu/Lọc/Chiết

Revision ID: a3b4c5d6e7f8
Revises: f8a9b0c1d2e3
Create Date: 2026-07-16

- brew_batch: thêm started_at (gán tay lúc tạo, mặc định giờ hiện tại) + ended_at (chỉ set
  khi vận hành bấm "Kết thúc").
- filter_record/bottle_record: thêm ended_at (mốc bắt đầu đã có sẵn: filter_date/bottle_date).
Đây là trạng thái THỰC THI của vận hành, song song với trạng thái suy ra từ tồn kho hiện có
(status/_filter_status) — không thay thế.
"""
from alembic import op
import sqlalchemy as sa

revision = 'a3b4c5d6e7f8'
down_revision = 'f8a9b0c1d2e3'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('brew_batch') as batch_op:
        batch_op.add_column(sa.Column('started_at', sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column('ended_at', sa.DateTime(), nullable=True))
    with op.batch_alter_table('filter_record') as batch_op:
        batch_op.add_column(sa.Column('ended_at', sa.DateTime(), nullable=True))
    with op.batch_alter_table('bottle_record') as batch_op:
        batch_op.add_column(sa.Column('ended_at', sa.DateTime(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('bottle_record') as batch_op:
        batch_op.drop_column('ended_at')
    with op.batch_alter_table('filter_record') as batch_op:
        batch_op.drop_column('ended_at')
    with op.batch_alter_table('brew_batch') as batch_op:
        batch_op.drop_column('ended_at')
        batch_op.drop_column('started_at')
