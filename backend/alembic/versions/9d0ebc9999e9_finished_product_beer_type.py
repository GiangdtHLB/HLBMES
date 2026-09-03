"""finished_product_beer_type

Revision ID: 9d0ebc9999e9
Revises: 8dc7d68e2bbe
Create Date: 2026-09-01 00:00:00.000000

FinishedProduct.beer_type_id — Loại bia của SKU thành phẩm, khai trực tiếp (không suy qua
product_id vốn chỉ để tham khảo) để lọc đúng nhóm chỉ tiêu/Sản phẩm theo Loại bia khi lập
Lệnh lọc, yêu cầu người dùng 2026-09-01.
"""
from alembic import op
import sqlalchemy as sa


revision = '9d0ebc9999e9'
down_revision = '8dc7d68e2bbe'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('finished_product') as batch_op:
        batch_op.add_column(sa.Column('beer_type_id', sa.Unicode(length=64), nullable=True))
        batch_op.create_index('ix_finished_product_beer_type_id', ['beer_type_id'])


def downgrade() -> None:
    with op.batch_alter_table('finished_product') as batch_op:
        batch_op.drop_index('ix_finished_product_beer_type_id')
        batch_op.drop_column('beer_type_id')
