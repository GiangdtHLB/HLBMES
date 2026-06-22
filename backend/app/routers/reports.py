"""Báo cáo sản xuất — BC định mức NVL (tổng hợp nhiều mẻ)."""

from datetime import timedelta

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
