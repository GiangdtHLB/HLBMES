"""Bia cận date/Bia gửi: thêm duyệt Trưởng bộ phận kho trước khi tăng tồn kho

Revision ID: a1b2c3d4e5f7
Revises: e2f3a4b5c6d7
Create Date: 2026-08-02

- near_expiry_entry/consigned_entry: thêm approved_by/approved_at (xem services/wms.py::
  approve_near_expiry_entry/approve_consigned_entry). Trước khi duyệt, khai báo direction="in"
  KHÔNG còn tăng tồn kho ngay — chỉ tạo FinishedGoodsUnit lúc duyệt.
- Data fix: các bản khai CŨ (tạo trước migration này) đã có unit_codes nghĩa là đã tăng tồn
  kho thật từ trước — backfill approved_by/approved_at = created_by/created_at để không biến
  chúng thành "đang chờ duyệt" một cách sai lệch (tồn kho của chúng đã tồn tại rồi).
"""
from alembic import op
import sqlalchemy as sa

revision = 'd3e4f5a6b7c9'
down_revision = 'e2f3a4b5c6d7'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('near_expiry_entry', recreate='auto') as batch_op:
        batch_op.add_column(sa.Column('approved_by', sa.Unicode(length=255), nullable=True))
        batch_op.add_column(sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True))
    with op.batch_alter_table('consigned_entry', recreate='auto') as batch_op:
        batch_op.add_column(sa.Column('approved_by', sa.Unicode(length=255), nullable=True))
        batch_op.add_column(sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True))

    conn = op.get_bind()
    conn.execute(sa.text(
        "UPDATE near_expiry_entry SET approved_by = created_by, approved_at = created_at "
        "WHERE direction = 'in' AND unit_codes IS NOT NULL AND approved_by IS NULL"))
    conn.execute(sa.text(
        "UPDATE consigned_entry SET approved_by = created_by, approved_at = created_at "
        "WHERE direction = 'in' AND unit_codes IS NOT NULL AND approved_by IS NULL"))


def downgrade() -> None:
    with op.batch_alter_table('consigned_entry', recreate='auto') as batch_op:
        batch_op.drop_column('approved_at')
        batch_op.drop_column('approved_by')
    with op.batch_alter_table('near_expiry_entry', recreate='auto') as batch_op:
        batch_op.drop_column('approved_at')
        batch_op.drop_column('approved_by')
