"""transfer_kcpx_require_kcs

Thêm cờ `require_kcs` trên transfer_kcpx_request (Điều chuyển Công ty -> Phân xưởng) — người tạo
đề nghị TỰ CHỌN (tick lúc tạo) có bắt lô về ON_HOLD chờ KCS duyệt lại hay không, KHÔNG còn tự suy
theo requires_kcs_hold(material_id) như trước (mặc định KHÔNG chọn = bỏ qua KCS, kể cả vật tư
đang cấu hình chỉ tiêu bắt buộc trong Danh mục) — yêu cầu người dùng 2026-09-30: "nếu chọn tích
vào đó thì mới cần KCS nhập chỉ tiêu, nếu không chọn thì mặc định lô đó chuyển sang phân xưởng để
duyệt, không cần duyệt qua KCS".

Revision ID: 56a90b371cf6
Revises: 1df6797ac310
Create Date: 2026-09-30 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = '56a90b371cf6'
down_revision = '1df6797ac310'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('transfer_kcpx_request') as batch_op:
        batch_op.add_column(sa.Column('require_kcs', sa.Boolean(), nullable=False,
                                      server_default=sa.false()))


def downgrade() -> None:
    with op.batch_alter_table('transfer_kcpx_request') as batch_op:
        batch_op.drop_column('require_kcs')
