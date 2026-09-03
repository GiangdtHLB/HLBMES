"""batch_pack_lot_shifts

Revision ID: 9c3d7f1a2b4e
Revises: 7a1c2e9f4b3d
Create Date: 2026-08-31 00:00:00.000000

Thêm SL chiết theo ca 1/2/3 + giờ bắt đầu/kết thúc từng ca vào batch_pack_lot — mirror
BottleRecord.ca1/ca2/ca3 (module Nấu-Lọc-Chiết cũ), bổ sung mốc giờ mà module cũ không có.
"""
from alembic import op
import sqlalchemy as sa


revision = '9c3d7f1a2b4e'
down_revision = '7a1c2e9f4b3d'
branch_labels = None
depends_on = None


def upgrade() -> None:
    for n in (1, 2, 3):
        op.add_column('batch_pack_lot', sa.Column(f'ca{n}_qty', sa.Float(), nullable=True))
        op.add_column('batch_pack_lot', sa.Column(f'ca{n}_start_at', sa.DateTime(), nullable=True))
        op.add_column('batch_pack_lot', sa.Column(f'ca{n}_end_at', sa.DateTime(), nullable=True))


def downgrade() -> None:
    for n in (3, 2, 1):
        op.drop_column('batch_pack_lot', f'ca{n}_end_at')
        op.drop_column('batch_pack_lot', f'ca{n}_start_at')
        op.drop_column('batch_pack_lot', f'ca{n}_qty')
