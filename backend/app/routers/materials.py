"""Material/product lots."""

from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..audit import record_audit
from ..common import Role, new_id
from ..database import get_db
from ..errors import NotFoundError
from ..models.materials import MaterialLot
from ..schemas import LotIn, LotKcsUpdateIn, LotOut
from ..security import User, get_current_user, require_role
from ..services import qc_catalog

router = APIRouter(prefix="/api/lots", tags=["lots"],
                   dependencies=[Depends(get_current_user)])


@router.get("", response_model=list[LotOut])
def list_lots(limit: int = 1000, offset: int = 0, db: Session = Depends(get_db)):
    """Có phân trang (limit/offset, mặc định 1000, tối đa 5000) — số lô tích lũy tăng dần theo
    mỗi lần nhập/tách/nhập tồn đầu nên endpoint không lọc vẫn cần chặn không tải hết bảng."""
    limit = max(1, min(limit or 1000, 5000))
    offset = max(0, offset or 0)
    stmt = select(MaterialLot).order_by(MaterialLot.created_at.desc()).limit(limit).offset(offset)
    return db.execute(stmt).scalars().all()


@router.get("/{lot_id}/qc-status")
def lot_qc_status(lot_id: str, db: Session = Depends(get_db)):
    lot = db.get(MaterialLot, lot_id)
    if not lot:
        raise NotFoundError("Lô không tồn tại.")
    return qc_catalog.lot_qc_status(db, lot)


@router.put("/{lot_id}", response_model=LotOut)
def update_lot_kcs(lot_id: str, payload: LotKcsUpdateIn, db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)):
    """KCS tự điền Số lô KCS khi khai báo chỉ tiêu chất lượng (khác lot_code do phần mềm tự sinh)."""
    require_role(user, Role.QA, Role.OPERATOR)
    lot = db.get(MaterialLot, lot_id)
    if not lot:
        raise NotFoundError("Lô không tồn tại.")
    before = lot.kcs_lot_no
    lot.kcs_lot_no = payload.kcs_lot_no
    record_audit(db, entity_type="lot", entity_id=lot.lot_id, action="update",
                 actor=user, before={"kcs_lot_no": before}, after={"kcs_lot_no": lot.kcs_lot_no})
    db.commit()
    db.refresh(lot)
    return lot


@router.post("", response_model=LotOut, status_code=201)
def create_lot(payload: LotIn, db: Session = Depends(get_db),
               user: User = Depends(get_current_user)):
    data = payload.model_dump()
    data["lot_year"] = data["lot_year"] or datetime.utcnow().year
    lot = MaterialLot(lot_id=new_id(), **data)
    db.add(lot)
    record_audit(db, entity_type="lot", entity_id=lot.lot_id, action="create",
                 actor=user, after={"lot_code": lot.lot_code, "quantity": lot.quantity})
    db.commit()
    db.refresh(lot)
    return lot
