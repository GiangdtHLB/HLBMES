"""production order admin fields (issued_by executor_unit warehouse_keeper reference_note start_date end_date safety_note created_by)

Revision ID: 5520c402202e
Revises: 7a22e8cdfb0a
Create Date: 2026-08-21 08:46:53.079116

Lệnh SX (ERP) mirror phần hành chính của Lệnh nấu (BrewMasterOrder) — Người ra lệnh/Thực hiện/
Xuất hàng, Căn cứ, Thời gian thực hiện, Biện pháp an toàn — để dùng chung 1 mẫu in "LỆNH SẢN
XUẤT KIÊM PHIẾU XUẤT KHO" (xem frontend printProductionOrder). Khác BrewMasterOrder, các trường
này nằm THẲNG trên production_order (không có cấu trúc lệnh nhỏ/master-children).
"""
from alembic import op
import sqlalchemy as sa


revision = '5520c402202e'
down_revision = '7a22e8cdfb0a'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('production_order') as batch_op:
        batch_op.add_column(sa.Column('issued_by', sa.Unicode(length=255), nullable=True))
        batch_op.add_column(sa.Column('executor_unit', sa.Unicode(length=255), nullable=True))
        batch_op.add_column(sa.Column('warehouse_keeper', sa.Unicode(length=255), nullable=True))
        batch_op.add_column(sa.Column('reference_note', sa.UnicodeText(), nullable=True))
        batch_op.add_column(sa.Column('start_date', sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column('end_date', sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column('safety_note', sa.UnicodeText(), nullable=True))
        batch_op.add_column(sa.Column('created_by', sa.Unicode(length=255), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('production_order') as batch_op:
        batch_op.drop_column('created_by')
        batch_op.drop_column('safety_note')
        batch_op.drop_column('end_date')
        batch_op.drop_column('start_date')
        batch_op.drop_column('reference_note')
        batch_op.drop_column('warehouse_keeper')
        batch_op.drop_column('executor_unit')
        batch_op.drop_column('issued_by')
