"""production_line_usable_pct

Revision ID: 5511d69dd844
Revises: de4c63ff7ee4
Create Date: 2026-09-01 00:00:00.000000

ProductionLine.usable_pct — % khả dụng của tank (kind="tank"/"tank_bbt"): tank thật không chứa
được 100% thể tích danh định (chừa khoảng CO2/bọt) — thể tích khả dụng = volume * usable_pct/100,
hiển thị ở Danh mục "Tank lên men"/"Tank thành phẩm", yêu cầu người dùng 2026-09-01.
"""
from alembic import op
import sqlalchemy as sa


revision = '5511d69dd844'
down_revision = 'de4c63ff7ee4'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('production_line') as batch_op:
        batch_op.add_column(sa.Column('usable_pct', sa.Float(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('production_line') as batch_op:
        batch_op.drop_column('usable_pct')
