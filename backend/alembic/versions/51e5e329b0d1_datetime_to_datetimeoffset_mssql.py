"""MSSQL: đổi 15 cột thời gian DATETIME → DATETIMEOFFSET (nhận datetime tz-aware)

Revision ID: 51e5e329b0d1
Revises: b7c8d9e0f1a3
Create Date: 2026-07-24

Model khai các cột thời gian bằng UTCDateTime (impl DateTime(timezone=True)) và app luôn
ghi datetime tz-aware (common.utcnow → datetime.now(timezone.utc)). Nhưng 15 cột này do
migration cũ tạo bằng sa.DateTime() TRẦN (thiếu timezone=True) nên trên SQL Server thành
kiểu DATETIME (không giữ offset). Ghi 1 datetime tz-aware vào DATETIME → pyodbc gửi chuỗi
có offset → SQL Server báo "Conversion failed when converting date and/or time from
character string" (500). Vỡ ở "Thêm mẻ" (brew_batch.started_at), "Lưu ngưỡng"
(ops_setting.updated_at) và mọi thao tác ghi các cột dưới đây.

Đổi sang DATETIMEOFFSET để khớp model. Chỉ chạy trên MSSQL (prod); các dialect khác no-op
(giá trị lưu luôn là UTC nên convert DATETIME→DATETIMEOFFSET giữ nguyên, offset +00:00).
Không cột nào có DEFAULT/index nên ALTER thẳng, không cần gỡ ràng buộc trước.
"""
from alembic import op

revision = '51e5e329b0d1'
down_revision = 'b7c8d9e0f1a3'
branch_labels = None
depends_on = None

# (bảng, cột, nullable) — 15 cột kiểu DATETIME phát hiện trên prod.
_COLS = [
    ('bottle_record', 'ended_at', True),
    ('bottle_record', 'locked_at', True),
    ('brew_batch', 'ended_at', True),
    ('brew_batch', 'locked_at', True),
    ('brew_batch', 'started_at', True),
    ('brew_order', 'locked_at', True),
    ('brew_record', 'locked_at', True),
    ('ferment_record', 'locked_at', True),
    ('filter_master_order', 'locked_at', True),
    ('filter_order', 'created_at', False),
    ('filter_order', 'locked_at', True),
    ('filter_order_tank', 'ended_at', True),
    ('filter_record', 'ended_at', True),
    ('filter_record', 'locked_at', True),
    ('ops_setting', 'updated_at', False),
]


def _alter(sql_type: str) -> None:
    if op.get_bind().dialect.name != 'mssql':
        return
    for table, col, nullable in _COLS:
        null = 'NULL' if nullable else 'NOT NULL'
        op.execute(f"ALTER TABLE {table} ALTER COLUMN {col} {sql_type} {null}")


def upgrade() -> None:
    _alter('datetimeoffset')


def downgrade() -> None:
    _alter('datetime')
