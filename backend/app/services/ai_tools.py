"""Lớp 'tool' MES — hàm đọc dữ liệu dùng chung cho trợ lý AI và AI agent tương lai.

Tất cả tool ở đây CHỈ ĐỌC (read-only). Theo tài liệu §1.1, AI chỉ tư vấn —
không có tool nào thay đổi setpoint, điều khiển thiết bị hay ghi dữ liệu. Mỗi tool
có schema (JSON Schema) để vừa dùng cho tool-use của Claude vừa xuất manifest cho agent.

Phủ toàn bộ pipeline sản xuất (yêu cầu người dùng 2026-09-18: "mở rộng ra toàn bộ hệ thống"):
Lệnh nấu/Điều độ (get_brew_order_status), Cấp liệu/FIFO (get_dispense_status), Lên men
(get_fermentation_status), Lọc (get_filter_status), Chiết (get_pack_status), Kho TP/WMS
(get_wms_status), Công thức/BOM (get_recipe_status), CAPA/Deviation (get_capa_status) — cộng
với 8 tool gốc (tồn kho NVL, OEE, cảnh báo QC, mẻ, kiểm định, sự cố, năng lượng, truy xuất lô).

Mở rộng thêm 2026-11-03 (yêu cầu người dùng: "Mở rộng đầy đủ toàn bộ tính năng cho AI này tư
vấn") — phủ nốt các mảng còn thiếu: CIP (get_cip_status), Bảo trì/dừng máy (get_maintenance_
status), OEE chi tiết theo kỳ (get_oee_detail), Điều độ/Lệnh SX (get_wo_status), Lập lịch
(get_schedule_conflicts), Danh mục SP/NVL (get_product_info/get_material_info), CAPA chi tiết
(get_capa_detail), trạng thái ký/khóa EBR (get_ebr_lock_status), ISA-88 (get_isa88_status), đề
nghị cấp NVL đang chờ (get_pending_material_requests), Bao bì (get_packaging_status), báo cáo
hệ lọc/dây chuyền chiết (get_filter_production_report/get_pack_line_report) — đồng thời làm
giàu 2 tool đã có: get_inventory_status (tách theo Kho công ty/phân xưởng qua `location`) và
get_batch_status/get_dispense_status (thêm các field hồ sơ EBR/cấp liệu trước đây chỉ xem được
qua UI, không qua AI — xem routers/ai.py: endpoint /api/ai/chat KHÔNG lọc theo scope của người
hỏi như UI thường, nên MỌI tool ở đây vẫn giữ nguyên phạm vi đọc toàn hệ thống, không mở thêm
quyền gì mới ngoài phạm vi đã có)."""


from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models.batches import BatchExecution
from ..models.maintenance import Incident
from . import warehouse as wh
from . import genealogy
from .performance import compute_oee


# ---- Hàm tool (db, **input) -> dict ----

def get_inventory_status(db: Session, below_only: bool = False, location: str = None) -> dict:
    """`location`: "Kho công ty" hoặc "Kho phân xưởng" (bỏ trống = gộp cả 2, như trước)."""
    stock = wh.stock_on_hand(db, location=location)
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
    """Không truyền `batch_code`: danh sách rút gọn (tối đa 30 mẻ gần nhất). Có `batch_code`:
    trả thêm chi tiết hồ sơ EBR (Lệnh nấu, công thức, giờ bắt đầu/kết thúc, đã khóa chưa, đã ký
    những gì) — tái dùng services/ebr.py::assemble() (đúng dữ liệu panel "Mẻ sản xuất" hiển thị),
    CHỈ gọi khi lọc đúng 1 mẻ vì assemble() khá nặng (dò genealogy/BOM), không hợp gọi 30 lần."""
    stmt = select(BatchExecution).order_by(BatchExecution.created_at.desc())
    rows = db.execute(stmt).scalars().all()
    if batch_code:
        rows = [b for b in rows if b.batch_code == batch_code]
        if not rows:
            return {"error": f"Không tìm thấy mẻ có mã {batch_code}"}
        from . import ebr as ebr_svc
        info = ebr_svc.assemble(db, rows[0])
        core = info["core"]
        return {"batch_code": rows[0].batch_code, "state": rows[0].state,
                "quality_status": rows[0].quality_status, "planned_qty": rows[0].planned_qty,
                "actual_qty": rows[0].actual_qty, "uom": rows[0].uom,
                "order_code": core.get("order_code"), "recipe": core.get("recipe"),
                "start_at": core.get("start_at"), "end_at": core.get("end_at"),
                "ebr_locked": info.get("locked"),
                "signatures": [{"meaning": s["meaning"], "by": s["by"], "role": s["role"],
                               "time": s["time"]} for s in info.get("signatures", [])]}
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
               "fifo_computed": l.get("fifo_computed"),
               # Người nhập/ngày tạo (lần ghi/sửa gần nhất), ngày cấp (= batch.start_at, khác
               # ngày tạo), cấp tự do (qua nút "Cấp 1 vật tư") — có sẵn trong batch_dispense_
               # summary() nhưng trước đây bị cắt bỏ khỏi tool AI (yêu cầu người dùng 2026-11-03:
               # "mở rộng đầy đủ"), xem dispense.py:920-927.
               "actor": l.get("actor"), "created_at": l.get("created_at"),
               "supply_date": l.get("supply_date"), "is_free": l.get("is_free")} for l in lines]
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


