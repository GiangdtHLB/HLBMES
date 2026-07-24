"""kho thành phẩm: gộp các dòng finished_goods_unit trùng lặp thành 1 dòng/lô

Revision ID: c7d8e9f0a1b2
Revises: 51e5e329b0d1
Create Date: 2026-07-24

Data migration đi kèm docs/WMS-LOT-LEVEL-REDESIGN.md (redesign kho thành phẩm từ "1 dòng/vỉ"
sang "1 dòng/lô"): duyệt chiết trước đây tạo 1 dòng finished_goods_unit CHO MỖI vỉ/keg — 1 lô
190.000 vỉ ra ~190.000 dòng insert row-by-row, gây timeout khi duyệt trên SQL Server (xem
docs/DEPLOY-CONTRACT.md). Code tầng service đã sửa (chỉ còn insert 1 dòng/lô), nhưng dữ liệu
ĐÃ CÓ SẴN trên prod (từ trước khi sửa) vẫn còn ở dạng cũ — migration này gộp lại.

Gộp theo (finished_product_id, product_name, lot_code, unit_type, status, location_id,
shipment_id) — thêm product_name vào khóa gộp so với mô tả gốc trong doc (chỉ liệt kê
finished_product_id) để KHÔNG gộp nhầm 2 sản phẩm khác nhau cùng chưa gán SKU (finished_
product_id NULL) tình cờ trùng lot_code/vị trí/trạng thái. Dòng còn lại (survivor) là dòng có
created_at SỚM NHẤT trong nhóm (giữ mốc FIFO gốc) — cộng quantity = SUM cả nhóm, các dòng còn
lại bị xóa. genealogy_edge trỏ tới/từ các dòng bị xóa được TRỎ LẠI survivor (repoint, không
gộp cạnh trùng — xem docs, _bottle_forward_groups đọc qua GROUP BY nên không cần gộp cạnh để
tránh chậm).

Toàn bộ xử lý bằng SQL portable (GROUP BY/MIN/SUM/subquery chuẩn ANSI, không dùng cú pháp
riêng dialect nào) — chạy được trên SQLite/Postgres/MSSQL như nhau. Số NHÓM trùng lặp trên
thực tế nhỏ (vài chục/vài trăm lô), dù mỗi nhóm có thể gộp hàng trăm nghìn dòng — nên vòng lặp
Python chỉ chạy theo số NHÓM, các câu UPDATE/DELETE thao tác hàng loạt ở tầng SQL.

KHÔNG thể downgrade (mất thông tin: sau khi gộp không còn biết dòng nào tách ra từ dòng nào) —
xem downgrade().
"""
from alembic import op
import sqlalchemy as sa

revision = 'c7d8e9f0a1b2'
down_revision = '51e5e329b0d1'
branch_labels = None
depends_on = None

_GROUP_COLS = ["finished_product_id", "product_name", "lot_code", "unit_type", "status",
               "location_id", "shipment_id"]


def _null_safe_eq(col: str, val) -> tuple[str, dict]:
    """Điều kiện so khớp NULL-safe cho 1 cột trong nhóm — SQL chuẩn `col = :v` không khớp
    được khi cả 2 vế đều NULL, nên nhóm theo cột nullable (lot_code/location_id/shipment_id/
    finished_product_id) phải tách riêng nhánh IS NULL."""
    if val is None:
        return f"{col} IS NULL", {}
    key = f"gv_{col}"
    return f"{col} = :{key}", {key: val}


def upgrade() -> None:
    conn = op.get_bind()

    group_cols_sql = ", ".join(_GROUP_COLS)
    dup_groups = conn.execute(sa.text(f"""
        SELECT {group_cols_sql}, COUNT(*) AS cnt, SUM(quantity) AS total_qty
        FROM finished_goods_unit
        GROUP BY {group_cols_sql}
        HAVING COUNT(*) > 1
    """)).mappings().all()

    for g in dup_groups:
        conds, params = [], {}
        for col in _GROUP_COLS:
            c, p = _null_safe_eq(col, g[col])
            conds.append(c)
            params.update(p)
        where_sql = " AND ".join(conds)

        survivor = conn.execute(sa.text(
            f"SELECT unit_id FROM finished_goods_unit WHERE {where_sql} "
            "ORDER BY created_at ASC, unit_id ASC"
        ), params).scalars().first()
        if not survivor:
            continue
        p = dict(params)
        p["survivor"] = survivor
        p["total_qty"] = g["total_qty"]

        # Trỏ lại cạnh phả hệ (cả 2 chiều) từ các dòng sẽ bị xóa sang dòng còn lại.
        conn.execute(sa.text(f"""
            UPDATE genealogy_edge SET to_id = :survivor
            WHERE to_type = 'finished_goods_unit' AND to_id IN (
                SELECT unit_id FROM finished_goods_unit WHERE {where_sql} AND unit_id != :survivor
            )
        """), p)
        conn.execute(sa.text(f"""
            UPDATE genealogy_edge SET from_id = :survivor
            WHERE from_type = 'finished_goods_unit' AND from_id IN (
                SELECT unit_id FROM finished_goods_unit WHERE {where_sql} AND unit_id != :survivor
            )
        """), p)

        conn.execute(sa.text(
            "UPDATE finished_goods_unit SET quantity = :total_qty WHERE unit_id = :survivor"
        ), p)
        conn.execute(sa.text(
            f"DELETE FROM finished_goods_unit WHERE {where_sql} AND unit_id != :survivor"
        ), p)


def downgrade() -> None:
    """Không thể hoàn tác — sau khi gộp, không còn dữ liệu (unit_code/created_at riêng của
    từng vỉ) để tách ngược lại. Đây là data migration một chiều, đi kèm thay đổi code tầng
    service (không phải thay đổi schema) nên không có DDL cần đảo ngược."""
