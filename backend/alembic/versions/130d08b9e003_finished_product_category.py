"""FinishedProduct: thêm category (Bia chai/Bia lon/Bia hơi/Bia tươi...)

Revision ID: c4d5e6f7a8b9
Revises: b3c4d5e6f7a8
Create Date: 2026-07-15
"""
from alembic import op
import sqlalchemy as sa

from app.alembic_mssql import prep_drop_columns

revision = '130d08b9e003'
down_revision = 'b3c4d5e6f7a8'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('finished_product') as batch_op:
        batch_op.add_column(sa.Column('category', sa.Unicode(length=64), nullable=True))
    op.create_index(op.f('ix_finished_product_category'), 'finished_product', ['category'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_finished_product_category'), table_name='finished_product')
    prep_drop_columns(op.get_bind(), 'finished_product', ['category'])
    with op.batch_alter_table('finished_product') as batch_op:
        batch_op.drop_column('category')
