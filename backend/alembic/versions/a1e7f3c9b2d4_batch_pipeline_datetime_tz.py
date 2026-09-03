"""batch pipeline: sửa cột thời gian bare DATETIME -> DATETIMEOFFSET (tz-aware)

Revision ID: a1e7f3c9b2d4
Revises: c310cce1e620
Create Date: 2026-09-03

Các migration dựng pipeline "Mẻ sản xuất" 4 lớp tạo cột thời gian bằng bare `sa.DateTime()` →
MSSQL DATETIME, trong khi model dùng UTCDateTime (= DateTime(timezone=True) → DATETIMEOFFSET).
Lệch kiểu này khiến MỌI so sánh/ghi giá trị tz-aware (utcnow()) vào các cột đó vỡ trên SQL Server:
"Conversion failed when converting date and/or time from character string" (VD báo cáo
low-yield-filter-alerts lọc BatchFilterLotBatch.ended_at >= utcnow()-Nd). Đổi 27 cột về
DATETIMEOFFSET (DEPLOY-CONTRACT §1). Chỉ chạy trên MSSQL — SQLite lưu datetime dạng text, đọc
qua UTCDateTime nên không cần đổi.
"""
from alembic import op
import sqlalchemy as sa


revision = 'a1e7f3c9b2d4'
down_revision = 'c310cce1e620'
branch_labels = None
depends_on = None

# (bảng, cột, nullable) — mọi cột đang là DATETIME trên các bảng pipeline (query sys.columns).
_COLS = [
    ('batch_filter_lot', 'created_at', False),
    ('batch_filter_lot', 'ended_at', True),
    ('batch_filter_lot', 'locked_at', True),
    ('batch_filter_lot', 'qc_approved_at', True),
    ('batch_filter_lot_batch', 'created_at', False),
    ('batch_filter_lot_batch', 'ended_at', True),
    ('batch_filter_order', 'created_at', False),
    ('batch_filter_order', 'locked_at', True),
    ('batch_pack_lot', 'approved_at', True),
    ('batch_pack_lot', 'ca1_end_at', True),
    ('batch_pack_lot', 'ca1_start_at', True),
    ('batch_pack_lot', 'ca2_end_at', True),
    ('batch_pack_lot', 'ca2_start_at', True),
    ('batch_pack_lot', 'ca3_end_at', True),
    ('batch_pack_lot', 'ca3_start_at', True),
    ('batch_pack_lot', 'created_at', False),
    ('batch_pack_lot', 'locked_at', True),
    ('batch_pack_lot', 'pack_date', True),
    ('batch_pack_lot', 'stocked_at', True),
    ('batch_pack_lot_material_usage', 'created_at', False),
    ('batch_pack_lot_material_usage', 'lot_date', True),
    ('batch_tank', 'created_at', False),
    ('batch_tank', 'locked_at', True),
    ('batch_tank_daily_reading', 'kcs_at', True),
    ('batch_tank_daily_reading', 'measured_at', True),
    ('batch_tank_daily_reading', 'truc_ca_at', True),
    ('batch_tank_process_log', 'updated_at', True),
]


def _alter(cols, to_type):
    bind = op.get_bind()
    if bind.dialect.name != 'mssql':
        return  # SQLite/PG: UTCDateTime lo việc tz, không cần đổi kiểu vật lý
    for table, col, nullable in cols:
        null_sql = 'NULL' if nullable else 'NOT NULL'
        op.execute(f'ALTER TABLE {table} ALTER COLUMN {col} {to_type} {null_sql}')


def upgrade() -> None:
    _alter(_COLS, 'DATETIMEOFFSET')


def downgrade() -> None:
    _alter(_COLS, 'DATETIME')
