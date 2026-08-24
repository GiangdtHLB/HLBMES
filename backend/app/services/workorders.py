"""Nghiệp vụ Lệnh sản xuất (Work Order) & điều độ (tài liệu §7.1)."""

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..audit import record_audit
from ..common import WORKORDER_TRANSITIONS, WorkOrderState, new_id, utcnow
from ..errors import DomainError, NotFoundError
from ..models.batches import BatchExecution
from ..models.orders import ProductionOrder
from ..models.recipes import RecipeVersion
from ..models.workorder import WorkOrder
from ..security import User, filter_by_scope, require_perm, require_scope
from . import batches as batch_svc


def create_wo(db: Session, payload: dict, user: User) -> WorkOrder:
    require_perm(user, "wo.manage")
    require_scope(user, "lines", payload.get("line"))
    po = db.get(ProductionOrder, payload["production_order_id"])
    if not po:
        raise NotFoundError("Production order không tồn tại.")
    rv_id = payload.get("recipe_version_id")
    # Lệnh SX (ERP) giờ chỉ chọn Loại bia lúc lập, po.product_id thường None cho tới khi Lệnh
    # nấu chọn Version — Work Order cần 1 Dịch bia CỤ THỂ (WorkOrder.product_id bắt buộc, dùng
    # thật cho Mẻ sản xuất/BOM), nên nếu PO chưa có product_id thì bắt buộc chọn Version ngay
    # lúc lập Work Order để suy ra Dịch bia (RecipeVersion.product_id).
    product_id = po.product_id
    if not product_id:
        if not rv_id:
            raise DomainError("Lệnh SX (ERP) này chưa xác định Dịch bia — chọn Version lúc lập lệnh điều độ.")
        rv = db.get(RecipeVersion, rv_id)
        if not rv:
            raise NotFoundError("Recipe version không tồn tại.")
        product_id = rv.product_id
    sd = payload.get("scheduled_date") or date.today()
    wo = WorkOrder(
        wo_id=new_id(),
        wo_code=payload.get("wo_code") or f"WO-{utcnow():%Y%m%d}-{new_id()[:5].upper()}",
        production_order_id=po.order_id,
        product_id=product_id,
        recipe_version_id=rv_id,
        planned_qty=float(payload.get("planned_qty") or po.planned_qty),
        uom=payload.get("uom") or po.uom,
        line=payload.get("line"),
        shift=payload.get("shift", "A"),
        scheduled_date=sd,
        priority=int(payload.get("priority", 5)),
        status=WorkOrderState.PLANNED.value,
        note=payload.get("note"),
        created_by=user.username,
    )
    db.add(wo)
    record_audit(db, entity_type="work_order", entity_id=wo.wo_id, action="create", actor=user,
                 after={"wo_code": wo.wo_code, "qty": wo.planned_qty, "line": wo.line, "shift": wo.shift})
    db.commit()
    db.refresh(wo)
    return wo


def transition(db: Session, wo_id: str, target: str, user: User, reason: str = None) -> WorkOrder:
    require_perm(user, "wo.manage")
    wo = _get(db, wo_id)
    require_scope(user, "lines", wo.line)
    try:
        target_state = WorkOrderState(target)
    except ValueError:
        raise DomainError(f"Trạng thái không hợp lệ: {target}")
    current = WorkOrderState(wo.status)
    if target_state not in WORKORDER_TRANSITIONS[current]:
        raise DomainError(f"Không thể chuyển lệnh từ {current.value} sang {target}.")
    before = {"status": wo.status}
    wo.status = target_state.value
    record_audit(db, entity_type="work_order", entity_id=wo.wo_id, action=f"transition:{target}",
                 actor=user, before=before, after={"status": wo.status}, reason=reason)
    db.commit()
    db.refresh(wo)
    return wo


