"""brew record production order link

Revision ID: b09abc6c171e
Revises: cf9b414c3332
Create Date: 2026-08-22

Mã nấu (BrewRecord) giờ có thể tạo qua "Lệnh SX (ERP)" (ProductionOrder) thay vì chỉ qua
"Lệnh nấu" (BrewOrder) — thêm `brew_record.production_order_id` (nullable, song song
`brew_order_id` đã có, đúng 1 trong 2 được set — validate ở services/orders.py, không CHECK
constraint ở DB). Đồng thời thêm `ops_setting.erp_order_volume_tolerance_hl` — sai số sản
lượng (±hl) DÙNG CHUNG cho mọi Lệnh SX (ERP) khi tự động xét "hoàn thành" (thay vì mỗi lệnh
tự khai riêng như BrewOrder.volume_tolerance_hl).
"""
from alembic import op
import sqlalchemy as sa


revision = 'b09abc6c171e'
down_revision = 'cf9b414c3332'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('brew_record', sa.Column('production_order_id', sa.Unicode(length=64), nullable=True))
    op.create_index('ix_brew_record_production_order_id', 'brew_record', ['production_order_id'])
    op.add_column('ops_setting', sa.Column('erp_order_volume_tolerance_hl', sa.Float(),
                                           nullable=False, server_default='5.0'))


def downgrade() -> None:
    op.drop_column('ops_setting', 'erp_order_volume_tolerance_hl')
    op.drop_index('ix_brew_record_production_order_id', table_name='brew_record')
    op.drop_column('brew_record', 'production_order_id')
