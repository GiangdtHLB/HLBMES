"""Báo cáo sản xuất — BC định mức NVL (tổng hợp nhiều mẻ)."""

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..common import utcnow
from ..database import get_db
from ..models.batches import BatchExecution
from ..security import User, get_current_user
from ..services import bom as bom_svc

router = APIRouter(prefix="/api/reports", tags=["reports"])

# Chỉ gộp các mẻ ĐÃ thực thi (đã/đang tiêu thụ) — bỏ qua mẻ chưa chạy/đã hủy
# để không thổi phồng định mức (planned mà actual≈0).
EXECUTED_STATES = {"running", "held", "completed", "closed"}


@router.get("/material-norm")
def material_norm(days: int = 3650, product_id: str = None, db: Session = Depends(get_db),
                  user: User = Depends(get_current_user)):
    """BC định mức NVL: gộp định mức (đã scale) ↔ thực tế tiêu thụ theo vật tư qua nhiều mẻ."""
    since = utcnow() - timedelta(days=days)
    stmt = select(BatchExecution).where(BatchExecution.created_at >= since,
                                        BatchExecution.state.in_(EXECUTED_STATES))
    if product_id:
        stmt = stmt.where(BatchExecution.product_id == product_id)
    batches = db.execute(stmt.order_by(BatchExecution.created_at)).scalars().all()

    agg = {}   # material_code -> {planned, actual, uom, tol, batch_ids}
    batch_rows = []
    for b in batches:
        cmp = bom_svc.compare_batch(db, b)
        if not cmp["lines"]:
            continue
        b_planned = b_actual = 0.0
        for l in cmp["lines"]:
            a = agg.setdefault(l["material_code"], {"planned": 0.0, "actual": 0.0,
                                                    "uom": l["uom"], "tol": 0.0, "batch_ids": set()})
            a["planned"] += l["planned"]
            a["actual"] += l["actual"]
            a["tol"] = max(a["tol"], l.get("tol_pct", 0) or 0)
            a["batch_ids"].add(b.batch_id)
            b_planned += l["planned"]
            b_actual += l["actual"]
        batch_rows.append({"batch_code": b.batch_code, "state": b.state,
                           "planned_qty": b.planned_qty, "uom": b.uom,
                           "planned_total": round(b_planned, 3), "actual_total": round(b_actual, 3)})

    materials = []
    for code, a in agg.items():
        planned = round(a["planned"], 3)
        actual = round(a["actual"], 3)
        # Dùng cùng quy ước dung sai theo vật tư như đối chiếu chi tiết mẻ.
        diff, pct, status = bom_svc._classify(planned, actual, a["tol"])
        materials.append({"material_code": code, "uom": a["uom"], "batches": len(a["batch_ids"]),
                          "tol_pct": a["tol"], "planned": planned, "actual": actual,
                          "diff": diff, "pct": pct, "status": status})
    materials.sort(key=lambda x: abs(x["pct"]), reverse=True)
    return {"days": days, "batch_count": len(batch_rows), "materials": materials,
            "batches": batch_rows}


