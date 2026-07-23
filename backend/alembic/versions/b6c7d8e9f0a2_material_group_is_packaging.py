"""Nhóm vật tư: cờ is_packaging cho báo cáo bao bì tiêu hao theo lô

Revision ID: b6c7d8e9f0a2
Revises: a1b2c3d4e5f9
Create Date: 2026-07-21

- Thêm cột is_packaging (mặc định False) cho material_group — nhóm được đánh dấu cờ này
  sẽ khiến vật tư (Material.category = mã nhóm) tự động xuất hiện ở báo cáo lô bao bì tiêu
  hao (tab Bao bì), lấy trực tiếp từ Kho NVL (MaterialLot/StockMovement/BottleMaterialUsage)
  thay vì khai báo tay. Không ảnh hưởng tới packaging_type/packaging_move (vỏ chai/két/keg
  tuần hoàn — tài sản đặt cọc, giữ nguyên cơ chế riêng). Xem services/packaging.py::lot_report.
"""
from alembic import op
import sqlalchemy as sa

revision = 'b6c7d8e9f0a2'
down_revision = 'a1b2c3d4e5f9'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('material_group', sa.Column('is_packaging', sa.Boolean(),
                                              nullable=False, server_default=sa.false()))


def downgrade() -> None:
    op.drop_column('material_group', 'is_packaging')
