"""Báo cáo sản xuất."""

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..database import get_db
from ..security import User, get_current_user

router = APIRouter(prefix="/api/reports", tags=["reports"])

# Chỉ gộp các mẻ ĐÃ thực thi (đã/đang tiêu thụ) — bỏ qua mẻ chưa chạy/đã hủy để không thổi
# phồng định mức (planned mà actual≈0). Xem material_norm() bên dưới.
_MATERIAL_NORM_EXECUTED_STATES = {"running", "held", "completed", "closed"}


# ---- BC định mức NVL: gộp định mức (đã scale theo SL kế hoạch) ↔ thực tế tiêu thụ theo vật
# tư qua nhiều mẻ (Mẻ sản xuất/BatchExecution) ----
@router.get("/material-norm")
def material_norm(days: int = 90, product_id: str = None, db: Session = Depends(get_db),
                  user: User = Depends(get_current_user)):
    from ..common import utcnow
    from ..models.batches import BatchExecution
    from ..services import bom as bom_svc
    from sqlalchemy import select

    since = utcnow() - timedelta(days=days)
    stmt = select(BatchExecution).where(BatchExecution.created_at >= since,
                                        BatchExecution.state.in_(_MATERIAL_NORM_EXECUTED_STATES))
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


# ---- Tổng hợp cho Tổng quan (dashboard): lệnh/mẻ nấu-lọc-chiết + sản lượng chiết lon/keg ----
@router.get("/dashboard-summary")
def dashboard_summary(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    from ..services import dashboard as dashboard_svc
    return dashboard_svc.production_summary(db)


@router.get("/qc-attention-alerts")
def qc_attention_alerts(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    from ..services import dashboard as dashboard_svc
    return dashboard_svc.qc_attention_alerts(db)


@router.get("/overdue-action-alerts")
def overdue_action_alerts(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    from ..services import dashboard as dashboard_svc
    return dashboard_svc.overdue_action_alerts(db)


@router.get("/low-yield-filter-alerts")
def low_yield_filter_alerts(days: int = 5, limit: int = 5, db: Session = Depends(get_db),
                            user: User = Depends(get_current_user)):
    from ..services import dashboard as dashboard_svc
    return dashboard_svc.low_yield_filter_alerts(db, days, limit)


@router.get("/bottled-not-approved")
def bottled_not_approved(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    from ..services import dashboard as dashboard_svc
    return dashboard_svc.bottled_not_approved_report(db)


