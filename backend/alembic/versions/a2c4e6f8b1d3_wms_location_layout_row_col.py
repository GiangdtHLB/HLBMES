"""Vị trí kho — thêm layout_row/layout_col cho "Bố cục kho" (admin tự xếp vị trí lên lưới
hàng/cột qua UI kéo-thả, thay vì sơ đồ vẽ cứng theo mã D01-D21 cũ — mã vị trí thật trên server
(vd "DM.K01") không theo quy luật cố định nào để tự suy ra vị trí vẽ).

Revision ID: a2c4e6f8b1d3
Revises: 961553fef9f2
Create Date: 2026-08-09
"""
from alembic import op
import sqlalchemy as sa


revision = 'a2c4e6f8b1d3'
down_revision = '961553fef9f2'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("wms_location", sa.Column("layout_row", sa.Integer(), nullable=True))
    op.add_column("wms_location", sa.Column("layout_col", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("wms_location", "layout_col")
    op.drop_column("wms_location", "layout_row")
