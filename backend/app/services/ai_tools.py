"""Lớp 'tool' MES — hàm đọc dữ liệu dùng chung cho trợ lý AI và AI agent tương lai.

Tất cả tool ở đây CHỈ ĐỌC (read-only). Theo tài liệu §1.1, AI chỉ tư vấn —
không có tool nào thay đổi setpoint, điều khiển thiết bị hay ghi dữ liệu. Mỗi tool
có schema (JSON Schema) để vừa dùng cho tool-use của Claude vừa xuất manifest cho agent.

Phủ toàn bộ pipeline sản xuất (yêu cầu người dùng 2026-09-18: "mở rộng ra toàn bộ hệ thống"):
Lệnh nấu/Điều độ (get_brew_order_status), Cấp liệu/FIFO (get_dispense_status), Lên men
(get_fermentation_status), Lọc (get_filter_status), Chiết (get_pack_status), Kho TP/WMS
(get_wms_status), Công thức/BOM (get_recipe_status), CAPA/Deviation (get_capa_status) — cộng
với 8 tool gốc (tồn kho NVL, OEE, cảnh báo QC, mẻ, kiểm định, sự cố, năng lượng, truy xuất lô).
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


def get_quality_alerts(db: Session) -> dict:
    from . import derived
    return {"process": derived.process_quality_alerts(db)}


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


# ---- Mở rộng toàn hệ thống (2026-09-18, yêu cầu người dùng): thêm tool cho các khâu Nấu-Lọc-
# Chiết/Cấp liệu/Lên men/Kho TP/Công thức/CAPA chưa từng có trước đây, cùng khuôn READ-ONLY.

def get_brew_order_status(db: Session, order_code: str = None) -> dict:
    from . import brew_order as bo
    orders = bo.list_orders(db)
    if order_code:
        orders = [o for o in orders if o["order_code"] == order_code]
        if not orders:
            return {"error": f"Không tìm thấy Lệnh nấu có mã {order_code}"}
    return {"orders": [{"order_code": o["order_code"], "product_code": o["product_code"],
                        "recipe_code": o["recipe_code"], "planned_volume_hl": o["planned_volume_hl"],
                        "actual_volume_hl": o["actual_volume_hl"], "is_executed": o["is_executed"],
                        "is_complete": o["is_complete"], "wo_status": o["wo_status"]}
                       for o in orders[:30]]}


def get_dispense_status(db: Session, batch_code: str) -> dict:
    """Định mức (BOM) ↔ thực tế cấp liệu + trạng thái FIFO của 1 mẻ — mirror màn "Cấp liệu cho
    mẻ"/"Mẻ sản xuất", xem services/dispense.py::batch_dispense_summary."""
    from . import dispense as disp
    rows = db.execute(select(BatchExecution).order_by(BatchExecution.created_at.desc())).scalars().all()
    batch = next((b for b in rows if b.batch_code == batch_code), None)
    if not batch:
        return {"error": f"Không tìm thấy mẻ có mã {batch_code}"}
    lines = disp.batch_dispense_summary(db, batch.batch_id, only_dispensed=False)
    trimmed = [{"material_code": l["material_code"], "material_name": l.get("material_name"),
               "planned": l.get("planned"), "actual": l.get("actual"), "status": l.get("status"),
               "lot_codes": l.get("lot_codes"), "fifo_ok": l.get("fifo_ok"),
               "fifo_computed": l.get("fifo_computed")} for l in lines]
    shortfall = [l for l in trimmed if l["status"] == "thieu"]
    return {"batch_code": batch_code, "start_at": batch.start_at, "lines": trimmed,
            "shortfall_count": len(shortfall)}