# ---- Mở rộng 2026-11-03 (yêu cầu người dùng: "mở rộng đầy đủ toàn bộ tính năng cho AI này tư
# vấn") — phủ nốt CIP/Bảo trì/OEE chi tiết/Điều độ/Lập lịch/Danh mục/CAPA chi tiết/EBR lock/
# ISA-88/Kho NVL theo khu vực/Bao bì/báo cáo hệ lọc-dây chuyền chiết. Cùng khuôn READ-ONLY.

def get_cip_status(db: Session, equipment_code: str = None, area: str = None) -> dict:
    """Lịch sử vệ sinh CIP (tối đa 30 lượt gần nhất) — lọc theo mã thiết bị và/hoặc khu vực."""
    from . import cip as cip_svc
    records = cip_svc.list_records(db, area=area, limit=200)
    if equipment_code:
        records = [r for r in records if r.get("equipment_code") == equipment_code]
        if not records:
            return {"error": f"Không tìm thấy lượt CIP nào cho thiết bị {equipment_code}"}
    return {"records": [{"cip_code": r["cip_code"], "equipment_code": r["equipment_code"],
                         "form_type_name": r["form_type_name"], "started_at": r["started_at"],
                         "ended_at": r["ended_at"], "result": r["result"],
                         "checked_by": r["checked_by"]} for r in records[:30]]}


def get_maintenance_status(db: Session, line: str = None) -> dict:
    """Sự cố dừng máy gần đây (downtime, tối đa 30) + kế hoạch bảo trì/hiệu chuẩn thiết bị đang
    đến hạn hoặc quá hạn — mirror routers/maintenance.py::list_plans (tự chuyển "planned" quá
    `scheduled_date` thành "overdue")."""
    from datetime import date
    from . import downtime as dt_svc
    from ..models.maintenance import Equipment, MaintenancePlan
    events = dt_svc.list_events(db, line=line, limit=30)
    today = date.today()
    plans = db.execute(select(MaintenancePlan).order_by(MaintenancePlan.scheduled_date)).scalars().all()
    eq_by_id = {e.equipment_id: e for e in db.execute(select(Equipment)).scalars().all()}
    due = []
    for p in plans:
        status = "overdue" if p.status == "planned" and p.scheduled_date < today else p.status
        if status not in ("planned", "overdue"):
            continue
        eq = eq_by_id.get(p.equipment_id)
        due.append({"equipment_code": eq.code if eq else None, "plan_type": p.plan_type,
                    "scheduled_date": p.scheduled_date, "status": status})
    return {"downtime_events": [{"line": e["line"], "shift_date": e["shift_date"],
                                 "reason_label": e["reason_label"], "loss_category": e["loss_category"],
                                 "minutes": e["minutes"]} for e in events],
            "maintenance_due_or_overdue": due[:30]}


