"""Chiết: thêm FinishedProduct.unit_volume_l để đối chiếu Ca1+Ca2+Ca3 với V cấp chiết

Revision ID: 2b3c4d5e6f7a
Revises: 1a2b3c4d5e6f
Create Date: 2026-08-02

- finished_product: thêm unit_volume_l (float, nullable) — dung tích 1 đơn vị đóng gói
  cuối cùng (lít), dùng để quy đổi V cấp chiết (hl, đo ở tank BBT) sang số lượng vỉ/keg kỳ
  vọng lúc "Kết thúc chiết" (xem routers/brewing.py::finish_bottle). SKU cũ để trống = bỏ
  qua đối chiếu, không ép buộc backfill.
"""
from alembic import op
import sqlalchemy as sa

revision = '2b3c4d5e6f7a'
down_revision = '1a2b3c4d5e6f'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('finished_product', recreate='auto') as batch_op:
        batch_op.add_column(sa.Column('unit_volume_l', sa.Float(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('finished_product', recreate='auto') as batch_op:
        batch_op.drop_column('unit_volume_l')
