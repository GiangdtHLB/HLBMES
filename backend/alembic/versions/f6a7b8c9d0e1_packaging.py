"""production_line.kind + bao bì tuần hoàn (packaging_type, packaging_move)

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-06-23
"""
from alembic import op
import sqlalchemy as sa

revision = 'f6a7b8c9d0e1'
down_revision = 'e5f6a7b8c9d0'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('production_line', sa.Column('kind', sa.String(), nullable=False, server_default='line'))
    op.create_index(op.f('ix_production_line_kind'), 'production_line', ['kind'], unique=False)
    op.create_table(
        'packaging_type',
        sa.Column('pkg_id', sa.String(), nullable=False),
        sa.Column('code', sa.String(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('category', sa.String(), nullable=False),
        sa.Column('material', sa.String(), nullable=True),
        sa.Column('volume_l', sa.Float(), nullable=True),
        sa.Column('deposit', sa.Float(), nullable=False, server_default='0'),
        sa.Column('on_hand', sa.Float(), nullable=False, server_default='0'),
        sa.Column('in_circulation', sa.Float(), nullable=False, server_default='0'),
        sa.Column('active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('pkg_id'),
    )
    op.create_index(op.f('ix_packaging_type_code'), 'packaging_type', ['code'], unique=True)
    op.create_index(op.f('ix_packaging_type_category'), 'packaging_type', ['category'], unique=False)
    op.create_table(
        'packaging_move',
        sa.Column('move_id', sa.String(), nullable=False),
        sa.Column('pkg_id', sa.String(), nullable=False),
        sa.Column('kind', sa.String(), nullable=False),
        sa.Column('qty', sa.Float(), nullable=False, server_default='0'),
        sa.Column('ref', sa.String(), nullable=True),
        sa.Column('note', sa.String(), nullable=True),
        sa.Column('by', sa.String(), nullable=True),
        sa.Column('ts', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['pkg_id'], ['packaging_type.pkg_id']),
        sa.PrimaryKeyConstraint('move_id'),
    )
    op.create_index(op.f('ix_packaging_move_pkg_id'), 'packaging_move', ['pkg_id'], unique=False)


def downgrade() -> None:
    op.drop_table('packaging_move')
    op.drop_index(op.f('ix_packaging_type_category'), table_name='packaging_type')
    op.drop_index(op.f('ix_packaging_type_code'), table_name='packaging_type')
    op.drop_table('packaging_type')
    op.drop_index(op.f('ix_production_line_kind'), table_name='production_line')
    op.drop_column('production_line', 'kind')