# ---- Báo cáo sản lượng chiết (lon) thật từ CSDL SCADA ngoài (SqlConnection.purpose="filling") ----
@router.get("/filling-bounds")
def filling_bounds(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    from ..services import filling_external
    return filling_external.data_bounds(db)


@router.get("/filling-realtime")
def filling_realtime(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Trạng thái tức thời máy chiết lon 30K (bảng 30K_Realtime, cùng kết nối purpose="filling")."""
    from ..services import filling_external
    return filling_external.filling_realtime_status(db)


# ---- Trạm quan trắc nước thải Hạ Long (SqlConnection.purpose="wastewater") ----
@router.get("/wastewater-realtime")
def wastewater_realtime(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Snapshot tức thời trạm quan trắc nước thải Hạ Long (bảng QT_Realtime)."""
    from ..services import wastewater_external
    return wastewater_external.wastewater_realtime_status(db)


@router.get("/filling-report")
def filling_report(date_from: datetime = None, date_to: datetime = None,
                   db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    from ..services import filling_external
    if not date_from or not date_to:
        # Mặc định: đúng 1 ngày gần nhất có dữ liệu — Ca 1 (06h) của ngày đó tới Ca 3 (06h ngày kế).
        bounds = filling_external.data_bounds(db)
        ref_day = datetime.fromisoformat(bounds["max_date"])
        date_from = date_from or ref_day.replace(hour=filling_external.SHIFT_ANCHOR_HOUR, minute=0, second=0)
        date_to = date_to or (date_from + timedelta(hours=24))
    return filling_external.filling_report(db, date_from, date_to)


# ---- Báo cáo sản lượng chiết KEG thật từ CSDL SCADA ngoài (SqlConnection.purpose="filling_keg") ----
@router.get("/keg-bounds")
def keg_bounds(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    from ..services import keg_external
    return keg_external.data_bounds(db)


@router.get("/keg-report")
def keg_report(date_from: datetime = None, date_to: datetime = None,
              db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    from ..services import keg_external
    if not date_from or not date_to:
        # Mặc định: ngày hôm qua — Ca 1 (06h) hôm qua tới Ca 3 (06h hôm nay).
        ref_day = (utcnow() - timedelta(days=1)).replace(hour=6, minute=0, second=0, microsecond=0)
        date_from = date_from or ref_day
        date_to = date_to or (date_from + timedelta(hours=24))
    return keg_external.keg_report(db, date_from, date_to)


# ---- Báo cáo trạng thái lô tổng hợp (Nấu/Lên men/Lọc/Chiết) ----
@router.get("/lo-status")
def lo_status(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    from ..services import lo_status as lo_status_svc
    return lo_status_svc.lo_status_report(db)


# ---- Tổng hợp cho Tổng quan (dashboard): lệnh/mẻ nấu-lọc-chiết + sản lượng chiết lon/keg ----
@router.get("/dashboard-summary")
def dashboard_summary(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    from ..services import dashboard as dashboard_svc
    return dashboard_svc.production_summary(db)


@router.get("/qc-attention-alerts")
def qc_attention_alerts(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    from ..services import dashboard as dashboard_svc
    return dashboard_svc.qc_attention_alerts(db)


# ---- Báo cáo xuất thành phẩm theo ca (Ca 1/2/3, giống Năng lượng) ----
@router.get("/finished-goods-shift-report")
def finished_goods_shift_report(date_from: datetime = None, date_to: datetime = None,
                                db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    from ..services import wms as wms_svc
    if not date_from or not date_to:
        # Mặc định: ngày hôm qua — Ca 1 (06h) hôm qua tới Ca 3 (06h hôm nay), giống keg_report.
        ref_day = (utcnow() - timedelta(days=1)).replace(hour=6, minute=0, second=0, microsecond=0)
        date_from = date_from or ref_day
        date_to = date_to or (date_from + timedelta(hours=24))
    result = wms_svc.finished_goods_shift_report(db, date_from, date_to)
    result.update({"date_from": date_from.isoformat(), "date_to": date_to.isoformat()})
    return result


@router.get("/low-yield-filter-alerts")
def low_yield_filter_alerts(days: int = 5, limit: int = 5, db: Session = Depends(get_db),
                            user: User = Depends(get_current_user)):
    from ..services import dashboard as dashboard_svc
    return dashboard_svc.low_yield_filter_alerts(db, days, limit)


# ---- Báo cáo tồn kho thành phẩm theo tuổi lô (cho khối kinh doanh đẩy nhanh bán hàng) ----
@router.get("/inventory-aging")
def inventory_aging(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    from ..services import ops_setting as ops_setting_svc
    from ..services import wms as wms_svc
    settings = ops_setting_svc.get_settings(db)
    return wms_svc.lot_aging_report(db, settings.aging_caution_days, settings.aging_warning_days,
                                    settings.aging_critical_days)


# ---- Báo cáo sản lượng lọc theo mẻ (Thấp/Bình thường/Cao so với ngưỡng OpsSetting) ----
@router.get("/filter-yield-report")
def filter_yield_report(date_from: datetime = None, date_to: datetime = None, group_by: str = "day",
                        db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    from ..services import filter_yield_report as filter_yield_svc
    from ..services import ops_setting as ops_setting_svc
    if not date_from or not date_to:
        # Mặc định: 90 ngày gần nhất.
        date_to = date_to or utcnow()
        date_from = date_from or (date_to - timedelta(days=90))
    settings = ops_setting_svc.get_settings(db)
    return filter_yield_svc.filter_yield_report(db, date_from, date_to, settings.filter_yield_low_hl,
                                                settings.filter_yield_high_hl, group_by)


# ---- Báo cáo sản lượng lọc theo TỪNG DÒNG "mẻ lọc số" (kèm truy vết tank LM/mẻ nấu nguồn) ----
@router.get("/filter-line-yield-report")
def filter_line_yield_report(date_from: datetime = None, date_to: datetime = None,
                             db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    from ..services import filter_yield_report as filter_yield_svc
    from ..services import ops_setting as ops_setting_svc
    if not date_from or not date_to:
        date_to = date_to or utcnow()
        date_from = date_from or (date_to - timedelta(days=90))
    settings = ops_setting_svc.get_settings(db)
    return filter_yield_svc.filter_line_yield_report(db, date_from, date_to,
                                                     settings.filter_line_yield_low_l,
                                                     settings.filter_line_yield_high_l)
