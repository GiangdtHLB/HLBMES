"""WMS thành phẩm: vị trí, đơn vị tồn kho (vỉ/keg), putaway/ship, phân giải barcode (P3-4)."""

from fastapi import APIRouter, Depends, File, UploadFile
from sqlalchemy.orm import Session

from ..database import get_db
from ..schemas import (DecomposeBatchIn, DeleteByLotIn, FreeIssueBatchIn, LoadSlipHeaderUpdate, NearExpiryEntryIn,
                       NearExpiryLookupIn, PutawayIn, RelocateBatchIn, ShipmentIn, ShipToIn, ShipToUpdate,
                       UnitBuildIn, UnitDeleteIn, UnitTransferIn, VehicleIn, VehicleUpdate, WmsLocationIn,
                       WmsLocationUpdate)
from ..security import User, get_current_user, require_perm
from ..services import load_slip as load_slip_svc
from ..services import wms as svc

router = APIRouter(prefix="/api/wms", tags=["wms"])


@router.get("/summary")
def summary(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return svc.summary(db)


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


@router.get("/ship-to")
def ship_to_list(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return svc.list_ship_to(db)


@router.post("/ship-to", status_code=201)
def ship_to_create(payload: ShipToIn, db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)):
    require_perm(user, "warehouse.receive")
    st = svc.create_ship_to(db, payload.model_dump())
    return {"ship_to_id": st.ship_to_id, "code": st.code}


@router.put("/ship-to/{ship_to_id}")
def ship_to_update(ship_to_id: str, payload: ShipToUpdate, db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)):
    require_perm(user, "warehouse.receive")
    st = svc.update_ship_to(db, ship_to_id, payload.model_dump(exclude_unset=True))
    return {"ship_to_id": st.ship_to_id, "code": st.code}


@router.delete("/ship-to/{ship_to_id}", status_code=204)
def ship_to_delete(ship_to_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    require_perm(user, "warehouse.receive")
    svc.delete_ship_to(db, ship_to_id)


@router.get("/vehicles")
def vehicle_list(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return svc.list_vehicles(db)


@router.post("/vehicles", status_code=201)
def vehicle_create(payload: VehicleIn, db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)):
    require_perm(user, "warehouse.receive")
    v = svc.create_vehicle(db, payload.model_dump())
    return {"vehicle_id": v.vehicle_id, "plate": v.plate}


@router.put("/vehicles/{vehicle_id}")
def vehicle_update(vehicle_id: str, payload: VehicleUpdate, db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)):
    require_perm(user, "warehouse.receive")
    v = svc.update_vehicle(db, vehicle_id, payload.model_dump(exclude_unset=True))
    return {"vehicle_id": v.vehicle_id, "plate": v.plate}


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


@router.post("/units", status_code=201)
def build_units(payload: UnitBuildIn, db: Session = Depends(get_db),
                user: User = Depends(get_current_user)):
    created = svc.build_units(db, payload.model_dump(), user)
    # count = số vỉ/keg thật (total/pack_size cho "vi"; keg/lon luôn 1 đơn vị = 1 quantity) —
    # dùng pack_size TỪ PAYLOAD (biết chính xác lúc tạo), KHÔNG dùng len(created) vì
    # _create_units giờ luôn trả về đúng 1 dòng/lô bất kể total lớn cỡ nào (xem
    # docs/WMS-LOT-LEVEL-REDESIGN.md).
    divisor = payload.pack_size if payload.unit_type == "vi" and payload.pack_size else 1
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
    return svc.decompose_batch(db, payload.product_name, payload.lot_code, payload.count, user)


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
def shipments(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return svc.list_shipments(db)


@router.post("/shipments", status_code=201)
def create_shipment(payload: ShipmentIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    header = payload.model_dump(include={"note", "recipient_name", "recipient_dept", "driver_name",
                                          "vehicle_plate", "from_location", "delivery_place", "shipment_type"})
    lines = [l.model_dump() for l in payload.lines]
    return svc.create_shipment(db, payload.ship_to_id, lines, user, header=header)


@router.post("/shipments/{shipment_id}/undo")
def undo_shipment(shipment_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return svc.undo_shipment(db, shipment_id, user)


# ---- Nhập bia cận date ----
@router.post("/near-expiry/lookup")
def lookup_near_expiry_bottle(payload: NearExpiryLookupIn, db: Session = Depends(get_db),
                              user: User = Depends(get_current_user)):
    return svc.find_bottle_for_datetime(db, payload.declared_at)


@router.post("/near-expiry", status_code=201)
def create_near_expiry(payload: NearExpiryEntryIn, db: Session = Depends(get_db),
                       user: User = Depends(get_current_user)):
    return svc.create_near_expiry_entry(db, payload.bottle_id, payload.quantity, payload.declared_at,
                                        user, payload.note)


@router.get("/near-expiry")
def list_near_expiry(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return svc.list_near_expiry_entries(db)


@router.post("/near-expiry/{entry_id}/undo")
def undo_near_expiry(entry_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return svc.undo_near_expiry_entry(db, entry_id, user)


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
