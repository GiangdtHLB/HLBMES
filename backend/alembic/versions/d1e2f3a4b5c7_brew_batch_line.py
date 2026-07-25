"""brew_batch.line_id — dây chuyền/nhà nấu (brewhouse) thực hiện mẻ

Revision ID: d1e2f3a4b5c7
Revises: c7d8e9f0a1b2
Create Date: 2026-07-25

Bắt buộc ở tầng API/UI (BrewBatchIn.line_id không Optional, xem routers/brewing.py::
add_brew_batch — validate line.kind == "brewhouse") khi tạo mẻ MỚI, nhưng nullable ở DB vì
các mẻ đã có sẵn trước migration này chưa từng khai báo dây chuyền — không backfill dữ liệu
cũ (không có căn cứ để suy ra dây chuyền nào đã dùng cho mẻ trong quá khứ).
"""
from alembic import op
import sqlalchemy as sa

revision = 'd1e2f3a4b5c7'
down_revision = 'c7d8e9f0a1b2'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('brew_batch', sa.Column('line_id', sa.Unicode(64), nullable=True))
    op.create_index('ix_brew_batch_line_id', 'brew_batch', ['line_id'])


def downgrade() -> None:
    op.drop_index('ix_brew_batch_line_id', table_name='brew_batch')
    op.drop_column('brew_batch', 'line_id')
