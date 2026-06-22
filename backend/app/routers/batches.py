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
def list_batches(db: Session = Depends(get_db)):
    return db.execute(
        select(BatchExecution).order_by(BatchExecution.created_at.desc())
    ).scalars().all()


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


@router.get("/{batch_id}", response_model=BatchOut)
def get_batch(batch_id: str, db: Session = Depends(get_db)):
    b = db.get(BatchExecution, batch_id)
    if not b:
        raise NotFoundError("Batch không tồn tại.")
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
def bom_compare(batch_id: str, db: Session = Depends(get_db)):
    """Đối chiếu định mức (BOM, scale theo quy mô mẻ) với thực tế tiêu thụ (genealogy)."""
    b = db.get(BatchExecution, batch_id)
    if not b:
        raise NotFoundError("Batch không tồn tại.")
    return bom_svc.compare_batch(db, b)


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
def list_readings(batch_id: str, parameter: str = None, db: Session = Depends(get_db)):
    """Telemetry curated cho đường cong lên men (nhiệt độ/°P/pH...)."""
    stmt = select(ProcessReading).where(ProcessReading.batch_id == batch_id)
    if parameter:
        stmt = stmt.where(ProcessReading.parameter == parameter)
    return db.execute(stmt.order_by(ProcessReading.ts)).scalars().all()


@router.post("/{batch_id}/readings", response_model=ReadingOut, status_code=201)
def add_reading(batch_id: str, payload: ReadingIn, db: Session = Depends(get_db)):
    if not db.get(BatchExecution, batch_id):
        raise NotFoundError("Batch không tồn tại.")
    r = ProcessReading(reading_id=new_id(), batch_id=batch_id, parameter=payload.parameter,
                       value=payload.value, unit=payload.unit, ts=payload.ts or utcnow())
    db.add(r)
    db.commit()
    db.refresh(r)
    return r
