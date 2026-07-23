"""số mẻ trong lô LM + nguyên liệu dùng cho mẻ nấu

Revision ID: b9c0d1e2f3a4
Revises: a8b9c0d1e2f3
Create Date: 2026-07-09

- brew_record: thêm cột seq (số mẻ — thứ tự mẻ nấu trong lô LM).
- brew_material_usage: nguyên liệu (từ material_receipt) đã dùng cho một mẻ nấu cụ thể.
"""
from alembic import op
import sqlalchemy as sa

revision = 'b9c0d1e2f3a4'
down_revision = 'a8b9c0d1e2f3'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('brew_record', sa.Column('seq', sa.Integer(), nullable=True))

    op.create_table(
        'brew_material_usage',
        sa.Column('usage_id', sa.Unicode(length=64), nullable=False),
        sa.Column('brew_id', sa.Unicode(length=64), sa.ForeignKey('brew_record.brew_id'), nullable=False),
        sa.Column('receipt_id', sa.Unicode(length=64), sa.ForeignKey('material_receipt.receipt_id'), nullable=True),
        sa.Column('material_name', sa.Unicode(length=255), nullable=False),
        sa.Column('lot_pm', sa.Unicode(length=255), nullable=True),
        sa.Column('quantity', sa.Float(), nullable=False, server_default='0'),
        sa.Column('uom', sa.Unicode(length=255), nullable=False, server_default='kg'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('usage_id'),
    )
    op.create_index('ix_brew_material_usage_brew_id', 'brew_material_usage', ['brew_id'])
    op.create_index('ix_brew_material_usage_receipt_id', 'brew_material_usage', ['receipt_id'])


def downgrade() -> None:
    op.drop_table('brew_material_usage')
    op.drop_column('brew_record', 'seq')
