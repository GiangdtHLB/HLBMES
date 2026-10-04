"""filter_lot_batch_note

batch_filter_lot_batch.note — ghi chú tự do cho từng mẻ lọc (VD lý do dừng máy/CIP, sự cố...),
hiển thị + sửa được cùng popup "Sửa"/"Kết thúc" mẻ lọc. Yêu cầu người dùng 2026-10-03.

Revision ID: c55dce88de16
Revises: dcceae3b59ab
Create Date: 2026-10-03 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = 'c55dce88de16'
down_revision = 'dcceae3b59ab'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('batch_filter_lot_batch') as batch_op:
        batch_op.add_column(sa.Column('note', sa.UnicodeText(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('batch_filter_lot_batch') as batch_op:
        batch_op.drop_column('note')
