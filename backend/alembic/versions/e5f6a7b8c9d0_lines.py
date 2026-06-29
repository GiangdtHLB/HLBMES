"""production line master + recipe SUSPENDED (state là chuỗi, không đổi schema)

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-06-23
"""
from alembic import op
import sqlalchemy as sa

revision = 'e5f6a7b8c9d0'
down_revision = 'd4e5f6a7b8c9'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'production_line',
        sa.Column('line_id', sa.String(length=64), nullable=False),
        sa.Column('code', sa.String(length=64), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('area', sa.String(length=255), nullable=True),
        sa.Column('ideal_rate_per_min', sa.Float(), nullable=False, server_default='0'),
        sa.Column('active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('line_id'),
    )
    op.create_index(op.f('ix_production_line_code'), 'production_line', ['code'], unique=True)
    op.create_index(op.f('ix_production_line_active'), 'production_line', ['active'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_production_line_active'), table_name='production_line')
    op.drop_index(op.f('ix_production_line_code'), table_name='production_line')
    op.drop_table('production_line')
