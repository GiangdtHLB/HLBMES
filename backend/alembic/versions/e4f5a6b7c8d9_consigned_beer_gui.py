"""Bia gửi (consigned): mirror y hệt bia cận date — xe xuất phiếu buổi sáng giao không hết,
mang phần dư về gửi lại kho (khác cận date, khác đổi trả).

Revision ID: e4f5a6b7c8d9
Revises: d2e3f4a5b6c8
Create Date: 2026-08-01

- finished_goods_unit.is_consigned (Boolean): đánh dấu vỉ/keg đến từ "Nhập bia gửi".
- consigned_entry: lịch sử riêng cho nhập/xuất bia gửi (Kho TP) — mirror near_expiry_entry
  nhưng có sẵn finished_product_id/location_id ngay từ đầu (không cần vá thêm như
  near_expiry_entry vì đây là bảng mới, không có dữ liệu cũ theo lô chiết).
"""
from alembic import op
import sqlalchemy as sa

revision = "e4f5a6b7c8d9"
down_revision = "d2e3f4a5b6c8"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("finished_goods_unit", sa.Column("is_consigned", sa.Boolean(), nullable=False,
                                                    server_default=sa.false()))
    op.create_index("ix_finished_goods_unit_is_consigned", "finished_goods_unit", ["is_consigned"])

    op.create_table(
        "consigned_entry",
        sa.Column("entry_id", sa.Unicode(length=64), nullable=False),
        sa.Column("direction", sa.Unicode(length=16), nullable=False),
        sa.Column("finished_product_id", sa.Unicode(length=64), sa.ForeignKey("finished_product.finished_product_id"), nullable=True),
        sa.Column("product_name", sa.Unicode(length=255), nullable=True),
        sa.Column("lot_code", sa.Unicode(length=64), nullable=True),
        sa.Column("unit_type", sa.Unicode(length=16), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("location_id", sa.Unicode(length=64), sa.ForeignKey("wms_location.loc_id"), nullable=True),
        sa.Column("declared_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("shipment_id", sa.Unicode(length=64), sa.ForeignKey("shipment.shipment_id"), nullable=True),
        sa.Column("note", sa.UnicodeText(), nullable=True),
        sa.Column("created_by", sa.Unicode(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("unit_codes", sa.UnicodeText(), nullable=True),
        sa.Column("reversed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.PrimaryKeyConstraint("entry_id"),
    )
    op.create_index("ix_consigned_entry_direction", "consigned_entry", ["direction"])
    op.create_index("ix_consigned_entry_finished_product_id", "consigned_entry", ["finished_product_id"])
    op.create_index("ix_consigned_entry_location_id", "consigned_entry", ["location_id"])
    op.create_index("ix_consigned_entry_shipment_id", "consigned_entry", ["shipment_id"])


def downgrade():
    op.drop_table("consigned_entry")
    op.drop_index("ix_finished_goods_unit_is_consigned", table_name="finished_goods_unit")
    op.drop_column("finished_goods_unit", "is_consigned")
