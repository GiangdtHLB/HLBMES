"""Kho NVL nhà máy."""

from datetime import datetime

from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy.orm import Session

from ..common import Role
from ..database import get_db
from ..errors import DomainError
from ..security import User, get_current_user, require_perm, require_role
from ..services import warehouse as svc
from ..schemas import (
    IssueIn,
    LotRelocateIn,
    MaterialLocationIn,
    MaterialLocationOut,
    MaterialRequestIn,
    MaterialRequestOut,
    ReceiptIn,
    ReceiptUpdateIn,
    RequestFulfillAllIn,
    RequestFulfillIn,
    RequestRejectIn,
    ReturnIn,
    ReturnToSupplierIn,
    SangNgangRejectIn,
    SangNgangRequestOut,
    SangNgangUpdateIn,
    SourceMaterialLineOut,
    StockCountCreateIn,
    StockCountLinesIn,
    StockMovementOut,
    TransferIn,
    TransferPxRejectIn,
    TransferPxRequestIn,
    TransferPxRequestOut,
    TransferToFactoryIn,
)

router = APIRouter(prefix="/api/warehouse", tags=["warehouse"],
                   dependencies=[Depends(get_current_user)])


@router.post("/receive")
def receive(payload: ReceiptIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    require_perm(user, "warehouse.receive")
    data = payload.model_dump()
    # Bắt buộc chọn vị trí cất khi nhập vào Kho công ty — nhưng CHỈ SAU KHI danh mục vị trí đã
    # có ít nhất 1 vị trí (tránh chặn nhập kho ngay từ đầu khi admin chưa kịp khai báo danh mục).
    # Không áp dụng Kho phân xưởng — chưa có danh mục vị trí riêng.
    if ("phân xưởng" not in (data.get("location") or "Kho công ty").lower() and not data.get("location_id")
            and svc.any_material_locations_declared(db)):
        raise DomainError("Vui lòng chọn vị trí kho trước khi nhập.")
    return svc.receive(db, data, user)


@router.get("/locations")
def list_material_locations(db: Session = Depends(get_db)):
    return svc.list_material_locations(db)


@router.post("/locations", response_model=MaterialLocationOut, status_code=201)
def create_material_location(payload: MaterialLocationIn, db: Session = Depends(get_db),
                             user: User = Depends(get_current_user)):
    return svc.create_material_location(db, payload.model_dump(), user)


@router.put("/locations/{loc_id}", response_model=MaterialLocationOut)
def update_material_location(loc_id: str, payload: MaterialLocationIn, db: Session = Depends(get_db),
                             user: User = Depends(get_current_user)):
    return svc.update_material_location(db, loc_id, payload.model_dump(), user)


@router.delete("/locations/{loc_id}")
def delete_material_location(loc_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    svc.delete_material_location(db, loc_id, user)
    return {"deleted": True}


@router.post("/lots/{lot_id}/relocate")
def relocate_lot(lot_id: str, payload: LotRelocateIn, db: Session = Depends(get_db),
                 user: User = Depends(get_current_user)):
    return svc.relocate_lot(db, lot_id, payload.location_id, user)


@router.post("/opening-balance/import")
async def import_opening_balance(file: UploadFile = File(...), location: str = Form("Kho công ty"),
                                 db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    content = await file.read()
    return svc.import_opening_balance_materials(db, content, location, user)


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
def report(days: int = 30, location: str = None, date_from: datetime = None,
          date_to: datetime = None, db: Session = Depends(get_db)):
    return svc.inventory_report(db, days, location, date_from, date_to)


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
def list_requests(status: str = None, limit: int = 500, offset: int = 0, db: Session = Depends(get_db),
                  user: User = Depends(get_current_user)):
    return svc.list_requests(db, status, limit, offset)


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


# ---- Điều chuyển kho công ty, chiều 1: Kho phân xưởng → Kho công ty (duyệt trước khi chuyển) ----
@router.post("/transfer-px-requests", response_model=TransferPxRequestOut, status_code=201)
def create_transfer_px_request(payload: TransferPxRequestIn, db: Session = Depends(get_db),
                               user: User = Depends(get_current_user)):
    return svc.create_transfer_px_request(db, payload.lot_id, payload.quantity, user, payload.reason)


@router.get("/transfer-px-requests", response_model=list[TransferPxRequestOut])
def list_transfer_px_requests(status: str = None, limit: int = 500, offset: int = 0,
                              db: Session = Depends(get_db)):
    return svc.list_transfer_px_requests(db, status, limit, offset)


@router.post("/transfer-px-requests/{request_id}/approve", response_model=TransferPxRequestOut)
def approve_transfer_px_request(request_id: str, db: Session = Depends(get_db),
                                user: User = Depends(get_current_user)):
    return svc.approve_transfer_px_request(db, request_id, user)


@router.post("/transfer-px-requests/{request_id}/reject", response_model=TransferPxRequestOut)
def reject_transfer_px_request(request_id: str, payload: TransferPxRejectIn, db: Session = Depends(get_db),
                               user: User = Depends(get_current_user)):
    return svc.reject_transfer_px_request(db, request_id, user, payload.reason)


@router.post("/transfer-px-requests/{request_id}/undo", response_model=TransferPxRequestOut)
def undo_transfer_px_request(request_id: str, db: Session = Depends(get_db),
                             user: User = Depends(get_current_user)):
    return svc.undo_transfer_px_request(db, request_id, user)


# ---- Xuất sang ngang: hàng cập Kho công ty nhưng đích thực sự là Kho phân xưởng ----
@router.post("/sang-ngang", response_model=SangNgangRequestOut, status_code=201)
def create_sang_ngang(payload: ReceiptIn, db: Session = Depends(get_db),
                      user: User = Depends(get_current_user)):
    require_perm(user, "warehouse.receive")
    data = payload.model_dump()
    # Khác /receive thường — hàng "sang ngang" hiểu là về tới đâu chuyển thẳng cho phân xưởng
    # tới đó, không cần cất vào 1 vị trí Kho công ty cụ thể trước, nên KHÔNG bắt buộc chọn vị
    # trí kho ở đây (vẫn cho phép chọn nếu muốn, chỉ không ép buộc).
    return svc.create_sang_ngang(db, data, user)


@router.get("/sang-ngang", response_model=list[SangNgangRequestOut])
def list_sang_ngang(status: str = None, limit: int = 500, offset: int = 0,
                    db: Session = Depends(get_db)):
    return svc.list_sang_ngang_requests(db, status, limit, offset)


@router.post("/sang-ngang/{request_id}/approve", response_model=SangNgangRequestOut)
def approve_sang_ngang(request_id: str, db: Session = Depends(get_db),
                       user: User = Depends(get_current_user)):
    return svc.approve_sang_ngang(db, request_id, user)


@router.post("/sang-ngang/{request_id}/reject", response_model=SangNgangRequestOut)
def reject_sang_ngang(request_id: str, payload: SangNgangRejectIn, db: Session = Depends(get_db),
                      user: User = Depends(get_current_user)):
    return svc.reject_sang_ngang(db, request_id, user, payload.reason)


@router.post("/sang-ngang/{request_id}/undo", response_model=SangNgangRequestOut)
def undo_sang_ngang(request_id: str, db: Session = Depends(get_db),
                    user: User = Depends(get_current_user)):
    return svc.undo_sang_ngang(db, request_id, user)


@router.post("/sang-ngang/{request_id}/resubmit", response_model=SangNgangRequestOut)
def resubmit_sang_ngang(request_id: str, db: Session = Depends(get_db),
                        user: User = Depends(get_current_user)):
    return svc.resubmit_sang_ngang(db, request_id, user)


# Sửa/xóa — CHỈ khi CHƯA được Kho phân xưởng duyệt (status pending/rejected), xem
# services/warehouse.py::update_sang_ngang/delete_sang_ngang. Đăng ký SAU /sang-ngang/{id}/approve
# v.v — cùng lý do thứ tự route như /movements/{movement_id} ở trên.
@router.put("/sang-ngang/{request_id}", response_model=SangNgangRequestOut)
def update_sang_ngang(request_id: str, payload: SangNgangUpdateIn, db: Session = Depends(get_db),
                      user: User = Depends(get_current_user)):
    return svc.update_sang_ngang(db, request_id, payload.model_dump(exclude_unset=True), user)


@router.delete("/sang-ngang/{request_id}")
def delete_sang_ngang(request_id: str, db: Session = Depends(get_db),
                      user: User = Depends(get_current_user)):
    return svc.delete_sang_ngang(db, request_id, user)


# ---- Điều chuyển kho công ty, chiều 2: Kho công ty → Nhà máy khác (xuất ngay, duyệt sau) ----
@router.post("/transfer-to-factory")
def transfer_to_factory(payload: TransferToFactoryIn, db: Session = Depends(get_db),
                        user: User = Depends(get_current_user)):
    return svc.transfer_to_factory(db, payload.lot_id, payload.quantity, payload.factory_id,
                                   user, payload.reason)


@router.post("/movements/{movement_id}/approve-factory")
def approve_transfer_to_factory(movement_id: str, db: Session = Depends(get_db),
                                user: User = Depends(get_current_user)):
    return svc.approve_transfer_to_factory(db, movement_id, user)


# ---- Xuất tự do / Trả nhà cung cấp ----
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
def list_movements(movement_type: str = None, mode: str = None, limit: int = 200, offset: int = 0,
                   db: Session = Depends(get_db)):
    return svc.list_movements(db, movement_type, mode, limit, offset)


# ---- Xóa lịch sử (chỉ admin) — dọn dẹp sổ nhập/xuất tự do/xuất theo đề nghị, dữ liệu vận
# hành thật (lô/tồn kho/NVL đã dùng cho mẻ) không bị đụng tới. Vẫn ghi audit bình thường.
@router.delete("/movements/free-issue-history")
def delete_free_issue_history(workshop: bool = False, db: Session = Depends(get_db),
                              user: User = Depends(get_current_user)):
    return svc.delete_free_issue_history(db, workshop, user)


@router.delete("/movements/receipt-history")
def delete_receipt_history(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return svc.delete_receipt_history(db, user)


# ---- Sửa/xóa 1 lượt nhập kho cụ thể — CHỈ khi lô liên quan chưa bị xuất/chuyển/tiêu thụ (xem
# services/warehouse.py::update_receipt/delete_receipt). Đăng ký SAU các route tĩnh
# /movements/receipt-history, /movements/free-issue-history ở trên — FastAPI khớp route theo
# đúng thứ tự khai báo, nếu đặt {movement_id} trước sẽ "nuốt" mất các route tĩnh đó.
@router.put("/movements/{movement_id}")
def update_receipt(movement_id: str, payload: ReceiptUpdateIn, db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)):
    return svc.update_receipt(db, movement_id, payload.model_dump(exclude_unset=True), user)


@router.delete("/movements/{movement_id}")
def delete_receipt(movement_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return svc.delete_receipt(db, movement_id, user)


@router.delete("/requests-history")
def delete_request_history(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return svc.delete_request_history(db, user)


@router.get("/workshop-usage-history")
def workshop_usage_history(limit: int = 200, db: Session = Depends(get_db)):
    return svc.workshop_usage_history(db, limit)


# ---- Kiểm kê định kỳ (cycle count) ----
@router.post("/counts")
def create_count(payload: StockCountCreateIn, db: Session = Depends(get_db),
                 user: User = Depends(get_current_user)):
    return svc.create_count(db, payload.location, user, payload.note,
                            payload.start_date, payload.end_date)


@router.get("/counts")
def list_counts(status: str = None, limit: int = 1000, offset: int = 0, db: Session = Depends(get_db)):
    return svc.list_counts(db, status, limit, offset)


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