def get_fermentation_status(db: Session, tank_code: str = None) -> dict:
    from . import batch_pipeline as bp
    tanks = bp.list_tanks_out(db)
    if tank_code:
        tanks = [t for t in tanks if t.get("tank_code") == tank_code or t.get("tank_lm") == tank_code]
        if not tanks:
            return {"error": f"Không tìm thấy tank lên men có mã {tank_code}"}
    return {"tanks": [{"tank_code": t.get("tank_code"), "tank_lm": t.get("tank_lm"),
                       "product_code": t.get("product_code"), "on_hand": t.get("on_hand"),
                       "status_label": t.get("status_label"), "days_elapsed": t.get("days_elapsed"),
                       "ready_date": t.get("ready_date"), "qc_fail_count": t.get("qc_fail_count")}
                      for t in tanks[:30]]}


def get_filter_status(db: Session, filter_lot_code: str = None) -> dict:
    from ..models.batch_pipeline import BatchFilterLot
    from ..models.master import Product
    rows = db.execute(select(BatchFilterLot).order_by(BatchFilterLot.created_at.desc())).scalars().all()
    if filter_lot_code:
        rows = [r for r in rows if r.filter_lot_code == filter_lot_code]
        if not rows:
            return {"error": f"Không tìm thấy lô lọc có mã {filter_lot_code}"}
    products = {p.product_id: p for p in db.execute(select(Product)).scalars().all()}
    return {"filter_lots": [{"filter_lot_code": r.filter_lot_code,
                             "product_code": products[r.product_id].code if r.product_id in products else None,
                             "volume_hl": r.volume_hl, "on_hand": r.on_hand, "status": r.status,
                             "qc_approved": r.qc_approved, "quality_status": r.quality_status}
                            for r in rows[:30]]}


def get_pack_status(db: Session, pack_lot_code: str = None) -> dict:
    from ..models.batch_pipeline import BatchPackLot
    from ..models.master import FinishedProduct
    rows = db.execute(select(BatchPackLot).order_by(BatchPackLot.created_at.desc())).scalars().all()
    if pack_lot_code:
        rows = [r for r in rows if r.pack_lot_code == pack_lot_code]
        if not rows:
            return {"error": f"Không tìm thấy lô thành phẩm có mã {pack_lot_code}"}
    fps = {f.finished_product_id: f for f in db.execute(select(FinishedProduct)).scalars().all()}
    return {"pack_lots": [{"pack_lot_code": r.pack_lot_code,
                           "finished_product_code": fps[r.finished_product_id].code
                           if r.finished_product_id in fps else None,
                           "qty_lit": r.qty, "lot_no": r.lot_no, "approved": r.approved,
                           "ca_qty": [r.ca1_qty, r.ca2_qty, r.ca3_qty]} for r in rows[:30]]}


def get_wms_status(db: Session) -> dict:
    from . import wms as wms_svc
    return wms_svc.summary(db)


def get_recipe_status(db: Session, product_code: str = None) -> dict:
    """Công thức (BOM/định mức) đang effective — theo Loại bia/dịch bia."""
    from ..models.master import Product
    from ..models.recipes import Recipe, RecipeVersion
    stmt = select(RecipeVersion).where(RecipeVersion.state == "effective")
    versions = db.execute(stmt).scalars().all()
    products = {p.product_id: p for p in db.execute(select(Product)).scalars().all()}
    recipes = {r.recipe_id: r for r in db.execute(select(Recipe)).scalars().all()}
    if product_code:
        versions = [v for v in versions
                   if v.product_id in products and products[v.product_id].code == product_code]
        if not versions:
            return {"error": f"Không tìm thấy công thức effective cho dịch bia {product_code}"}
    return {"recipe_versions": [{
        "product_code": products[v.product_id].code if v.product_id in products else None,
        "recipe_code": recipes[v.recipe_id].code if v.recipe_id in recipes else None,
        "version_no": v.version_no, "base_qty": v.base_qty, "base_uom": v.base_uom,
        "material_count": len(v.materials or [])} for v in versions[:30]]}


