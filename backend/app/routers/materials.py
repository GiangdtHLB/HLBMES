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
from ..security import User, get_current_user, require_perm, require_role
from ..services import qc_catalog
from ..services import warehouse as warehouse_svc

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
    _attach_sibling_locations(db, lots)
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
        parent_code = parent_code_by_id.get(parent_id) if parent_id else None
        # Từ khi tách lô KHÔNG còn sinh mã mới (dùng LẠI lot_code gốc, xem
        # services/warehouse.py::_transfer_lot) — lô cha/con cùng mã thì KHÔNG gắn tag "tách từ
        # X" (vô nghĩa, tự nói về chính nó); tag chỉ còn hiện cho dữ liệu tách kiểu CŨ (mã khác).
        l.split_from_lot_code = parent_code if parent_code and parent_code != l.lot_code else None


def _attach_sibling_locations(db: Session, lots: list[MaterialLot]) -> None:
    """Gắn `sibling_locations` (thuộc tính tạm, KHÔNG lưu DB) — "lô này còn ở kho khác: bao
    nhiêu" (yêu cầu người dùng 2026-09-14). 1 lot_code giờ có thể có nhiều dòng MaterialLot, mỗi
    dòng ở 1 kho (xem models/materials.py); tra 1 lần theo (lot_year, lot_code) cho cả danh sách,
    loại trừ chính dòng đang xem."""
    keys = {(l.lot_year, l.lot_code) for l in lots}
    if not keys:
        return
    # IN theo lot_code đơn cột (an toàn mọi dialect — MSSQL không hỗ trợ IN theo tuple nhiều cột)
    # rồi lọc đúng cặp (lot_year, lot_code) ở Python; lot_code trùng khác năm hiếm và vô hại (chỉ
    # bị loại ở bước lọc dưới, không gắn nhầm sibling).
    codes = {l.lot_code for l in lots}
    rows = db.execute(select(MaterialLot.lot_id, MaterialLot.lot_year, MaterialLot.lot_code,
                             MaterialLot.location, MaterialLot.quantity)
                      .where(MaterialLot.lot_code.in_(codes))).all()
    by_key: dict[tuple, list] = {}
    for lot_id, lot_year, lot_code, location, quantity in rows:
        if (lot_year, lot_code) not in keys:
            continue
        by_key.setdefault((lot_year, lot_code), []).append(
            {"lot_id": lot_id, "location": location, "quantity": quantity})
    for l in lots:
        siblings = [s for s in by_key.get((l.lot_year, l.lot_code), []) if s["lot_id"] != l.lot_id]
        l.sibling_locations = ([{"location": s["location"], "quantity": s["quantity"]} for s in siblings]
                               if siblings else None)


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
    """Tạo lô vật tư trực tiếp — KHÔNG đi qua toàn bộ quy trình nhận hàng của
    warehouse.receive() (không kiểm tra ngày nhập/tồn đầu/hạn mức...), dùng để nạp nhanh 1 lô
    có sẵn (VD dựng dữ liệu test/khởi tạo). Trước đây endpoint này KHÔNG kiểm tra quyền gì cả
    (bất kỳ ai đăng nhập cũng tạo được lô số lượng tùy ý, trạng thái AVAILABLE ngay, không ghi
    StockMovement — phá vỡ bất biến "tồn = tổng phiếu nhập/xuất" mà các báo cáo point-in-time
    dựa vào) — audit rủi ro 2026-09-15: yêu cầu quyền warehouse.receive như nhập kho thường +
    ghi kèm StockMovement("receipt")."""
    require_perm(user, "warehouse.receive")
    data = payload.model_dump()
    data["lot_year"] = data["lot_year"] or datetime.utcnow().year
    lot = MaterialLot(lot_id=new_id(), **data)
    db.add(lot)
    db.flush()
    if lot.quantity:
        warehouse_svc._move(db, "receipt", lot, lot.quantity, user, location_to=lot.location,
                            reason="Tạo lô trực tiếp (POST /api/lots)")
    record_audit(db, entity_type="lot", entity_id=lot.lot_id, action="create",
                 actor=user, after={"lot_code": lot.lot_code, "quantity": lot.quantity})
    db.commit()
    db.refresh(lot)
    return lot