def get_oee_detail(db: Session, line_code: str, year: int = None, month: int = None) -> dict:
    """OEE theo kỳ (tháng/quý/13 tuần gần nhất) cho 1 line — chi tiết hơn get_oee (vốn chỉ đọc
    thô OEERecord), tái dùng đúng phép tính của màn "OEE/Dừng máy"."""
    from datetime import date as date_cls
    from . import oee_summary
    today = date_cls.today()
    year = year or today.year
    month = month or today.month
    s = oee_summary.summary_dashboard(db, line_code, year, month)
    trim = lambda pts: [{"label": p["label"], "opi": p["opi"], "opi_target": p["opi_target"],
                         "efficiency": p["efficiency"], "unplanned_pct": p["unplanned_pct"]}
                        for p in pts]
    return {"line_code": line_code, "year": year, "month": month,
            "monthly": trim(s["monthly"]), "quarterly": trim(s["quarterly"]),
            "weekly_last_13": trim(s["weekly"])}


def get_wo_status(db: Session, wo_code: str = None, line: str = None) -> dict:
    """Bảng điều độ Lệnh sản xuất (WO): kế hoạch/thực tế, tiến độ %, có đóng/hoàn thành được chưa."""
    from . import workorders as wo_svc
    orders = wo_svc.board(db, line=line)
    if wo_code:
        orders = [o for o in orders if o.get("wo_code") == wo_code]
        if not orders:
            return {"error": f"Không tìm thấy Lệnh SX có mã {wo_code}"}
    return {"orders": [{"wo_code": o["wo_code"], "line": o["line"], "shift": o["shift"],
                        "scheduled_date": o["scheduled_date"], "priority": o["priority"],
                        "status": o["status"], "planned_qty": o["planned_qty"],
                        "actual_qty": o["actual_qty"], "completion_pct": o["completion_pct"],
                        "can_complete": o["can_complete"], "can_close": o["can_close"]}
                       for o in orders[:30]]}


def get_schedule_conflicts(db: Session) -> dict:
    """Lập lịch: phát hiện chồng lấn tài nguyên (cùng dây chuyền/thiết bị 2 lệnh trùng giờ) và
    lệnh thiếu NVL dự kiến — "ok": true nghĩa là lịch hiện tại không có xung đột nào."""
    from . import scheduler as sched_svc
    c = sched_svc.conflicts(db)
    return {"ok": c["ok"], "overlaps": c["overlaps"][:30], "material_short": c["material_short"][:30]}


def get_product_info(db: Session, product_code: str = None) -> dict:
    """Danh mục Dịch bia (Product) — công thức/loại bia đang chạy qua nấu→lên men→lọc."""
    from ..models.master import BeerType, Product
    rows = db.execute(select(Product).order_by(Product.code)).scalars().all()
    if product_code:
        rows = [p for p in rows if p.code == product_code]
        if not rows:
            return {"error": f"Không tìm thấy dịch bia có mã {product_code}"}
    beer_types = {b.beer_type_id: b.name for b in db.execute(select(BeerType)).scalars().all()}
    return {"products": [{"code": p.code, "name": p.name, "uom": p.uom,
                          "beer_type_name": beer_types.get(p.beer_type_id),
                          "ferment_days_std": p.ferment_days_std} for p in rows[:30]]}


def get_material_info(db: Session, material_code: str = None) -> dict:
    """Danh mục Vật tư/NVL — đơn vị, nhóm, ngưỡng tồn tối thiểu."""
    from ..models.master import Material
    rows = db.execute(select(Material).order_by(Material.code)).scalars().all()
    if material_code:
        rows = [m for m in rows if m.code == material_code]
        if not rows:
            return {"error": f"Không tìm thấy vật tư có mã {material_code}"}
    return {"materials": [{"code": m.code, "name": m.name, "uom": m.uom, "category": m.category,
                           "stock_min": m.stock_min} for m in rows[:30]]}


