"""WMS thành phẩm (wms_location, pallet, wms_case)

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-06-23
"""
from alembic import op
import sqlalchemy as sa

revision = 'd4e5f6a7b8c9'
down_revision = 'c3d4e5f6a7b8'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'wms_location',
        sa.Column('loc_id', sa.String(length=64), nullable=False),
        sa.Column('code', sa.String(length=64), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('zone', sa.String(length=255), nullable=True),
        sa.Column('kind', sa.String(length=255), nullable=False, server_default='bin'),
        sa.Column('capacity', sa.Integer(), nullable=False, server_default='10'),
        sa.Column('active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.PrimaryKeyConstraint('loc_id'),
    )
    op.create_index(op.f('ix_wms_location_code'), 'wms_location', ['code'], unique=True)
    op.create_table(
        'pallet',
        sa.Column('pallet_id', sa.String(length=64), nullable=False),
        sa.Column('pallet_code', sa.String(length=64), nullable=False),
        sa.Column('product', sa.String(length=255), nullable=True),
        sa.Column('lot_code', sa.String(length=64), nullable=True),
        sa.Column('case_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('units_per_case', sa.Integer(), nullable=False, server_default='24'),
        sa.Column('status', sa.String(length=255), nullable=False, server_default='building'),
        sa.Column('location_id', sa.String(length=64), nullable=True),
        sa.Column('created_by', sa.String(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['location_id'], ['wms_location.loc_id']),
        sa.PrimaryKeyConstraint('pallet_id'),
    )
    op.create_index(op.f('ix_pallet_pallet_code'), 'pallet', ['pallet_code'], unique=True)
    op.create_index(op.f('ix_pallet_status'), 'pallet', ['status'], unique=False)
    op.create_index(op.f('ix_pallet_location_id'), 'pallet', ['location_id'], unique=False)
    op.create_table(
        'wms_case',
        sa.Column('case_id', sa.String(length=64), nullable=False),
        sa.Column('case_code', sa.String(length=64), nullable=False),
        sa.Column('pallet_id', sa.String(length=64), nullable=False),
        sa.Column('product', sa.String(length=255), nullable=True),
        sa.Column('units', sa.Float(), nullable=False, server_default='24'),
        sa.Column('lot_code', sa.String(length=64), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['pallet_id'], ['pallet.pallet_id']),
        sa.PrimaryKeyConstraint('case_id'),
    )
    op.create_index(op.f('ix_wms_case_case_code'), 'wms_case', ['case_code'], unique=True)
    op.create_index(op.f('ix_wms_case_pallet_id'), 'wms_case', ['pallet_id'], unique=False)


def downgrade() -> None:
    op.drop_table('wms_case')
    op.drop_table('pallet')
    op.drop_index(op.f('ix_wms_location_code'), table_name='wms_location')
    op.drop_table('wms_location')
