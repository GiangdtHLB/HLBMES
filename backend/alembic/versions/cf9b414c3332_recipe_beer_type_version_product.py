"""recipe → beer_type, recipe_version → product (mỗi version 1 dịch bia riêng)

Revision ID: cf9b414c3332
Revises: d4a1c2b3e5f7
Create Date: 2026-08-22

Đổi `Recipe` từ gắn 1-1 với `Product` (dịch bia, VD SAPPHIRE-13OP/SAPPHIRE-14OP — mỗi độ oP là
1 Product riêng) sang gắn 1-1 với `BeerType` (Loại bia, VD Sapphire) — vì chỉ tiêu nấu/lên men
khác nhau THEO DỊCH trong khi bản thân quy trình soạn/duyệt công thức vẫn quản lý chung theo
thương hiệu (mirror đúng cách Lọc/Chiết đã tra chỉ tiêu theo BeerType, xem models/master.py).
Mỗi `RecipeVersion` giờ tự mang `product_id` riêng — version nào áp dụng cho dịch nào.

upgrade():
  1. Thêm `recipe.beer_type_id` + `recipe_version.product_id` (nullable trước để backfill).
  2. Với mỗi Product đang được 1 Recipe tham chiếu mà chưa có `beer_type_id` (dữ liệu thật hiện
     có 1 case — Product BIA-LAGER của Recipe REC-LAGER): tự tạo 1 BeerType 1-1 (code/name lấy
     từ Product đó, dò trùng code rồi tăng hậu tố nếu đụng) rồi gán vào Product — để migration
     không phụ thuộc việc dọn dữ liệu tay trước khi chạy.
  3. Gom các Recipe theo `beer_type_id` suy ra được — nếu ≥2 Recipe cùng dồn về 1 BeerType
     (dữ liệu thật hiện tại KHÔNG có case này, nhưng Product/BeerType vốn many-to-1 nên phải xử
     lý tổng quát): giữ Recipe có `recipe_id` nhỏ nhất làm "survivor", chuyển toàn bộ
     RecipeVersion của các Recipe còn lại sang `recipe_id` của survivor (renumber `version_no`
     nối tiếp sau số lớn nhất survivor đang có để không đụng `uq_recipe_version`), xóa các
     Recipe thừa.
  4. Set `recipe_version.product_id` = đúng product_id gốc của Recipe nó thuộc về TRƯỚC khi gộp
     (mọi version của 1 Recipe trước migration đều cùng 1 dịch, vì Recipe cũ vốn 1-1 Product).
  5. Set `recipe.beer_type_id`, drop `recipe.product_id` (dùng prep_drop_columns vì cột này có
     FK constraint inline auto-đặt tên từ lúc tạo bảng — 4b0bfd0900bd_init_schema.py — MSSQL từ
     chối DROP COLUMN nếu không gỡ FK trước, xem DEPLOY-CONTRACT §2B), rồi đặt NOT NULL cho 2
     cột mới + tạo lại index (unique cho recipe.beer_type_id, thường cho recipe_version.product_id).

downgrade() CHỈ khôi phục SCHEMA (thêm lại `recipe.product_id` nullable, xóa 2 cột mới) — KHÔNG
phục dựng lại đúng nhóm Recipe đã gộp ở bước 3 (mất thông tin sau khi hợp nhất, cùng giới hạn
"downgrade không đối xứng dữ liệu" như d4a1c2b3e5f7/7a22e8cdfb0a).
"""
import uuid

from alembic import op
import sqlalchemy as sa

from app.alembic_mssql import prep_drop_columns


