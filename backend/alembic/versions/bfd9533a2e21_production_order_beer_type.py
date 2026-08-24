"""production order beer type

Revision ID: bfd9533a2e21
Revises: 1825842d838f
Create Date: 2026-08-24 02:02:16.793360

Lệnh SX (ERP) giờ chọn Loại bia lúc lập (product_id/Dịch bia cụ thể chỉ xác định được sau, lúc
Lệnh nấu chọn Version — 1 Loại bia có thể có nhiều RecipeVersion, mỗi version tự gắn 1 Dịch bia
riêng, xem cf9b414c3332). Thêm `production_order.beer_type_id` (NOT NULL sau backfill), nới
`production_order.product_id` thành nullable (không còn là nguồn sự thật bắt buộc lúc tạo lệnh).

Backfill: mọi ProductionOrder hiện có đều đã có product_id (cột đang NOT NULL trước migration
này) — suy beer_type_id qua product.beer_type_id. Nếu gặp product chưa gán beer_type_id (dữ liệu
lịch sử thiếu, không có trong dữ liệu thật hiện tại nhưng xử lý tổng quát mirror cf9b414c3332):
tự tạo 1 BeerType 1-1 từ chính Product đó rồi gán ngược lại cho Product.
"""
import uuid

from alembic import op
import sqlalchemy as sa


revision = 'bfd9533a2e21'
down_revision = '1825842d838f'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('production_order', sa.Column('beer_type_id', sa.Unicode(length=64), nullable=True))
    conn = op.get_bind()

    # Product được 1 ProductionOrder tham chiếu mà chưa có beer_type_id — tự tạo BeerType 1-1
    # (mirror cf9b414c3332), để migration không phụ thuộc việc dọn dữ liệu tay trước khi chạy.
    orphan_products = conn.execute(sa.text(
        "SELECT DISTINCT p.product_id, p.code, p.name FROM product p "
        "JOIN production_order po ON po.product_id = p.product_id WHERE p.beer_type_id IS NULL"
    )).mappings().all()
    for p in orphan_products:
        code = p["code"]
        n = 2
        while conn.execute(sa.text("SELECT 1 FROM beer_type WHERE code = :c"), {"c": code}).first():
            code = f'{p["code"]}-{n}'
            n += 1
        bt_id = str(uuid.uuid4())
        conn.execute(sa.text(
            "INSERT INTO beer_type (beer_type_id, code, name) VALUES (:id, :code, :name)"
        ), {"id": bt_id, "code": code, "name": p["name"]})
        conn.execute(sa.text(
            "UPDATE product SET beer_type_id = :bt WHERE product_id = :pid"
        ), {"bt": bt_id, "pid": p["product_id"]})

    conn.execute(sa.text(
        "UPDATE production_order SET beer_type_id = ("
        "  SELECT p.beer_type_id FROM product p WHERE p.product_id = production_order.product_id"
        ") WHERE product_id IS NOT NULL"
    ))

    with op.batch_alter_table('production_order') as batch_op:
        batch_op.alter_column('beer_type_id', existing_type=sa.Unicode(length=64), nullable=False)
        batch_op.alter_column('product_id', existing_type=sa.Unicode(length=64), nullable=True)
    op.create_index('ix_production_order_beer_type_id', 'production_order', ['beer_type_id'])


def downgrade() -> None:
    op.drop_index('ix_production_order_beer_type_id', table_name='production_order')
    with op.batch_alter_table('production_order') as batch_op:
        batch_op.alter_column('product_id', existing_type=sa.Unicode(length=64), nullable=False)
        batch_op.drop_column('beer_type_id')
