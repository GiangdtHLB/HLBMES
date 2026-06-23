"""Batch execution: tạo, chuyển trạng thái, ghi actual, consume/produce."""

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..common import new_id, utcnow
from ..database import get_db
from ..errors import NotFoundError
from ..models.batches import BatchExecution
from ..models.metrics import ProcessReading
from ..models.recipes import RecipeVersion
from ..services import bom as bom_svc
from ..schemas import (
    ActualIn,
    BatchIn,
    BatchOut,
    ConsumeIn,
    EbrLockIn,
    EbrSignIn,
    LotOut,
    ProduceIn,
    ReadingIn,
    ReadingOut,
    TransitionIn,
)
from ..security import User, get_current_user, require_perm
from ..services import batches as svc
from ..services import ebr as ebr_svc

router = APIRouter(prefix="/api/batches", tags=["batches"])


@router.get("", response_model=list[BatchOut])
def list_batches(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    from ..models.workorder import WorkOrder
    from ..security import filter_by_scope
    rows = db.execute(
        select(BatchExecution).order_by(BatchExecution.created_at.desc())
    ).scalars().all()
    # Lọc theo phạm vi line (§10.2): line suy ra từ work order của mẻ.
    line_map = {w.wo_id: w.line for w in db.execute(select(WorkOrder)).scalars().all()}
    return filter_by_scope(user, rows, "lines", lambda b: line_map.get(b.work_order_id))


@router.get("/availability")
def check_availability(recipe_version_id: str, planned_qty: float, db: Session = Depends(get_db),
                      user: User = Depends(get_current_user)):
    """Xem trước nhu cầu BOM (đã scale) so với tồn khả dụng — trước khi tạo mẻ (§7.1).

    Khai báo TRƯỚC /{batch_id} để không bị route động bắt nhầm."""
    rv = db.get(RecipeVersion, recipe_version_id)
    if not rv:
        raise NotFoundError("Recipe version không tồn tại.")
    snap = {"base_qty": rv.base_qty, "base_uom": rv.base_uom, "materials": rv.materials}
    return bom_svc.availability(db, snap, planned_qty)


@router.get("/availability-alt")
def check_availability_alt(recipe_version_id: str, planned_qty: float, db: Session = Depends(get_db),
                           user: User = Depends(get_current_user)):
    """Như /availability nhưng kèm gợi ý nguyên liệu thay thế khi NVL chính thiếu (§7.2)."""
    rv = db.get(RecipeVersion, recipe_version_id)
    if not rv:
        raise NotFoundError("Recipe version không tồn tại.")
    snap = {"base_qty": rv.base_qty, "base_uom": rv.base_uom, "materials": rv.materials}
    return bom_svc.availability_with_alternates(db, snap, planned_qty)


@router.get("/{batch_id}", response_model=BatchOut)
def get_batch(batch_id: str, db: Session = Depends(get_db),
              user: User = Depends(get_current_user)):
    b = db.get(BatchExecution, batch_id)
    if not b:
        raise NotFoundError("Batch không tồn tại.")
    _assert_batch_scope(db, b, user)
    return b


@router.post("", response_model=BatchOut, status_code=201)
def create_batch(payload: BatchIn, db: Session = Depends(get_db),
                 user: User = Depends(get_current_user)):
    require_perm(user, "batch.create")
    return svc.create_batch(db, payload.order_id, payload.recipe_version_id, user,
                            payload.batch_code, payload.planned_qty, payload.allow_shortage)


@router.post("/{batch_id}/transition", response_model=BatchOut)
def transition(batch_id: str, payload: TransitionIn, db: Session = Depends(get_db),
               user: User = Depends(get_current_user)):
    require_perm(user, "batch.execute")
    return svc.transition(db, batch_id, payload.target, user, payload.reason)


@router.post("/{batch_id}/actuals", response_model=BatchOut)
def record_actual(batch_id: str, payload: ActualIn, db: Session = Depends(get_db),
                  user: User = Depends(get_current_user)):
    require_perm(user, "batch.execute")
    return svc.record_actual(db, batch_id, payload.model_dump(), user)


@router.post("/{batch_id}/consume")
def consume(batch_id: str, payload: ConsumeIn, db: Session = Depends(get_db),
            user: User = Depends(get_current_user)):
    require_perm(user, "batch.execute")
    return svc.consume_lot(db, batch_id, payload.lot_id, payload.quantity, user, payload.allow_over)


@router.post("/{batch_id}/produce", response_model=LotOut, status_code=201)
def produce(batch_id: str, payload: ProduceIn, db: Session = Depends(get_db),
            user: User = Depends(get_current_user)):
    require_perm(user, "batch.execute")
    return svc.produce_lot(db, batch_id, payload.lot_code, payload.quantity,
                           payload.lot_type, user)


@router.get("/{batch_id}/bom")
def bom_compare(batch_id: str, db: Session = Depends(get_db),
                user: User = Depends(get_current_user)):
    """Đối chiếu định mức (BOM, scale theo quy mô mẻ) với thực tế tiêu thụ (genealogy)."""
    b = db.get(BatchExecution, batch_id)
    if not b:
        raise NotFoundError("Batch không tồn tại.")
    _assert_batch_scope(db, b, user)
    return bom_svc.compare_batch(db, b)


@router.get("/{batch_id}/yield")
def get_yield(batch_id: str, db: Session = Depends(get_db),
              user: User = Depends(get_current_user)):
    """Hiệu suất theo công đoạn + cumulative yield/loss của mẻ (§7.2)."""
    from ..services import yield_calc
    return yield_calc.yield_report(db, batch_id)


@router.post("/{batch_id}/yield")
def record_yield(batch_id: str, payload: dict, db: Session = Depends(get_db),
                 user: User = Depends(get_current_user)):
    """Ghi hiệu suất 1 công đoạn (input/output) cho mẻ."""
    from ..services import yield_calc
    require_perm(user, "batch.execute")
    return yield_calc.record_yield(db, batch_id, payload, user)


@router.get("/{batch_id}/ebr")
def get_ebr(batch_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Hồ sơ mẻ điện tử (EBR) — dossier step-by-step + chữ ký + hash."""
    b = db.get(BatchExecution, batch_id)
    if not b:
        raise NotFoundError("Batch không tồn tại.")
    return ebr_svc.assemble(db, b)


@router.post("/{batch_id}/ebr/sign")
def sign_ebr(batch_id: str, payload: EbrSignIn, db: Session = Depends(get_db),
             user: User = Depends(get_current_user)):
    b = db.get(BatchExecution, batch_id)
    if not b:
        raise NotFoundError("Batch không tồn tại.")
    return ebr_svc.sign(db, b, user, payload.password, payload.meaning, payload.reason)


@router.post("/{batch_id}/ebr/lock")
def lock_ebr(batch_id: str, payload: EbrLockIn, db: Session = Depends(get_db),
             user: User = Depends(get_current_user)):
    b = db.get(BatchExecution, batch_id)
    if not b:
        raise NotFoundError("Batch không tồn tại.")
    return ebr_svc.lock(db, b, user, payload.password, payload.reason)


@router.get("/{batch_id}/readings", response_model=list[ReadingOut])
def list_readings(batch_id: str, parameter: str = None, db: Session = Depends(get_db),
                  user: User = Depends(get_current_user)):
    """Telemetry curated cho đường cong lên men (nhiệt độ/°P/pH...)."""
    stmt = select(ProcessReading).where(ProcessReading.batch_id == batch_id)
    if parameter:
        stmt = stmt.where(ProcessReading.parameter == parameter)
    return db.execute(stmt.order_by(ProcessReading.ts)).scalars().all()


@router.post("/{batch_id}/readings", response_model=ReadingOut, status_code=201)
def add_reading(batch_id: str, payload: ReadingIn, db: Session = Depends(get_db),
                user: User = Depends(get_current_user)):
    require_perm(user, "batch.execute")
    b = db.get(BatchExecution, batch_id)
    if not b:
        raise NotFoundError("Batch không tồn tại.")
    _assert_batch_scope(db, b, user)
    r = ProcessReading(reading_id=new_id(), batch_id=batch_id, parameter=payload.parameter,
                       value=payload.value, unit=payload.unit, ts=payload.ts or utcnow())
    db.add(r)
    db.commit()
    db.refresh(r)
    return r


def _assert_batch_scope(db, batch, user) -> None:
    """Chặn truy cập 1 mẻ ngoài phạm vi line (§10.2): line suy ra từ work order."""
    from ..models.workorder import WorkOrder
    from ..security import require_scope
    line = None
    if batch.work_order_id:
        wo = db.get(WorkOrder, batch.work_order_id)
        line = wo.line if wo else None
    require_scope(user, "lines", line)
