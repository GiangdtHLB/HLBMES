"""Shipment — thêm warehouse_id để chặn tài khoản bị giới hạn 1 kho thành phẩm (wms_warehouse_
scope) xác nhận/sửa/hoàn tác phiếu xuất kho của kho khác (rà soát an toàn: confirm_shipment/
update_shipment/undo_shipment trước đây chỉ dựa vào shipment_id, không xác minh phiếu thuộc
kho được phân quyền hay không).

Revision ID: b3d5f7a9c1e2
Revises: a2c4e6f8b1d3
Create Date: 2026-08-09
"""
from alembic import op
import sqlalchemy as sa


revision = 'b3d5f7a9c1e2'
down_revision = 'a2c4e6f8b1d3'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("shipment", sa.Column("warehouse_id", sa.Unicode(64), nullable=True))
    with op.batch_alter_table("shipment") as batch_op:
        batch_op.create_foreign_key("fk_shipment_warehouse_id", "wms_warehouse",
                                     ["warehouse_id"], ["warehouse_id"])


def downgrade() -> None:
    with op.batch_alter_table("shipment") as batch_op:
        batch_op.drop_constraint("fk_shipment_warehouse_id", type_="foreignkey")
    op.drop_column("shipment", "warehouse_id")