revision = 'cf9b414c3332'
down_revision = 'd4a1c2b3e5f7'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('recipe', sa.Column('beer_type_id', sa.Unicode(length=64), nullable=True))
    op.add_column('recipe_version', sa.Column('product_id', sa.Unicode(length=64), nullable=True))

    conn = op.get_bind()

    # (2) Tự tạo BeerType 1-1 cho Product chưa có, nếu Product đó đang được 1 Recipe dùng.
    orphan_products = conn.execute(sa.text(
        "SELECT DISTINCT p.product_id, p.code, p.name FROM product p "
        "JOIN recipe r ON r.product_id = p.product_id WHERE p.beer_type_id IS NULL"
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

    # (3)+(4) Gom Recipe theo beer_type_id, gộp nếu trùng, gán product_id cho từng version.
    recipes = conn.execute(sa.text(
        "SELECT r.recipe_id, r.product_id, p.beer_type_id FROM recipe r "
        "JOIN product p ON p.product_id = r.product_id ORDER BY r.recipe_id"
    )).mappings().all()

    by_beer_type = {}
    for r in recipes:
        by_beer_type.setdefault(r["beer_type_id"], []).append(r)

    for bt_id, group in by_beer_type.items():
        survivor = group[0]   # đã ORDER BY recipe_id nên phần tử đầu là recipe_id nhỏ nhất
        conn.execute(sa.text(
            "UPDATE recipe_version SET product_id = :pid WHERE recipe_id = :rid"
        ), {"pid": survivor["product_id"], "rid": survivor["recipe_id"]})

        if len(group) > 1:
            max_no = conn.execute(sa.text(
                "SELECT COALESCE(MAX(version_no), 0) FROM recipe_version WHERE recipe_id = :rid"
            ), {"rid": survivor["recipe_id"]}).scalar()
            for dup in group[1:]:
                conn.execute(sa.text(
                    "UPDATE recipe_version SET product_id = :pid WHERE recipe_id = :rid"
                ), {"pid": dup["product_id"], "rid": dup["recipe_id"]})
                versions = conn.execute(sa.text(
                    "SELECT version_id FROM recipe_version WHERE recipe_id = :rid ORDER BY version_no"
                ), {"rid": dup["recipe_id"]}).mappings().all()
                for v in versions:
                    max_no += 1
                    conn.execute(sa.text(
                        "UPDATE recipe_version SET recipe_id = :new_rid, version_no = :no WHERE version_id = :vid"
                    ), {"new_rid": survivor["recipe_id"], "no": max_no, "vid": v["version_id"]})
                conn.execute(sa.text("DELETE FROM recipe WHERE recipe_id = :rid"), {"rid": dup["recipe_id"]})

        conn.execute(sa.text(
            "UPDATE recipe SET beer_type_id = :bt WHERE recipe_id = :rid"
        ), {"bt": bt_id, "rid": survivor["recipe_id"]})

    # (5) drop cột cũ + index, đặt NOT NULL cho cột mới, tạo index mới. `recipe.product_id` có
    # FK constraint THẬT khai báo inline lúc tạo bảng (4b0bfd0900bd_init_schema.py) — cả SQLite
    # (native DROP COLUMN từ chối nếu còn FK tham chiếu chính cột đó) lẫn MSSQL (từ chối DROP
    # COLUMN khi còn FK auto-name) đều cần gỡ trước khi drop, nên dùng batch_alter_table (SQLite:
    # copy-and-recreate bỏ FK cũ) + prep_drop_columns (MSSQL: DROP CONSTRAINT, no-op SQLite).
    op.drop_index('ix_recipe_product_id_unique', table_name='recipe')
    prep_drop_columns(conn, 'recipe', ['product_id'])
    with op.batch_alter_table('recipe') as batch_op:
        batch_op.drop_column('product_id')
        batch_op.alter_column('beer_type_id', existing_type=sa.Unicode(length=64), nullable=False)

    with op.batch_alter_table('recipe_version') as batch_op:
        batch_op.alter_column('product_id', existing_type=sa.Unicode(length=64), nullable=False)

    op.create_index('ix_recipe_beer_type_id_unique', 'recipe', ['beer_type_id'], unique=True)
    op.create_index('ix_recipe_version_product_id', 'recipe_version', ['product_id'])


def downgrade() -> None:
    op.drop_index('ix_recipe_version_product_id', table_name='recipe_version')
    op.drop_index('ix_recipe_beer_type_id_unique', table_name='recipe')

    op.add_column('recipe', sa.Column('product_id', sa.Unicode(length=64), nullable=True))
    op.create_index('ix_recipe_product_id_unique', 'recipe', ['product_id'], unique=True)

    op.drop_column('recipe_version', 'product_id')
    op.drop_column('recipe', 'beer_type_id')
