"""Ngưỡng số ngày lùi tối đa cho phép ở "Ngày nhập" khi nhập kho thủ công thành phẩm/khai
báo Nhập từ nhà máy khác (trước đây hardcode 15 ngày trong wms.py) — cấu hình được ở
Cài đặt vận hành: OpsSetting.finished_goods_receive_max_backdate_days

Revision ID: d4e5f6a7b8c2
Revises: c3d4e5f6a7b1
Create Date: 2026-08-14
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "d4e5f6a7b8c2"
down_revision = "c3d4e5f6a7b1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("ops_setting") as batch_op:
        batch_op.add_column(sa.Column("finished_goods_receive_max_backdate_days", sa.Float(),
                                      nullable=False, server_default="15.0"))


def downgrade() -> None:
    with op.batch_alter_table("ops_setting") as batch_op:
        batch_op.drop_column("finished_goods_receive_max_backdate_days")
