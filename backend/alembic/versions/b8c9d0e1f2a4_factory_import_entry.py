"""Nhập từ nhà máy khác: bia nhận từ 1 nhà máy khác (Danh mục Nhà máy), không do nhà máy đang
chạy hệ thống này sản xuất.

Revision ID: b8c9d0e1f2a4
Revises: a7b8c9d0e1f3
Create Date: 2026-08-08

- finished_goods_unit.is_factory_import (Boolean): đánh dấu vỉ/keg đến từ "Nhập từ nhà máy
  khác" — CHỈ để dành cho báo cáo riêng sau này, không có xử lý đặc biệt gì ở Xuất kho/Điều
  chuyển/FIFO (mirror is_near_expiry/is_consigned về mặt khai báo-duyệt nhưng không tách dòng
  riêng ở Xuất kho).
- factory_import_entry: lịch sử khai báo (mirror near_expiry_entry, chỉ có chiều "in" — không
  có "out" tự động) — factory_id (Danh mục Nhà máy, models/warehouse.py::FactoryLocation) bắt
  buộc, đây là "dấu hiệu" nhận biết nguồn gốc.
"""
from alembic import op
import sqlalchemy as sa

revision = "b8c9d0e1f2a4"
down_revision = "a7b8c9d0e1f3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("finished_goods_unit", sa.Column("is_factory_import", sa.Boolean(), nullable=False,
                                                    server_default=sa.false()))
    op.create_index("ix_finished_goods_unit_is_factory_import", "finished_goods_unit", ["is_factory_import"])

    op.create_table(
        "factory_import_entry",
        sa.Column("entry_id", sa.Unicode(length=64), nullable=False),
        sa.Column("finished_product_id", sa.Unicode(length=64), sa.ForeignKey("finished_product.finished_product_id"), nullable=True),
        sa.Column("product_name", sa.Unicode(length=255), nullable=True),
        sa.Column("lot_code", sa.Unicode(length=64), nullable=True),
        sa.Column("unit_type", sa.Unicode(length=16), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("location_id", sa.Unicode(length=64), sa.ForeignKey("wms_location.loc_id"), nullable=True),
        sa.Column("factory_id", sa.Unicode(length=64), sa.ForeignKey("factory_location.factory_id"), nullable=True),
        sa.Column("declared_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("note", sa.UnicodeText(), nullable=True),
        sa.Column("created_by", sa.Unicode(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("unit_codes", sa.UnicodeText(), nullable=True),
        sa.Column("reversed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("approved_by", sa.Unicode(length=255), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("entry_id"),
    )
    op.create_index("ix_factory_import_entry_finished_product_id", "factory_import_entry", ["finished_product_id"])
    op.create_index("ix_factory_import_entry_location_id", "factory_import_entry", ["location_id"])
    op.create_index("ix_factory_import_entry_factory_id", "factory_import_entry", ["factory_id"])


def downgrade() -> None:
    op.drop_table("factory_import_entry")
    op.drop_index("ix_finished_goods_unit_is_factory_import", table_name="finished_goods_unit")
    op.drop_column("finished_goods_unit", "is_factory_import")