def get_capa_detail(db: Session, capa_code: str = None) -> dict:
    """Chi tiết CAPA (nguyên nhân gốc, kế hoạch khắc phục, hạn xử lý, đã KCS/Giám đốc duyệt
    chưa) — đầy đủ hơn get_capa_status (vốn chỉ có mã/tiêu đề/trạng thái)."""
    from . import quality_adv
    rows = quality_adv.list_capa(db)
    if capa_code:
        rows = [c for c in rows if c["capa_code"] == capa_code]
        if not rows:
            return {"error": f"Không tìm thấy CAPA có mã {capa_code}"}
    return {"capa": [{"capa_code": c["capa_code"], "title": c["title"], "capa_type": c["capa_type"],
                      "severity": c["severity"], "state": c["state"], "owner": c["owner"],
                      "root_cause": c["root_cause"], "action_plan": c["action_plan"],
                      "due_date": c["due_date"], "effectiveness": c["effectiveness"],
                      "kcs_approved_by": c["kcs_approved_by"],
                      "director_approved_by": c["director_approved_by"]} for c in rows[:30]]}


_EBR_SCOPE_MODEL = {
    "batch": ("batch_code", "batch_id", "ebr_locked"),
    "tank": ("tank_code", "tank_id", "locked"),
    "filter_lot": ("filter_lot_code", "filter_lot_id", "locked"),
    "pack_lot": ("pack_lot_code", "pack_lot_id", "locked"),
}


def get_ebr_lock_status(db: Session, scope_type: str, code: str) -> dict:
    """Hồ sơ EBR của 1 mẻ/tank lên men/lô lọc/lô thành phẩm đã ký những gì, đã khóa chưa — KHÔNG
    trả nội dung đầy đủ hồ sơ (dùng get_batch_status cho mẻ nấu nếu cần). `scope_type` là 1
    trong: batch, tank, filter_lot, pack_lot."""
    from ..models.batch_pipeline import BatchFilterLot, BatchPackLot, BatchTank
    from ..models.signature import Signature
    model_by_scope = {"batch": BatchExecution, "tank": BatchTank,
                      "filter_lot": BatchFilterLot, "pack_lot": BatchPackLot}
    if scope_type not in _EBR_SCOPE_MODEL:
        return {"error": f"scope_type phải là 1 trong: {', '.join(_EBR_SCOPE_MODEL)}"}
    code_attr, id_attr, locked_attr = _EBR_SCOPE_MODEL[scope_type]
    model = model_by_scope[scope_type]
    obj = db.execute(select(model).where(getattr(model, code_attr) == code)).scalar_one_or_none()
    if not obj:
        return {"error": f"Không tìm thấy {scope_type} có mã {code}"}
    obj_id = getattr(obj, id_attr)
    sigs = db.execute(select(Signature).where(Signature.scope_type == "ebr", Signature.scope_id == obj_id)
                      .order_by(Signature.signed_at)).scalars().all()
    return {"scope_type": scope_type, "code": code, "locked": bool(getattr(obj, locked_attr)),
            "signatures": [{"meaning": s.meaning, "by": s.signed_by, "role": s.role,
                           "time": s.signed_at.isoformat()} for s in sigs]}


def get_isa88_status(db: Session, batch_code: str) -> dict:
    """Tiến độ thực thi ISA-88 của 1 mẻ nấu: % hoàn thành + trạng thái từng phase."""
    from . import isa88 as isa88_svc
    batch = db.execute(select(BatchExecution).where(
        BatchExecution.batch_code == batch_code)).scalar_one_or_none()
    if not batch:
        return {"error": f"Không tìm thấy mẻ có mã {batch_code}"}
    s = isa88_svc.status(db, batch.batch_id)
    phases = [{"unit_procedure": up["unit_procedure"], "operation": o["operation"],
              "phase": p["phase"], "state": p["state"], "operator": p["operator"]}
             for up in s["unit_procedures"] for o in up["operations"] for p in o["phases"]]
    return {"batch_code": s["batch_code"], "completion_pct": s["completion_pct"],
            "phases_done": s["phases_done"], "phases_total": s["phases_total"],
            "phases": phases}


