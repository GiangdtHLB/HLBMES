"""mẻ (BrewBatch) thuộc 1 mã nấu — NVL/chỉ tiêu khai báo theo mẻ, không theo mã nấu

Revision ID: e1f2a3b4c5d6
Revises: d1e2f3a4b5c6
Create Date: 2026-07-09

- brew_batch: 1 mã nấu (brew_record) = 1 lần nấu vào 1 tank, có thể gồm nhiều mẻ
  (số mẻ từ hệ thống điều khiển nấu, VD Braumat: 123,124,125,126).
- brew_material_usage: đổi khóa ngoại từ brew_id (brew_record) sang batch_id (brew_batch) —
  nguyên liệu khai báo theo mẻ, không theo mã nấu.
"""
from alembic import op
import sqlalchemy as sa

revision = 'e1f2a3b4c5d6'
down_revision = 'd1e2f3a4b5c6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'brew_batch',
        sa.Column('batch_id', sa.Unicode(length=64), nullable=False),
        sa.Column('brew_id', sa.Unicode(length=64), sa.ForeignKey('brew_record.brew_id'), nullable=False),
        sa.Column('batch_code', sa.Unicode(length=64), nullable=False),
        sa.Column('seq', sa.Integer(), nullable=True),
        sa.Column('note', sa.UnicodeText(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('batch_id'),
        sa.UniqueConstraint('batch_code'),
    )
    op.create_index('ix_brew_batch_brew_id', 'brew_batch', ['brew_id'])

    with op.batch_alter_table('brew_material_usage') as batch_op:
        batch_op.drop_column('brew_id')
        batch_op.add_column(sa.Column('batch_id', sa.Unicode(length=64), sa.ForeignKey('brew_batch.batch_id'), nullable=False))
    op.create_index('ix_brew_material_usage_batch_id', 'brew_material_usage', ['batch_id'])


def downgrade() -> None:
    with op.batch_alter_table('brew_material_usage') as batch_op:
        batch_op.drop_column('batch_id')
        batch_op.add_column(sa.Column('brew_id', sa.Unicode(length=64), sa.ForeignKey('brew_record.brew_id'), nullable=False))
    op.drop_table('brew_batch')
