"""genealogy_edge: thêm movement_id (FK stock_movement) + backfill cạnh split/transfer cũ

Revision ID: ae7424b8e601
Revises: 492bb7ee99aa
Create Date: 2026-09-14 22:10:00.000000

Cần cho `_lot_balances_as_of` (services/warehouse.py, "Xem tồn kho theo ngày") dựng lại đúng tồn
khi 1 lô được điều chuyển NHIỀU LẦN vào CÙNG 1 dòng đích (từ migration 492bb7ee99aa — cùng lot_code
được phép gộp lặp lại vào cùng dòng-kho đích) — heuristic cũ "lần đầu thấy lot_id trong lịch sử"
không còn phân biệt được "lô mới" với "gộp lần 2/3 vào dòng đã tồn tại". `movement_id` cho biết
đúng StockMovement (transfer) nào sinh ra cạnh genealogy nào, tra 1:1 thay vì suy luận.

Backfill dữ liệu: mọi cạnh split/source_event="transfer" HIỆN CÓ (sinh ra dưới `_transfer_lot()`
bản CŨ, luôn tạo 1 lô MỚI + 1 StockMovement MỚI cho mỗi lần tách — quan hệ khi đó LUÔN LÀ 1:1) được
khớp lại với đúng StockMovement của nó qua (lot_id=edge.to_id, movement_type="transfer",
quantity=edge.quantity), chọn StockMovement có `created_at` GẦN `event_time` của cạnh NHẤT (cả 2
cột đều là utcnow() thật lúc ghi, ghi cùng lúc trong cùng 1 lệnh gọi `_transfer_lot()` — đáng tin
cậy hơn `ts` vốn có thể bị khai lùi ngày, xem approve_sang_ngang). Vì quan hệ gốc luôn 1:1, khớp
không mơ hồ.

KHÔNG thể downgrade dữ liệu đã backfill (một khi cạnh mới sau migration cũng có movement_id, không
còn phân biệt được cạnh nào cần xoá lại — chỉ downgrade schema, giữ nguyên dữ liệu movement_id đã
ghi, an toàn vì cột này là nullable/phụ trợ, không ảnh hưởng ràng buộc nào khác).
"""
from datetime import datetime

from alembic import op
import sqlalchemy as sa


revision = 'ae7424b8e601'
down_revision = '492bb7ee99aa'
branch_labels = None
depends_on = None


def _as_dt(value):
    """Raw sa.text() không áp type decorator của cột — SQLite (khác MSSQL/Postgres, driver tự
    trả về datetime) trả `created_at`/`event_time` dưới dạng chuỗi ISO, cần tự parse để trừ được."""
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value).replace(" ", "T").replace("Z", "+00:00"))


def upgrade() -> None:
    with op.batch_alter_table('genealogy_edge') as batch_op:
        batch_op.add_column(sa.Column(
            'movement_id', sa.Unicode(length=64),
            sa.ForeignKey('stock_movement.movement_id', name='fk_genealogy_edge_movement_id_stock_movement'),
            nullable=True))
        batch_op.create_index('ix_genealogy_edge_movement_id', ['movement_id'])

    conn = op.get_bind()
    edges = conn.execute(sa.text(
        "SELECT edge_id, to_id, quantity, event_time FROM genealogy_edge "
        "WHERE from_type = 'lot' AND to_type = 'lot' AND relation = 'split' "
        "AND source_event = 'transfer' AND movement_id IS NULL"
    )).mappings().all()
    for edge in edges:
        candidates = conn.execute(sa.text(
            "SELECT movement_id, created_at FROM stock_movement "
            "WHERE lot_id = :lot_id AND movement_type = 'transfer' AND quantity = :qty"
        ), {"lot_id": edge["to_id"], "qty": edge["quantity"]}).mappings().all()
        if not candidates:
            continue
        event_time = _as_dt(edge["event_time"])
        best = min(candidates, key=lambda c: abs((_as_dt(c["created_at"]) - event_time).total_seconds()))
        conn.execute(sa.text(
            "UPDATE genealogy_edge SET movement_id = :mv WHERE edge_id = :eid"
        ), {"mv": best["movement_id"], "eid": edge["edge_id"]})


def downgrade() -> None:
    with op.batch_alter_table('genealogy_edge') as batch_op:
        batch_op.drop_index('ix_genealogy_edge_movement_id')
        batch_op.drop_column('movement_id')
