"""batch_filter_lot_qc_approved

Revision ID: 18153f3ab494
Revises: c2951db6c97e
Create Date: 2026-08-31 00:00:00.000000

Thêm qc_approved/qc_approved_by/qc_approved_at vào batch_filter_lot — mirror
FilterRecord.qc_approved (module Nấu-Lọc-Chiết cũ). Cờ RIÊNG, KHÁC quality_status (hold/
release, mặc định RELEASED ngay từ lúc tạo) — approve_filter_lot trước đây chỉ set
quality_status (vốn đã là RELEASED sẵn, nên không có tác dụng phân biệt đã duyệt/chưa duyệt).
"""
from alembic import op
import sqlalchemy as sa


revision = '18153f3ab494'
down_revision = 'c2951db6c97e'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('batch_filter_lot', sa.Column('qc_approved', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column('batch_filter_lot', sa.Column('qc_approved_by', sa.Unicode(length=255), nullable=True))
    op.add_column('batch_filter_lot', sa.Column('qc_approved_at', sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column('batch_filter_lot', 'qc_approved_at')
    op.drop_column('batch_filter_lot', 'qc_approved_by')
    op.drop_column('batch_filter_lot', 'qc_approved')
