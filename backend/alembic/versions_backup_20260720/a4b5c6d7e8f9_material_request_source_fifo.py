"""material_request: gắn nguồn Lệnh nấu/Lệnh lọc + snapshot FIFO lúc xuất

Revision ID: a4b5c6d7e8f9
Revises: e6f7a8b9c0d1
Create Date: 2026-07-20

- material_request.source_type/source_id (tuỳ chọn): gắn phiếu đề nghị với 1 Lệnh nấu
  (brew_order) hoặc 1 Lệnh lọc lớn (filter_master_order) — chỉ để tham chiếu/báo cáo, hệ
  thống tự động điền sẵn dòng vật tư từ định mức NVL của lệnh lúc tạo phiếu, người dùng vẫn
  tự do sửa/thêm/xoá dòng sau đó.
- material_request_line.fifo_ok: chụp lại (snapshot) NGAY LÚC XUẤT xem lô đã chọn có phải lô
  cũ nhất (FIFO) hiện có lúc đó hay không — trước đây phiếu đã xử lý xong không hiện được
  cảnh báo FIFO vì so sánh live sau này không còn ý nghĩa (lô cũ hơn có thể đã hết/lô mới đã
  nhập thêm), mirror Shipment.fifo_ok (xem services/wms.py::create_shipment).
"""
from alembic import op
import sqlalchemy as sa

revision = 'a4b5c6d7e8f9'
down_revision = 'e6f7a8b9c0d1'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('material_request') as batch:
        batch.add_column(sa.Column('source_type', sa.Unicode(length=32), nullable=True))
        batch.add_column(sa.Column('source_id', sa.Unicode(length=64), nullable=True))
    op.create_index('ix_material_request_source_type', 'material_request', ['source_type'])
    op.create_index('ix_material_request_source_id', 'material_request', ['source_id'])
    with op.batch_alter_table('material_request_line') as batch:
        batch.add_column(sa.Column('fifo_ok', sa.Boolean(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('material_request_line') as batch:
        batch.drop_column('fifo_ok')
    op.drop_index('ix_material_request_source_id', table_name='material_request')
    op.drop_index('ix_material_request_source_type', table_name='material_request')
    with op.batch_alter_table('material_request') as batch:
        batch.drop_column('source_id')
        batch.drop_column('source_type')