def get_pending_material_requests(db: Session, status: str = None) -> dict:
    """Đề nghị cấp/xuất NVL đang chờ xử lý — mỗi phiếu kèm số dòng còn "pending" (chưa cấp)."""
    reqs = wh.list_requests(db, limit=200)
    out = []
    for r in reqs:
        pending = [l for l in r["lines"] if l["status"] == "pending"]
        if status == "pending" and not pending:
            continue
        out.append({"request_code": r["request_code"], "requested_by": r["requested_by"],
                    "requested_at": r["requested_at"], "source_label": r["source_label"],
                    "line_count": len(r["lines"]), "pending_count": len(pending)})
    return {"requests": out[:30]}


def get_packaging_status(db: Session) -> dict:
    """Bao bì tuần hoàn (vỏ chai/két-gông/keg): tồn kho vs đang lưu hành, theo nhóm."""
    from . import packaging as pkg_svc
    return pkg_svc.summary(db)


def get_filter_production_report(db: Session, days: int = 30) -> dict:
    """Báo cáo hệ lọc (mỗi dòng = 1 mẻ lọc): sản lượng, phối hay không, mẻ cuối hay không, xếp
    loại hiệu suất (Thấp/Bình thường/Cao)."""
    from . import dashboard as dashboard_svc
    items = dashboard_svc.filter_production_report(db, days=days)
    return {"days": days, "items": [{"batch_seq_no": i.get("batch_seq_no"), "ended_at": i.get("ended_at"),
                                     "v_l": i.get("v_l"), "beer_type_name": i.get("beer_type_name"),
                                     "classification_label": i.get("classification_label"),
                                     "is_final": i.get("is_final"), "is_blend": i.get("is_blend")}
                                    for i in items[:30]]}


def get_pack_line_report(db: Session, days: int = 30) -> dict:
    """Báo cáo dây chuyền chiết: số lần chiết + tổng thời gian đã chiết mỗi dây chuyền trong kỳ."""
    from . import dashboard as dashboard_svc
    r = dashboard_svc.pack_line_gantt_report(db, days=days)
    return {"from": r["from"], "to": r["to"],
            "lines": [{"line": l["line"], "line_name": l["line_name"], "lot_count": l["lot_count"],
                      "total_duration_hours": l["total_duration_hours"]} for l in r["lines"][:30]]}


