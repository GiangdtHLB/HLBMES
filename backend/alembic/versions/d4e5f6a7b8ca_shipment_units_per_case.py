"""Xuất kho từng phần nhiều pallet (shipment/shipment_line) + Lon/thùng theo sản phẩm

Revision ID: d4e5f6a7b8ca
Revises: c3d4e5f6a7b9
Create Date: 2026-07-15

- finished_product.units_per_case: Lon/thùng cố định theo SKU (thay vì gõ tay mỗi lần
  đóng pallet, mặc định 24).
- shipment/shipment_line: 1 phiếu xuất kho có thể gồm nhiều dòng, mỗi dòng lấy 1 số
  lượng case từ 1 pallet cụ thể — thay cho ship() xuất nguyên pallet cũ.
"""
from alembic import op
import sqlalchemy as sa

revision = 'd4e5f6a7b8ca'
down_revision = 'c3d4e5f6a7b9'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('finished_product', sa.Column('units_per_case', sa.Integer(), nullable=False, server_default='24'))

    op.create_table(
        'shipment',
        sa.Column('shipment_id', sa.Unicode(length=64), nullable=False),
        sa.Column('shipment_code', sa.Unicode(length=64), nullable=False),
        sa.Column('ship_to_id', sa.Unicode(length=64), nullable=False),
        sa.Column('created_by', sa.Unicode(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('note', sa.Unicode(length=255), nullable=True),
        sa.ForeignKeyConstraint(['ship_to_id'], ['ship_to_location.ship_to_id']),
        sa.PrimaryKeyConstraint('shipment_id'),
    )
    op.create_index(op.f('ix_shipment_shipment_code'), 'shipment', ['shipment_code'], unique=True)
    op.create_index(op.f('ix_shipment_ship_to_id'), 'shipment', ['ship_to_id'], unique=False)

    op.create_table(
        'shipment_line',
        sa.Column('line_id', sa.Unicode(length=64), nullable=False),
        sa.Column('shipment_id', sa.Unicode(length=64), nullable=False),
        sa.Column('pallet_id', sa.Unicode(length=64), nullable=False),
        sa.Column('product', sa.Unicode(length=255), nullable=True),
        sa.Column('lot_code', sa.Unicode(length=64), nullable=True),
        sa.Column('quantity', sa.Integer(), nullable=False, server_default='0'),
        sa.ForeignKeyConstraint(['shipment_id'], ['shipment.shipment_id']),
        sa.ForeignKeyConstraint(['pallet_id'], ['pallet.pallet_id']),
        sa.PrimaryKeyConstraint('line_id'),
    )
    op.create_index(op.f('ix_shipment_line_shipment_id'), 'shipment_line', ['shipment_id'], unique=False)
    op.create_index(op.f('ix_shipment_line_pallet_id'), 'shipment_line', ['pallet_id'], unique=False)


def downgrade() -> None:
    op.drop_table('shipment_line')
    op.drop_index(op.f('ix_shipment_ship_to_id'), table_name='shipment')
    op.drop_index(op.f('ix_shipment_shipment_code'), table_name='shipment')
    op.drop_table('shipment')
    op.drop_column('finished_product', 'units_per_case')
