"""Quét mã (kiosk/scanner): phân giải 1 mã → loại + dữ liệu liên quan.

Dùng cho giao diện kiosk/tablet: quét lô/mẻ/lệnh để tra cứu và thao tác nhanh."""

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models.batches import BatchExecution
from ..models.materials import MaterialLot
from ..models.orders import ProductionOrder
from ..models.workorder import WorkOrder
from ..security import User, get_current_user

router = APIRouter(prefix="/api/scan", tags=["scan"])


@router.get("")
def scan(code: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    code = (code or "").strip()
    # Lô vật tư / thành phẩm
    lot = db.execute(select(MaterialLot).where(MaterialLot.lot_code == code)).scalar_one_or_none()
    if lot:
        return {"type": "lot", "data": {"lot_id": lot.lot_id, "lot_code": lot.lot_code,
                "lot_type": lot.lot_type, "quantity": lot.quantity, "uom": lot.uom,
                "status": lot.status, "location": lot.location}}
    # Mẻ
    b = db.execute(select(BatchExecution).where(BatchExecution.batch_code == code)).scalar_one_or_none()
    if b:
        return {"type": "batch", "data": {"batch_id": b.batch_id, "batch_code": b.batch_code,
                "state": b.state, "quality_status": b.quality_status, "planned_qty": b.planned_qty,
                "actual_qty": b.actual_qty, "uom": b.uom, "ebr_locked": bool(b.ebr_locked)}}
    # Lệnh sản xuất (work order)
    wo = db.execute(select(WorkOrder).where(WorkOrder.wo_code == code)).scalar_one_or_none()
    if wo:
        return {"type": "work_order", "data": {"wo_id": wo.wo_id, "wo_code": wo.wo_code,
                "status": wo.status, "line": wo.line, "shift": wo.shift, "planned_qty": wo.planned_qty,
                "uom": wo.uom}}
    # Lệnh ERP
    po = db.execute(select(ProductionOrder).where(ProductionOrder.order_code == code)).scalar_one_or_none()
    if po:
        return {"type": "production_order", "data": {"order_id": po.order_id, "order_code": po.order_code,
                "status": po.status, "planned_qty": po.planned_qty, "uom": po.uom}}

    # Gợi ý: tìm gần đúng (prefix) lô đang available
    near = db.execute(select(MaterialLot.lot_code).where(MaterialLot.lot_code.like(f"%{code}%")).limit(5)).scalars().all()
    return {"type": "unknown", "code": code, "suggestions": near}


@router.get("/running-batches")
def running_batches(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Các mẻ đang chạy — để kiosk cấp liệu nhanh."""
    rows = db.execute(select(BatchExecution).where(BatchExecution.state == "running")).scalars().all()
    return [{"batch_id": b.batch_id, "batch_code": b.batch_code, "planned_qty": b.planned_qty} for b in rows]