# ---- Registry: name -> (fn, description, input_schema) ----
TOOLS = {
    "get_inventory_status": {
        "fn": get_inventory_status,
        "description": "Xem tồn kho nguyên vật liệu hiện tại và các lô sắp/đã hết hạn.",
        "input_schema": {"type": "object", "properties": {
            "below_only": {"type": "boolean", "description": "Chỉ lấy mục dưới mức (tùy chọn)"},
            "location": {"type": "string", "description": "'Kho công ty' hoặc 'Kho phân xưởng'. Bỏ trống = gộp cả 2."}}},
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
    "get_cip_status": {
        "fn": get_cip_status,
        "description": "Lịch sử vệ sinh CIP gần đây, lọc theo thiết bị và/hoặc khu vực (Nấu/Lên men/Lọc/Chiết).",
        "input_schema": {"type": "object", "properties": {
            "equipment_code": {"type": "string", "description": "Mã thiết bị. Bỏ trống = tất cả."},
            "area": {"type": "string", "description": "Khu vực: nau/len_men/loc/chiet. Bỏ trống = tất cả."}}},
    },
    "get_maintenance_status": {
        "fn": get_maintenance_status,
        "description": "Sự cố dừng máy gần đây + kế hoạch bảo trì/hiệu chuẩn đang đến hạn hoặc quá hạn.",
        "input_schema": {"type": "object", "properties": {
            "line": {"type": "string", "description": "Lọc sự cố dừng máy theo line. Bỏ trống = tất cả."}}},
    },
    "get_oee_detail": {
        "fn": get_oee_detail,
        "description": "OEE chi tiết theo kỳ (xu hướng tháng/quý/13 tuần gần nhất) cho 1 dây chuyền.",
        "input_schema": {"type": "object", "properties": {
            "line_code": {"type": "string", "description": "Mã dây chuyền, vd 'chiet-01'."},
            "year": {"type": "integer", "description": "Năm. Bỏ trống = năm hiện tại."},
            "month": {"type": "integer", "description": "Tháng (1-12). Bỏ trống = tháng hiện tại."}},
            "required": ["line_code"]},
    },
    "get_wo_status": {
        "fn": get_wo_status,
        "description": "Bảng điều độ Lệnh sản xuất (WO): kế hoạch/thực tế, tiến độ, đã đóng/hoàn thành được chưa.",
        "input_schema": {"type": "object", "properties": {
            "wo_code": {"type": "string", "description": "Mã Lệnh SX. Bỏ trống = tất cả."},
            "line": {"type": "string", "description": "Lọc theo line. Bỏ trống = tất cả."}}},
    },
    "get_schedule_conflicts": {
        "fn": get_schedule_conflicts,
        "description": "Kiểm tra Lập lịch: có chồng lấn tài nguyên hoặc lệnh thiếu NVL dự kiến không.",
        "input_schema": {"type": "object", "properties": {}},
    },
    "get_product_info": {
        "fn": get_product_info,
        "description": "Danh mục Dịch bia (Product): đơn vị, Loại bia, số ngày lên men chuẩn.",
        "input_schema": {"type": "object", "properties": {
            "product_code": {"type": "string", "description": "Mã dịch bia. Bỏ trống = tất cả."}}},
    },
    "get_material_info": {
        "fn": get_material_info,
        "description": "Danh mục Vật tư/NVL: đơn vị, nhóm, ngưỡng tồn tối thiểu.",
        "input_schema": {"type": "object", "properties": {
            "material_code": {"type": "string", "description": "Mã vật tư. Bỏ trống = tất cả."}}},
    },
    "get_capa_detail": {
        "fn": get_capa_detail,
        "description": "Chi tiết CAPA: nguyên nhân gốc, kế hoạch khắc phục, hạn xử lý, đã duyệt KCS/Giám đốc chưa.",
        "input_schema": {"type": "object", "properties": {
            "capa_code": {"type": "string", "description": "Mã CAPA. Bỏ trống = tất cả đang mở."}}},
    },
    "get_ebr_lock_status": {
        "fn": get_ebr_lock_status,
        "description": "Hồ sơ EBR (mẻ nấu/tank lên men/lô lọc/lô thành phẩm) đã ký gì, đã khóa chưa.",
        "input_schema": {"type": "object", "properties": {
            "scope_type": {"type": "string", "description": "batch | tank | filter_lot | pack_lot"},
            "code": {"type": "string", "description": "Mã tương ứng (mã mẻ/tank/lô lọc/lô thành phẩm)"}},
            "required": ["scope_type", "code"]},
    },
    "get_isa88_status": {
        "fn": get_isa88_status,
        "description": "Tiến độ thực thi ISA-88 của 1 mẻ nấu: % hoàn thành + trạng thái từng phase.",
        "input_schema": {"type": "object", "properties": {
            "batch_code": {"type": "string", "description": "Mã mẻ Braumat"}},
            "required": ["batch_code"]},
    },
    "get_pending_material_requests": {
        "fn": get_pending_material_requests,
        "description": "Đề nghị cấp/xuất NVL đang chờ xử lý, kèm số dòng còn chưa cấp.",
        "input_schema": {"type": "object", "properties": {
            "status": {"type": "string", "description": "'pending' = chỉ phiếu còn dòng chưa cấp. Bỏ trống = tất cả."}}},
    },
    "get_packaging_status": {
        "fn": get_packaging_status,
        "description": "Bao bì tuần hoàn (vỏ chai/két-gông/keg): tồn kho vs đang lưu hành, theo nhóm.",
        "input_schema": {"type": "object", "properties": {}},
    },
    "get_filter_production_report": {
        "fn": get_filter_production_report,
        "description": "Báo cáo hệ lọc theo mẻ lọc: sản lượng, phối hay không, xếp loại hiệu suất.",
        "input_schema": {"type": "object", "properties": {
            "days": {"type": "integer", "description": "Số ngày gần nhất (mặc định 30)."}}},
    },
    "get_pack_line_report": {
        "fn": get_pack_line_report,
        "description": "Báo cáo dây chuyền chiết: số lần chiết + tổng thời gian đã chiết mỗi dây chuyền.",
        "input_schema": {"type": "object", "properties": {
            "days": {"type": "integer", "description": "Số ngày gần nhất (mặc định 30)."}}},
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
