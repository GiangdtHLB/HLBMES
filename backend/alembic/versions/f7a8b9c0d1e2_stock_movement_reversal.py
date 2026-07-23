"""thêm cột hoàn tác giao dịch kho (reversed, reversal_of)

Revision ID: f7a8b9c0d1e2
Revises: e6f7a8b9c0d1
Create Date: 2026-07-08

Cho phép "hoàn lại" 1 giao dịch xuất tự do (không áp dụng cho trả NCC) — đánh
dấu giao dịch gốc đã được hoàn + trỏ tới giao dịch hoàn tương ứng, chặn hoàn 2 lần.
"""
from alembic import op
import sqlalchemy as sa

revision = 'f7a8b9c0d1e2'
down_revision = 'e6f7a8b9c0d1'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('stock_movement', sa.Column('reversed', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column('stock_movement', sa.Column('reversal_of', sa.Unicode(length=64), nullable=True))
    with op.batch_alter_table('stock_movement') as batch:
        batch.create_foreign_key('fk_stock_movement_reversal_of', 'stock_movement', ['reversal_of'], ['movement_id'])


def downgrade() -> None:
    with op.batch_alter_table('stock_movement') as batch:
        batch.drop_constraint('fk_stock_movement_reversal_of', type_='foreignkey')
        batch.drop_column('reversal_of')
        batch.drop_column('reversed')