def get_capa_status(db: Session) -> dict:
    """Deviation/CAPA đang mở (chưa closed) — theo dõi xử lý chất lượng chưa xong."""
    from ..models.quality import Deviation
    from ..models.quality_ext import CAPA
    devs = db.execute(select(Deviation).where(Deviation.state != "closed")
                      .order_by(Deviation.opened_at.desc())).scalars().all()
    capas = db.execute(select(CAPA).where(CAPA.state != "closed")).scalars().all()
    return {"open_deviations": [{"deviation_code": d.deviation_code, "scope_type": d.scope_type,
                                 "scope_id": d.scope_id, "severity": d.severity, "state": d.state}
                                for d in devs[:30]],
            "open_capa": [{"capa_code": c.capa_code, "title": c.title, "capa_type": c.capa_type,
                          "severity": c.severity, "state": c.state} for c in capas[:30]]}


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
        "description": "Tổng hợp cảnh báo QC mẻ (FAIL/ngoài giới hạn).",
        "input_schema": {"type": "object", "properties": {}},
    },
    "get_batch_status": {
        "fn": get_batch_status,
        "description": "Trạng thái thực thi và chất lượng các mẻ. Có thể lọc theo mã mẻ.",
        "input_schema": {"type": "object", "properties": {
            "batch_code": {"type": "string", "description": "Mã mẻ Braumat (số nguyên), vd 1"}}},
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
    "get_brew_order_status": {
        "fn": get_brew_order_status,
        "description": "Trạng thái Lệnh nấu (kế hoạch/thực tế sản lượng, đã chạy/hoàn thành chưa).",
        "input_schema": {"type": "object", "properties": {
            "order_code": {"type": "string", "description": "Mã Lệnh nấu. Bỏ trống = tất cả."}}},
    },
    "get_dispense_status": {
        "fn": get_dispense_status,
        "description": "Định mức (BOM) so với thực tế đã cấp liệu của 1 mẻ, kèm trạng thái FIFO từng vật tư.",
        "input_schema": {"type": "object", "properties": {
            "batch_code": {"type": "string", "description": "Mã mẻ Braumat, vd 2354"}},
            "required": ["batch_code"]},
    },
    "get_fermentation_status": {
        "fn": get_fermentation_status,
        "description": "Trạng thái tank lên men: dịch bia, tồn, số ngày lên men, ngày dự kiến lọc, chỉ tiêu QC fail.",
        "input_schema": {"type": "object", "properties": {
            "tank_code": {"type": "string", "description": "Mã tank (hoặc tank vật lý). Bỏ trống = tất cả."}}},
    },
    "get_filter_status": {
        "fn": get_filter_status,
        "description": "Trạng thái lô lọc: thể tích, tồn, đã duyệt KCS hay chưa.",
        "input_schema": {"type": "object", "properties": {
            "filter_lot_code": {"type": "string", "description": "Mã lô lọc. Bỏ trống = tất cả."}}},
    },
    "get_pack_status": {
        "fn": get_pack_status,
        "description": "Trạng thái lô thành phẩm (chiết): sản lượng theo ca, đã duyệt hay chưa.",
        "input_schema": {"type": "object", "properties": {
            "pack_lot_code": {"type": "string", "description": "Mã lô thành phẩm. Bỏ trống = tất cả."}}},
    },
    "get_wms_status": {
        "fn": get_wms_status,
        "description": "Tổng hợp Kho thành phẩm (WMS): số vị trí, sức chứa, pallet đang lưu, tỉ lệ lấp đầy.",
        "input_schema": {"type": "object", "properties": {}},
    },
    "get_recipe_status": {
        "fn": get_recipe_status,
        "description": "Công thức (BOM/định mức) đang hiệu lực (effective) theo dịch bia.",
        "input_schema": {"type": "object", "properties": {
            "product_code": {"type": "string", "description": "Mã dịch bia, vd SAPPHIRE-13OP. Bỏ trống = tất cả."}}},
    },
    "get_capa_status": {
        "fn": get_capa_status,
        "description": "Deviation và CAPA đang mở (chưa đóng) — theo dõi xử lý chất lượng còn tồn đọng.",
        "input_schema": {"type": "object", "properties": {}},
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
