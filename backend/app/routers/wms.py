"""WMS thành phẩm: vị trí, đơn vị tồn kho (vỉ/keg), putaway/ship, phân giải barcode (P3-4)."""

from fastapi import APIRouter, Depends, File, UploadFile
from sqlalchemy.orm import Session

from ..database import get_db
from ..schemas import (ConsignedEntryIn, ConsignedEntryUpdate, DecomposeBatchIn, DeleteByLotIn,
                       FactoryImportEntryIn, FactoryImportEntryUpdate, FreeIssueBatchIn,
                       LoadSlipHeaderUpdate, NearExpiryEntryIn, NearExpiryEntryUpdate, PutawayIn, RelocateBatchIn,
                       ShipmentIn, ShipmentTripIn, ShipmentUpdate, UnitBuildIn, UnitDeleteIn, UnitTransferIn,
                       VehicleIn, VehicleUpdate, WmsLocationIn, WmsLocationUpdate, WmsTransferIn, WmsTransferTripIn,
                       WmsTransferUpdate, WmsWarehouseIn, WmsWarehouseUpdate)
from ..security import User, get_current_user, require_perm
from ..services import load_slip as load_slip_svc
from ..services import wms as svc

router = APIRouter(prefix="/api/wms", tags=["wms"])


@router.get("/summary")
def summary(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return svc.summary(db)


@router.get("/warehouses")
def warehouses(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return svc.list_warehouses(db)


@router.post("/warehouses", status_code=201)
def create_warehouse(payload: WmsWarehouseIn, db: Session = Depends(get_db),
                     user: User = Depends(get_current_user)):
    require_perm(user, "warehouse.receive")
    wh = svc.create_warehouse(db, payload.model_dump())
    return {"warehouse_id": wh.warehouse_id, "code": wh.code}


@router.put("/warehouses/{warehouse_id}")
def update_warehouse(warehouse_id: str, payload: WmsWarehouseUpdate, db: Session = Depends(get_db),
                     user: User = Depends(get_current_user)):
    require_perm(user, "warehouse.receive")
    wh = svc.update_warehouse(db, warehouse_id, payload.model_dump(exclude_unset=True))
    return {"warehouse_id": wh.warehouse_id, "code": wh.code}


@router.delete("/warehouses/{warehouse_id}", status_code=204)
def delete_warehouse(warehouse_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    require_perm(user, "warehouse.receive")
    svc.delete_warehouse(db, warehouse_id)


@router.get("/locations")
def locations(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return svc.list_locations(db)


@router.post("/locations", status_code=201)
def create_location(payload: WmsLocationIn, db: Session = Depends(get_db),
                    user: User = Depends(get_current_user)):
    require_perm(user, "warehouse.receive")
    loc = svc.create_location(db, payload.model_dump())
    return {"loc_id": loc.loc_id, "code": loc.code}


@router.put("/locations/{loc_id}")
def update_location(loc_id: str, payload: WmsLocationUpdate, db: Session = Depends(get_db),
                    user: User = Depends(get_current_user)):
    require_perm(user, "warehouse.receive")
    loc = svc.update_location(db, loc_id, payload.model_dump(exclude_unset=True))
    return {"loc_id": loc.loc_id, "code": loc.code}


@router.delete("/locations/{loc_id}", status_code=204)
def delete_location(loc_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    require_perm(user, "warehouse.receive")
    svc.delete_location(db, loc_id)


@router.get("/vehicles")
def vehicle_list(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return svc.list_vehicles(db)


@router.get("/vehicles/consigned-eligible")
def vehicle_list_consigned_eligible(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return svc.consigned_eligible_vehicles(db)


@router.post("/vehicles", status_code=201)
def vehicle_create(payload: VehicleIn, db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)):
    require_perm(user, "warehouse.receive")
    v = svc.create_vehicle(db, payload.model_dump())
    return {"vehicle_id": v.vehicle_id, "vehicle_code": v.vehicle_code, "plate": v.plate}


@router.put("/vehicles/{vehicle_id}")
def vehicle_update(vehicle_id: str, payload: VehicleUpdate, db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)):
    require_perm(user, "warehouse.receive")
    v = svc.update_vehicle(db, vehicle_id, payload.model_dump(exclude_unset=True))
    return {"vehicle_id": v.vehicle_id, "vehicle_code": v.vehicle_code, "plate": v.plate}


@router.delete("/vehicles/{vehicle_id}", status_code=204)
def vehicle_delete(vehicle_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    require_perm(user, "warehouse.receive")
    svc.delete_vehicle(db, vehicle_id)


@router.get("/units")
def units(status: str = None, unit_type: str = None, product: str = None, lot_code: str = None,
          limit: int = 1000, offset: int = 0,
          db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return svc.list_units(db, status, unit_type, product, lot_code, limit, offset)


@router.get("/units/by-location")
def units_by_location(loc_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return svc.list_lot_summaries_by_location(db, loc_id)


@router.post("/units/delete-by-lot")
def delete_units_by_lot(payload: DeleteByLotIn, db: Session = Depends(get_db),
                        user: User = Depends(get_current_user)):
    return svc.delete_units_by_criteria(db, payload.product_name, payload.lot_code, payload.unit_type, user)


@router.post("/units/confirm-receipt-by-lot")
def confirm_receipt_by_lot(payload: DeleteByLotIn, db: Session = Depends(get_db),
                           user: User = Depends(get_current_user)):
    return svc.confirm_receipt_by_lot(db, payload.product_name, payload.lot_code, payload.unit_type, user)


@router.post("/units", status_code=201)
def build_units(payload: UnitBuildIn, db: Session = Depends(get_db),
                user: User = Depends(get_current_user)):
    created = svc.build_units(db, payload.model_dump(), user)
    # count = số vỉ/keg/... thật (total/pack_size cho loại "chia theo pack_size" — xem Danh mục
    # Loại đơn vị tồn kho; loại còn lại luôn 1 đơn vị = 1 quantity) — dùng pack_size TỪ PAYLOAD
    # (biết chính xác lúc tạo), KHÔNG dùng len(created) vì _create_units giờ luôn trả về đúng
    # 1 dòng/lô bất kể total lớn cỡ nào (xem docs/WMS-LOT-LEVEL-REDESIGN.md).
    divisor = payload.pack_size if payload.unit_type in svc._divide_by_pack_codes(db) and payload.pack_size else 1
    count = payload.total / divisor
    return {"count": count, "unit_codes": [u.unit_code for u in created]}


@router.post("/units/opening-balance/import", status_code=201)
async def import_units_opening_balance(file: UploadFile = File(...), db: Session = Depends(get_db),
                                       user: User = Depends(get_current_user)):
    content = await file.read()
    return svc.import_opening_balance_units(db, content, user)


@router.post("/units/{unit_id}/putaway")
def putaway(unit_id: str, payload: PutawayIn, db: Session = Depends(get_db),
            user: User = Depends(get_current_user)):
    return svc.putaway(db, unit_id, payload.loc_id, user)


@router.delete("/units/{unit_id}", status_code=204)
def delete_unit(unit_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    svc.delete_unit(db, unit_id, user)


@router.post("/units/transfer")
def transfer_units(payload: UnitTransferIn, db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)):
    return svc.transfer_units(db, payload.unit_ids, payload.to_loc_id, user)


@router.post("/units/delete-batch")
def delete_units(payload: UnitDeleteIn, db: Session = Depends(get_db),
                 user: User = Depends(get_current_user)):
    return svc.delete_units(db, payload.unit_ids, user)


@router.post("/units/{unit_id}/decompose", status_code=201)
def decompose_unit(unit_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return svc.decompose_unit(db, unit_id, user)


@router.post("/units/decompose-batch", status_code=201)
def decompose_batch(payload: DecomposeBatchIn, db: Session = Depends(get_db),
                    user: User = Depends(get_current_user)):
    return svc.decompose_batch(db, payload.product_name, payload.lot_code, payload.unit_type, payload.count, user)


@router.post("/units/decompose-batch/{audit_id}/undo")
def undo_decompose_batch(audit_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return svc.undo_decompose_batch(db, audit_id, user)


@router.post("/units/relocate-batch")
def relocate_batch(payload: RelocateBatchIn, db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)):
    return svc.relocate_batch(db, payload.product_name, payload.lot_code, payload.unit_type,
                              payload.from_loc_id, payload.to_loc_id, payload.count, user)


# ---- Xuất tự do (không qua Shipment) — chỉ admin, xem services/wms.py::free_issue_batch ----
@router.post("/units/free-issue", status_code=201)
def free_issue_batch(payload: FreeIssueBatchIn, db: Session = Depends(get_db),
                     user: User = Depends(get_current_user)):
    return svc.free_issue_batch(db, payload.product_name, payload.lot_code, payload.unit_type,
                               payload.count, payload.reason, user)


@router.post("/units/free-issue/{audit_id}/undo")
def undo_free_issue_batch(audit_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return svc.undo_free_issue_batch(db, audit_id, user)


@router.get("/units/free-issue-history")
def free_issue_history(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return svc.list_free_issues(db)


@router.get("/units/by-lot")
def units_by_lot(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return svc.list_lot_summaries(db)


@router.get("/shipments")
def shipments(limit: int = 200, offset: int = 0, db: Session = Depends(get_db),
             user: User = Depends(get_current_user)):
    return svc.list_shipments(db, limit, offset)


@router.post("/shipments", status_code=201)
def create_shipment(payload: ShipmentIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    header = payload.model_dump(include={"note", "recipient_name", "recipient_dept", "driver_name",
                                          "vehicle_plate", "vehicle_id", "from_location", "delivery_place"})
    lines = [l.model_dump() for l in payload.lines]
    return svc.create_shipment(db, payload.ship_to_id, lines, user, header=header,
                               warehouse_id=payload.warehouse_id)


@router.put("/shipments/{shipment_id}")
def update_shipment(shipment_id: str, payload: ShipmentUpdate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return svc.update_shipment(db, shipment_id, payload.model_dump(exclude_unset=True), user)


@router.post("/shipments/{shipment_id}/undo")
def undo_shipment(shipment_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return svc.undo_shipment(db, shipment_id, user)


@router.post("/shipments/{shipment_id}/confirm")
def confirm_shipment(shipment_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return svc.confirm_shipment(db, shipment_id, user)


@router.post("/shipments/{shipment_id}/trip")
def update_shipment_trip(shipment_id: str, payload: ShipmentTripIn, db: Session = Depends(get_db),
                         user: User = Depends(get_current_user)):
    return svc.update_shipment_trip(db, shipment_id, payload.km, payload.fuel_liters, user)


# ---- Điều chuyển nội bộ — mirror /shipments nhưng đích là 1 WmsLocation, không giảm tồn kho ----
@router.get("/transfers")
def transfers(limit: int = 200, offset: int = 0, db: Session = Depends(get_db),
             user: User = Depends(get_current_user)):
    return svc.list_transfers(db, limit, offset)


@router.post("/transfers", status_code=201)
def create_transfer(payload: WmsTransferIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    header = payload.model_dump(include={"note", "driver_name", "vehicle_plate", "vehicle_id"})
    lines = [l.model_dump() for l in payload.lines]
    return svc.create_transfer(db, payload.to_location_id, lines, user, header=header)


@router.put("/transfers/{transfer_id}")
def update_transfer(transfer_id: str, payload: WmsTransferUpdate, db: Session = Depends(get_db),
                    user: User = Depends(get_current_user)):
    return svc.update_transfer(db, transfer_id, payload.model_dump(exclude_unset=True), user)


@router.post("/transfers/{transfer_id}/undo")
def undo_transfer(transfer_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return svc.undo_transfer(db, transfer_id, user)


@router.post("/transfers/{transfer_id}/confirm")
def confirm_transfer(transfer_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return svc.confirm_transfer(db, transfer_id, user)


@router.post("/transfers/{transfer_id}/trip")
def update_transfer_trip(transfer_id: str, payload: WmsTransferTripIn, db: Session = Depends(get_db),
                         user: User = Depends(get_current_user)):
    return svc.update_transfer_trip(db, transfer_id, payload.km, payload.fuel_liters, user)


# ---- Nhập bia cận date ----
@router.post("/near-expiry", status_code=201)
def create_near_expiry(payload: NearExpiryEntryIn, db: Session = Depends(get_db),
                       user: User = Depends(get_current_user)):
    return svc.create_near_expiry_entry(db, payload.finished_product_id, payload.quantity,
                                        payload.location_id, user, payload.note)


@router.get("/near-expiry")
def list_near_expiry(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return svc.list_near_expiry_entries(db)


@router.put("/near-expiry/{entry_id}")
def update_near_expiry(entry_id: str, payload: NearExpiryEntryUpdate, db: Session = Depends(get_db),
                       user: User = Depends(get_current_user)):
    return svc.update_near_expiry_entry(db, entry_id, payload.model_dump(exclude_unset=True), user)


@router.post("/near-expiry/{entry_id}/approve")
def approve_near_expiry(entry_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return svc.approve_near_expiry_entry(db, entry_id, user)


@router.post("/near-expiry/{entry_id}/undo")
def undo_near_expiry(entry_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return svc.undo_near_expiry_entry(db, entry_id, user)


# ---- Nhập bia gửi ----
@router.post("/consigned", status_code=201)
def create_consigned(payload: ConsignedEntryIn, db: Session = Depends(get_db),
                     user: User = Depends(get_current_user)):
    return svc.create_consigned_entry(db, payload.finished_product_id, payload.quantity,
                                      payload.location_id, payload.vehicle_id, user, payload.note)


@router.get("/consigned")
def list_consigned(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return svc.list_consigned_entries(db)


@router.put("/consigned/{entry_id}")
def update_consigned(entry_id: str, payload: ConsignedEntryUpdate, db: Session = Depends(get_db),
                     user: User = Depends(get_current_user)):
    return svc.update_consigned_entry(db, entry_id, payload.model_dump(exclude_unset=True), user)


@router.post("/consigned/{entry_id}/approve")
def approve_consigned(entry_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return svc.approve_consigned_entry(db, entry_id, user)


@router.post("/consigned/{entry_id}/undo")
def undo_consigned(entry_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return svc.undo_consigned_entry(db, entry_id, user)


# ---- Nhập từ nhà máy khác ----
@router.post("/factory-import", status_code=201)
def create_factory_import(payload: FactoryImportEntryIn, db: Session = Depends(get_db),
                          user: User = Depends(get_current_user)):
    return svc.create_factory_import_entry(db, payload.finished_product_id, payload.quantity,
                                           payload.location_id, payload.factory_id, user, payload.note,
                                           payload.received_at)


@router.get("/factory-import")
def list_factory_import(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return svc.list_factory_import_entries(db)


@router.put("/factory-import/{entry_id}")
def update_factory_import(entry_id: str, payload: FactoryImportEntryUpdate, db: Session = Depends(get_db),
                          user: User = Depends(get_current_user)):
    return svc.update_factory_import_entry(db, entry_id, payload.model_dump(exclude_unset=True), user)


@router.post("/factory-import/{entry_id}/approve")
def approve_factory_import(entry_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return svc.approve_factory_import_entry(db, entry_id, user)


@router.post("/factory-import/{entry_id}/undo")
def undo_factory_import(entry_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return svc.undo_factory_import_entry(db, entry_id, user)


@router.post("/load-slips/import", status_code=201)
async def import_casing_order(file: UploadFile = File(...), db: Session = Depends(get_db),
                              user: User = Depends(get_current_user)):
    """Nhập file Excel "Lệnh đóng hàng" (2 sheet HL/ĐM) — tách thành các Biên bản bàn giao
    hàng hóa theo từng xe (SỐ XE), sẵn sàng để xem/sửa và in ký."""
    require_perm(user, "warehouse.issue")
    content = await file.read()
    return load_slip_svc.import_casing_order(db, file.filename, content, user)


@router.get("/load-slips")
def list_load_slips(sheet_type: str | None = None, db: Session = Depends(get_db),
                    user: User = Depends(get_current_user)):
    return load_slip_svc.list_load_slips(db, sheet_type)


@router.get("/load-slips/{load_slip_id}")
def get_load_slip(load_slip_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return load_slip_svc.get_load_slip(db, load_slip_id)


@router.put("/load-slips/{load_slip_id}")
def update_load_slip(load_slip_id: str, payload: LoadSlipHeaderUpdate, db: Session = Depends(get_db),
                     user: User = Depends(get_current_user)):
    require_perm(user, "warehouse.issue")
    return load_slip_svc.update_load_slip_header(db, load_slip_id, payload.model_dump(exclude_unset=True))


@router.delete("/load-slips/{load_slip_id}", status_code=204)
def delete_load_slip(load_slip_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    require_perm(user, "warehouse.issue")
    load_slip_svc.delete_load_slip(db, load_slip_id)


@router.get("/resolve")
def resolve(code: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return svc.resolve(db, code)
