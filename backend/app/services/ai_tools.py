"""Lớp 'tool' MES — hàm đọc dữ liệu dùng chung cho trợ lý AI và AI agent tương lai.

Tất cả tool ở đây CHỈ ĐỌC (read-only). Theo tài liệu §1.1, AI chỉ tư vấn —
không có tool nào thay đổi setpoint, điều khiển thiết bị hay ghi dữ liệu. Mỗi tool
có schema (JSON Schema) để vừa dùng cho tool-use của Claude vừa xuất manifest cho agent.
"""


from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models.batches import BatchExecution
from ..models.maintenance import Incident
from . import warehouse as wh
from . import genealogy
from .performance import compute_oee


# ---- Hàm tool (db, **input) -> dict ----

def get_inventory_status(db: Session, below_only: bool = False) -> dict:
    stock = wh.stock_on_hand(db)
    expiry = wh.expiry_report(db)
    near = [e for e in expiry if e["status"] in ("near", "expired")]
    return {"items": stock, "expiring_soon": near[:20]}


def get_oee(db: Session, line: str = None) -> dict:
    from ..models.metrics import OEERecord
    stmt = select(OEERecord).order_by(OEERecord.shift_date.desc())
    if line:
        stmt = stmt.where(OEERecord.line == line)
    recs = db.execute(stmt).scalars().all()
    return {"records": [compute_oee(r) for r in recs[:10]]}


def get_quality_alerts(db: Session, month: int = None, year: int = None) -> dict:
    from . import derived
    return {"brewing": derived.brewing_alerts(db, month, year),
            "process": derived.process_quality_alerts(db)}


def get_batch_status(db: Session, batch_code: str = None) -> dict:
    stmt = select(BatchExecution).order_by(BatchExecution.created_at.desc())
    rows = db.execute(stmt).scalars().all()
    if batch_code:
        rows = [b for b in rows if b.batch_code == batch_code]
    return {"batches": [{"batch_code": b.batch_code, "state": b.state,
                         "quality_status": b.quality_status, "planned_qty": b.planned_qty,
                         "actual_qty": b.actual_qty, "uom": b.uom} for b in rows[:30]]}


def get_calibrations_due(db: Session) -> dict:
    from . import derived
    items = derived.calibrations(db)
    due = [c for c in items if c["status"] in ("due", "overdue")]
    return {"due_or_overdue": due, "total": len(items)}


def get_open_incidents(db: Session) -> dict:
    rows = db.execute(select(Incident).where(Incident.status.in_(["open", "in_progress"]))
                      .order_by(Incident.reported_at.desc())).scalars().all()
    return {"open_incidents": [{"code": i.incident_code, "title": i.title,
                               "severity": i.severity, "status": i.status} for i in rows]}


def get_energy_summary(db: Session) -> dict:
    from . import derived
    return {"monthly": derived.energy_monthly(db)}


def trace_lot(db: Session, code: str) -> dict:
    node = genealogy.find_node(db, code)
    if not node:
        return {"error": f"Không tìm thấy lô/mẻ có mã {code}"}
    affected = genealogy.recall_affected(db, node[0], node[1])
    back = genealogy.trace_backward(db, node[0], node[1])
    return {"code": code, "affected_forward": affected, "backward_tree": back}


# ---- Registry: name -> (fn, description, input_schema) ----
TOOLS = {
    "get_inventory_status": {
        "fn": get_inventory_status,
        "description": "Xem tồn kho nguyên vật liệu hiện tại và các lô sắp/đã hết hạn.",
        "input_schema": {"type": "object", "properties": {
            "below_only": {"type": "boolean", "description": "Chỉ lấy mục dưới mức (tùy chọn)"}}},
    },
    "get_oee": {
        "fn": get_oee,
        "description": "Lấy chỉ số OEE đóng gói (Availability×Performance×Quality) theo line.",
        "input_schema": {"type": "object", "properties": {
            "line": {"type": "string", "description": "Tên line, vd 'Line-1 (chai)'. Bỏ trống = tất cả."}}},
    },
    "get_quality_alerts": {
        "fn": get_quality_alerts,
        "description": "Tổng hợp cảnh báo chỉ tiêu chất lượng (nấu/lọc/chiết + QC mẻ) theo tháng/năm.",
        "input_schema": {"type": "object", "properties": {
            "month": {"type": "integer"}, "year": {"type": "integer"}}},
    },
    "get_batch_status": {
        "fn": get_batch_status,
        "description": "Trạng thái thực thi và chất lượng các mẻ. Có thể lọc theo mã mẻ.",
        "input_schema": {"type": "object", "properties": {
            "batch_code": {"type": "string", "description": "Mã mẻ, vd B-2406-0001"}}},
    },
    "get_calibrations_due": {
        "fn": get_calibrations_due,
        "description": "Danh sách kiểm định/hiệu chuẩn sắp đến hạn hoặc quá hạn.",
        "input_schema": {"type": "object", "properties": {}},
    },
    "get_open_incidents": {
        "fn": get_open_incidents,
        "description": "Các sự cố thiết bị đang mở/đang xử lý.",
        "input_schema": {"type": "object", "properties": {}},
    },
    "get_energy_summary": {
        "fn": get_energy_summary,
        "description": "Tổng hợp tiêu thụ năng lượng (điện/nước/hơi) theo tháng.",
        "input_schema": {"type": "object", "properties": {}},
    },
    "trace_lot": {
        "fn": trace_lot,
        "description": "Truy xuất nguồn gốc và mô phỏng recall cho một mã lô/mẻ.",
        "input_schema": {"type": "object", "properties": {
            "code": {"type": "string", "description": "Mã lô/mẻ cần truy xuất"}},
            "required": ["code"]},
    },
}


def anthropic_tool_specs() -> list:
    """Chuyển registry thành danh sách tool cho Claude tool-use."""
    return [{"name": n, "description": t["description"], "input_schema": t["input_schema"]}
            for n, t in TOOLS.items()]


def call_tool(db: Session, name: str, payload: dict) -> dict:
    spec = TOOLS.get(name)
    if not spec:
        return {"error": f"Tool không tồn tại: {name}"}
    try:
        return spec["fn"](db, **(payload or {}))
    except Exception as e:  # noqa: BLE001 — trả lỗi cho agent xử lý
        return {"error": str(e)}
