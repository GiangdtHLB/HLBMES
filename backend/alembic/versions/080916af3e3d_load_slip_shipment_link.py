"""load_slip_shipment_link

Revision ID: 080916af3e3d
Revises: 704a6bf6fa4a
Create Date: 2026-08-19 10:47:25.163816
"""
from alembic import op
import sqlalchemy as sa


revision = '080916af3e3d'
down_revision = '704a6bf6fa4a'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('load_slip') as batch_op:
        batch_op.add_column(sa.Column('shipment_id', sa.Unicode(length=64), nullable=True))
        batch_op.create_index('ix_load_slip_shipment_id', ['shipment_id'])


def downgrade() -> None:
    with op.batch_alter_table('load_slip') as batch_op:
        batch_op.drop_index('ix_load_slip_shipment_id')
        batch_op.drop_column('shipment_id')
