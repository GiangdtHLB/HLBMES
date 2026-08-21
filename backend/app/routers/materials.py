"""Material/product lots."""

from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..audit import record_audit
from ..common import GenealogyRelation, Role, new_id
from ..database import get_db
from ..errors import NotFoundError
from ..models.materials import GenealogyEdge, MaterialLot
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
    lots = db.execute(stmt).scalars().all()
    _attach_split_from(db, lots)
    return lots


def _attach_split_from(db: Session, lots: list[MaterialLot]) -> None:
    """Gắn `split_from_lot_code` (thuộc tính tạm, KHÔNG lưu DB) lên từng lô — tra 1 lần theo
    GenealogyEdge relation=SPLIT (ghi lúc tách lô, xem services/warehouse.py::_transfer_lot) để
    hiển thị "Tách từ lô X" ngay trên danh sách, không bắt người dùng vào Truy xuất mới thấy."""
    lot_ids = [l.lot_id for l in lots]
    parent_id_by_lot = {}
    if lot_ids:
        edges = db.execute(select(GenealogyEdge.to_id, GenealogyEdge.from_id).where(
            GenealogyEdge.to_id.in_(lot_ids), GenealogyEdge.to_type == "lot",
            GenealogyEdge.from_type == "lot", GenealogyEdge.relation == GenealogyRelation.SPLIT.value)).all()
        parent_id_by_lot = dict(edges)
    parent_ids = list(set(parent_id_by_lot.values()))
    parent_code_by_id = {}
    if parent_ids:
        rows = db.execute(select(MaterialLot.lot_id, MaterialLot.lot_code)
                          .where(MaterialLot.lot_id.in_(parent_ids))).all()
        parent_code_by_id = dict(rows)
    for l in lots:
        parent_id = parent_id_by_lot.get(l.lot_id)
        l.split_from_lot_code = parent_code_by_id.get(parent_id) if parent_id else None


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
    before = {"kcs_lot_no": lot.kcs_lot_no, "supplier_lot": lot.supplier_lot}
    lot.kcs_lot_no = payload.kcs_lot_no
    lot.supplier_lot = payload.supplier_lot
    record_audit(db, entity_type="lot", entity_id=lot.lot_id, action="update",
                 actor=user, before=before,
                 after={"kcs_lot_no": lot.kcs_lot_no, "supplier_lot": lot.supplier_lot})
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
