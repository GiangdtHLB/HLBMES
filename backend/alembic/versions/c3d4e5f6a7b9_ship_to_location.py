"""Danh mục nơi xuất đến (nhà phân phối) + pallet.shipped_at/ship_to_id

Revision ID: c3d4e5f6a7b9
Revises: b2c3d4e5f6a8
Create Date: 2026-07-15

- ship_to_location: danh mục nơi xuất đến (thường là nhà phân phối) — gắn vào pallet lúc
  xuất kho để truy xuất/thu hồi biết lô nào đã đi đâu.
- pallet.shipped_at/ship_to_id: ngày xuất + nơi xuất đến của pallet.
"""
from alembic import op
import sqlalchemy as sa

revision = 'c3d4e5f6a7b9'
down_revision = 'b2c3d4e5f6a8'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'ship_to_location',
        sa.Column('ship_to_id', sa.Unicode(length=64), nullable=False),
        sa.Column('code', sa.Unicode(length=64), nullable=False),
        sa.Column('name', sa.Unicode(length=255), nullable=False),
        sa.Column('kind', sa.Unicode(length=255), nullable=False, server_default='distributor'),
        sa.Column('address', sa.Unicode(length=255), nullable=True),
        sa.Column('contact', sa.Unicode(length=255), nullable=True),
        sa.Column('active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.PrimaryKeyConstraint('ship_to_id'),
    )
    op.create_index(op.f('ix_ship_to_location_code'), 'ship_to_location', ['code'], unique=True)
    op.add_column('pallet', sa.Column('shipped_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('pallet', sa.Column('ship_to_id', sa.Unicode(length=64), nullable=True))
    op.create_index(op.f('ix_pallet_ship_to_id'), 'pallet', ['ship_to_id'], unique=False)
    with op.batch_alter_table('pallet') as batch_op:
        batch_op.create_foreign_key('fk_pallet_ship_to_id', 'ship_to_location', ['ship_to_id'], ['ship_to_id'])


def downgrade() -> None:
    with op.batch_alter_table('pallet') as batch_op:
        batch_op.drop_constraint('fk_pallet_ship_to_id', type_='foreignkey')
    op.drop_index(op.f('ix_pallet_ship_to_id'), table_name='pallet')
    op.drop_column('pallet', 'ship_to_id')
    op.drop_column('pallet', 'shipped_at')
    op.drop_index(op.f('ix_ship_to_location_code'), table_name='ship_to_location')
    op.drop_table('ship_to_location')
