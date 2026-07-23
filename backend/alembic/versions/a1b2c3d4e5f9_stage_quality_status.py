"""Hold/Release theo công đoạn: quality_status trên BrewBatch/FermentRecord/FilterRecord/BottleRecord

Revision ID: a1b2c3d4e5f9
Revises: f0a1b2c4d6e8
Create Date: 2026-07-21

- Thêm cột quality_status (mặc định 'released') cho brew_batch, ferment_record,
  filter_record, bottle_record — cho phép QA/Supervisor HOLD/RELEASE độc lập theo từng
  công đoạn (Nấu/Lên men/Lọc/Chiết), tách biệt với `locked` (chốt sổ vĩnh viễn). Xem
  services/quality.py::set_hold + routers/brewing.py::_assert_unlocked.
"""
from alembic import op
import sqlalchemy as sa

revision = 'a1b2c3d4e5f9'
down_revision = 'f0a1b2c4d6e8'
branch_labels = None
depends_on = None

_TABLES = ["brew_batch", "ferment_record", "filter_record", "bottle_record"]


def upgrade() -> None:
    for table in _TABLES:
        op.add_column(table, sa.Column('quality_status', sa.Unicode(length=255),
                                       nullable=False, server_default='released'))


def downgrade() -> None:
    for table in _TABLES:
        op.drop_column(table, 'quality_status')
