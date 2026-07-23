"""lọc lại tank thành phẩm (BBT) trong lệnh lọc

Revision ID: d0e1f2a3b4c5
Revises: c8d9e0f1a2b3
Create Date: 2026-07-19

- filter_order_tank: ferment_id nới sang nullable (SQLite cần rebuild bảng qua
  batch_alter_table); thêm tank_type (cct|bbt, default cct), source_bbt_code,
  source_filter_id (FK filter_record — tự resolve lúc add_filter), reason (lý do lọc lại,
  bắt buộc khi tank_type=bbt, validate ở tầng service).
- filter_record: thêm source_filter_id (FK filter_record — mẻ lọc BBT nguồn khi lọc lại
  KHÔNG PHỐI; phối để None, xem filter_order_tank.source_filter_id từng dòng).
Không backfill dữ liệu.
"""
from alembic import op
import sqlalchemy as sa

revision = 'd0e1f2a3b4c5'
down_revision = 'c8d9e0f1a2b3'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('filter_record', sa.Column('source_filter_id', sa.Unicode(64), sa.ForeignKey('filter_record.filter_id'), nullable=True))
    op.create_index('ix_filter_record_source_filter_id', 'filter_record', ['source_filter_id'])

    with op.batch_alter_table('filter_order_tank') as batch_op:
        batch_op.alter_column('ferment_id', existing_type=sa.Unicode(64), nullable=True)
        batch_op.add_column(sa.Column('tank_type', sa.Unicode(16), nullable=False, server_default='cct'))
        batch_op.add_column(sa.Column('source_bbt_code', sa.Unicode(255), nullable=True))
        batch_op.add_column(sa.Column('source_filter_id', sa.Unicode(64), sa.ForeignKey('filter_record.filter_id'), nullable=True))
        batch_op.add_column(sa.Column('reason', sa.UnicodeText(), nullable=True))
    op.create_index('ix_filter_order_tank_source_bbt_code', 'filter_order_tank', ['source_bbt_code'])
    op.create_index('ix_filter_order_tank_source_filter_id', 'filter_order_tank', ['source_filter_id'])


def downgrade() -> None:
    op.drop_index('ix_filter_order_tank_source_filter_id', table_name='filter_order_tank')
    op.drop_index('ix_filter_order_tank_source_bbt_code', table_name='filter_order_tank')
    with op.batch_alter_table('filter_order_tank') as batch_op:
        batch_op.drop_column('reason')
        batch_op.drop_column('source_filter_id')
        batch_op.drop_column('source_bbt_code')
        batch_op.drop_column('tank_type')
        batch_op.alter_column('ferment_id', existing_type=sa.Unicode(64), nullable=False)

    op.drop_index('ix_filter_record_source_filter_id', table_name='filter_record')
    op.drop_column('filter_record', 'source_filter_id')
