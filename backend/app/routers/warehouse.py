"""Kho NVL nhà máy."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..common import Role
from ..database import get_db
from ..security import User, get_current_user, require_perm, require_role
from ..services import warehouse as svc
from ..schemas import (
    IssueIn,
    MaterialRequestIn,
    MaterialRequestOut,
    ReceiptIn,
    RequestFulfillAllIn,
    RequestFulfillIn,
    RequestRejectIn,
    ReturnIn,
    ReturnToSupplierIn,
    SourceMaterialLineOut,
    StockCountCreateIn,
    StockCountLinesIn,
    StockMovementOut,
    TransferIn,
    TransferToCompanyIn,
)

router = APIRouter(prefix="/api/warehouse", tags=["warehouse"],
                   dependencies=[Depends(get_current_user)])


@router.post("/receive")
def receive(payload: ReceiptIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    require_perm(user, "warehouse.receive")
    return svc.receive(db, payload.model_dump(), user)


@router.post("/return")
def return_stock(payload: ReturnIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    require_perm(user, "warehouse.issue")
    return svc.return_stock(db, payload.lot_id, payload.quantity, user, payload.reason)


@router.post("/issue")
def issue(payload: IssueIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    # Xuất tự do (không qua phiếu đề nghị) chỉ dành cho admin — đây là endpoint HTTP DUY NHẤT
    # gọi tới svc.issue() từ UI (nội bộ Nấu/Lọc/Chiết gọi thẳng svc.issue() bằng Python, không
    # qua route này nên không bị ảnh hưởng bởi ràng buộc admin-only ở đây).
    require_role(user, Role.ADMIN)
    return svc.issue(db, payload.lot_id, payload.quantity, user, payload.mode, payload.reason, payload.ref_doc)


@router.post("/transfer")
def transfer(payload: TransferIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    require_perm(user, "warehouse.issue")
    return svc.transfer(db, payload.lot_id, payload.quantity, payload.location_to, user, payload.reason)


@router.get("/stock")
def stock(location: str = None, db: Session = Depends(get_db)):
    return svc.stock_on_hand(db, location)


@router.get("/low-stock")
def low_stock(db: Session = Depends(get_db)):
    return svc.low_stock_report(db)


@router.get("/materials/{material_id}/fifo")
def material_fifo(material_id: str, db: Session = Depends(get_db)):
    return svc.material_fifo_detail(db, material_id)


@router.get("/card")
def card(material_id: str = None, lot_id: str = None, db: Session = Depends(get_db)):
    return svc.stock_card(db, material_id, lot_id)


@router.get("/expiry")
def expiry(warn_days: int = 30, db: Session = Depends(get_db)):
    return svc.expiry_report(db, warn_days)


@router.get("/report")
def report(days: int = 30, location: str = None, db: Session = Depends(get_db)):
    return svc.inventory_report(db, days, location)


# ---- Đề nghị nhận kho ----
@router.get("/requests/source-preview", response_model=list[SourceMaterialLineOut])
def preview_source_materials(source_type: str, source_id: str, db: Session = Depends(get_db)):
    """Xem trước nhu cầu NVL của 1 Lệnh nấu/Lệnh lọc lớn — dùng để tự động điền sẵn dòng
    vật tư khi tạo phiếu đề nghị nhận kho từ 1 lệnh sản xuất."""
    return svc.preview_source_materials(db, source_type, source_id)


@router.post("/requests", response_model=MaterialRequestOut, status_code=201)
def create_request(payload: MaterialRequestIn, db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)):
    return svc.create_request(db, payload.model_dump(), user)


@router.get("/requests", response_model=list[MaterialRequestOut])
def list_requests(status: str = None, db: Session = Depends(get_db),
                  user: User = Depends(get_current_user)):
    return svc.list_requests(db, status)


@router.post("/requests/{request_id}/lines/{line_id}/fulfill")
def fulfill_request_line(request_id: str, line_id: str, payload: RequestFulfillIn, db: Session = Depends(get_db),
                         user: User = Depends(get_current_user)):
    return svc.fulfill_request_line(db, request_id, line_id, payload.lot_id, payload.quantity,
                                    user, payload.location_to)


@router.post("/requests/{request_id}/lines/{line_id}/reject")
def reject_request_line(request_id: str, line_id: str, payload: RequestRejectIn, db: Session = Depends(get_db),
                        user: User = Depends(get_current_user)):
    return svc.reject_request_line(db, request_id, line_id, payload.reason, user)


@router.post("/requests/{request_id}/fulfill-all")
def fulfill_all_lines(request_id: str, payload: RequestFulfillAllIn, db: Session = Depends(get_db),
                      user: User = Depends(get_current_user)):
    return svc.fulfill_all_lines(db, request_id, user, payload.location_to)


@router.delete("/requests/{request_id}")
def cancel_request(request_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return svc.cancel_request(db, request_id, user)


@router.post("/requests/{request_id}/lines/{line_id}/undo-fulfill")
def undo_fulfill_line(request_id: str, line_id: str, db: Session = Depends(get_db),
                      user: User = Depends(get_current_user)):
    return svc.undo_fulfill_line(db, request_id, line_id, user)


# ---- Xuất tự do / Điều chuyển / Trả nhà cung cấp ----
@router.post("/transfer-to-company")
def transfer_to_company(payload: TransferToCompanyIn, db: Session = Depends(get_db),
                        user: User = Depends(get_current_user)):
    require_perm(user, "warehouse.issue")
    return svc.transfer_to_company(db, payload.lot_id, payload.quantity, user, payload.reason)


@router.post("/return-to-supplier")
def return_to_supplier(payload: ReturnToSupplierIn, db: Session = Depends(get_db),
                       user: User = Depends(get_current_user)):
    require_perm(user, "warehouse.issue")
    return svc.return_to_supplier(db, payload.lot_id, payload.quantity, user, payload.reason)


@router.post("/movements/{movement_id}/undo-issue")
def undo_issue(movement_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    require_perm(user, "warehouse.issue")
    return svc.undo_issue(db, movement_id, user)


@router.get("/movements", response_model=list[StockMovementOut])
def list_movements(movement_type: str = None, mode: str = None, limit: int = 200,
                   db: Session = Depends(get_db)):
    return svc.list_movements(db, movement_type, mode, limit)


@router.get("/workshop-usage-history")
def workshop_usage_history(limit: int = 200, db: Session = Depends(get_db)):
    return svc.workshop_usage_history(db, limit)


# ---- Kiểm kê định kỳ (cycle count) ----
@router.post("/counts")
def create_count(payload: StockCountCreateIn, db: Session = Depends(get_db),
                 user: User = Depends(get_current_user)):
    return svc.create_count(db, payload.location, user, payload.note)


@router.get("/counts")
def list_counts(status: str = None, db: Session = Depends(get_db)):
    return svc.list_counts(db, status)


@router.get("/counts/{count_id}")
def get_count(count_id: str, db: Session = Depends(get_db)):
    return svc.get_count(db, count_id)


@router.put("/counts/{count_id}/lines")
def update_count_lines(count_id: str, payload: StockCountLinesIn, db: Session = Depends(get_db),
                       user: User = Depends(get_current_user)):
    return svc.update_count_lines(db, count_id, [l.model_dump() for l in payload.lines], user)


@router.post("/counts/{count_id}/post")
def post_count(count_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return svc.post_count(db, count_id, user)


@router.post("/counts/{count_id}/approve")
def approve_count(count_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return svc.approve_count(db, count_id, user)


@router.post("/counts/{count_id}/undo")
def undo_count(count_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return svc.undo_count(db, count_id, user)