def dispatch(db: Session, wo_id: str, user: User, recipe_version_id: str = None,
             batch_code: str = None, planned_qty: float = None, allow_shortage: bool = False) -> dict:
    """Điều độ: phát mẻ từ lệnh sản xuất (tạo BatchExecution, đặt WO → in_progress)."""
    require_perm(user, "wo.dispatch")
    wo = _get(db, wo_id)
    require_scope(user, "lines", wo.line)
    if wo.status not in (WorkOrderState.RELEASED.value, WorkOrderState.IN_PROGRESS.value):
        raise DomainError("Chỉ dispatch lệnh đã 'released' (hoặc đang chạy).")
    rv_id = recipe_version_id or wo.recipe_version_id
    if not rv_id:
        raise DomainError("Chưa chọn recipe version để dispatch.")
    batch = batch_svc.create_batch(db, wo.production_order_id, rv_id, user,
                                   batch_code=batch_code,
                                   planned_qty=planned_qty if planned_qty is not None else wo.planned_qty,
                                   allow_shortage=allow_shortage, work_order_id=wo.wo_id)
    if wo.status == WorkOrderState.RELEASED.value:
        wo.status = WorkOrderState.IN_PROGRESS.value
    record_audit(db, entity_type="work_order", entity_id=wo.wo_id, action="dispatch", actor=user,
                 after={"batch_code": batch.batch_code})
    db.commit()
    return {"wo_id": wo.wo_id, "wo_status": wo.status, "batch_id": batch.batch_id,
            "batch_code": batch.batch_code}


def rollup(db: Session, wo: WorkOrder) -> dict:
    """Planned vs actual: gộp sản lượng thực tế các mẻ thuộc lệnh."""
    batches = db.execute(select(BatchExecution).where(
        BatchExecution.work_order_id == wo.wo_id)).scalars().all()
    actual = sum(b.actual_qty or 0 for b in batches)
    pct = round(actual / wo.planned_qty * 100, 1) if wo.planned_qty else 0.0
    return {"batches": len(batches), "actual_qty": round(actual, 3), "completion_pct": pct,
            "batch_list": [{"batch_code": b.batch_code, "state": b.state,
                            "quality_status": b.quality_status, "actual_qty": b.actual_qty}
                           for b in batches]}


def board(db: Session, date_from: date = None, date_to: date = None, line: str = None,
          user: User = None) -> list:
    """Bảng điều độ: danh sách lệnh + planned/actual, lọc theo ngày/line.

    Nếu truyền `user`, lọc thêm theo phạm vi (scope) line của tài khoản (§10.2)."""
    stmt = select(WorkOrder)
    if date_from:
        stmt = stmt.where(WorkOrder.scheduled_date >= date_from)
    if date_to:
        stmt = stmt.where(WorkOrder.scheduled_date <= date_to)
    if line:
        stmt = stmt.where(WorkOrder.line == line)
    wos = db.execute(stmt.order_by(WorkOrder.scheduled_date, WorkOrder.shift,
                                   WorkOrder.priority)).scalars().all()
    out = []
    for wo in wos:
        r = rollup(db, wo)
        out.append({"wo_id": wo.wo_id, "wo_code": wo.wo_code, "product_id": wo.product_id,
                    "production_order_id": wo.production_order_id, "recipe_version_id": wo.recipe_version_id,
                    "planned_qty": wo.planned_qty, "uom": wo.uom, "line": wo.line, "shift": wo.shift,
                    "scheduled_date": wo.scheduled_date, "priority": wo.priority, "status": wo.status,
                    "note": wo.note, "actual_qty": r["actual_qty"], "completion_pct": r["completion_pct"],
                    "batches": r["batches"]})
    if user is not None:
        out = filter_by_scope(user, out, "lines", "line")
    return out


def _get(db: Session, wo_id: str) -> WorkOrder:
    wo = db.get(WorkOrder, wo_id)
    if not wo:
        raise NotFoundError("Lệnh sản xuất không tồn tại.")
    return wo


def delete_wo(db: Session, wo_id: str, user: User) -> None:
    """Xóa Lệnh sản xuất (điều độ) — chặn nếu đã có Mẻ sản xuất (BatchExecution) dispatch từ
    lệnh này, mirror quy ước chặn sửa/xóa-khi-đã-thực-hiện dùng ở mọi module lệnh khác
    (brew_order.py/filter_order.py/orders.py::_assert_not_executed)."""
    require_perm(user, "wo.manage")
    wo = _get(db, wo_id)
    require_scope(user, "lines", wo.line)
    if db.execute(select(BatchExecution.batch_id).where(BatchExecution.work_order_id == wo.wo_id)).first():
        raise DomainError(f"Lệnh {wo.wo_code} đã có Mẻ sản xuất — không thể xóa.")
    record_audit(db, entity_type="work_order", entity_id=wo.wo_id, action="delete",
                 actor=user, before={"wo_code": wo.wo_code})
    db.delete(wo)
    db.commit()
