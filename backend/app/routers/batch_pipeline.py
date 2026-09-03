"""Pipeline mới cho "Mẻ sản xuất": tank lên men (BatchTank) / lô lọc (BatchFilterLot) / lô
thành phẩm (BatchPackLot). Xem services/batch_pipeline.py."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..database import get_db
from ..schemas import (
    BatchFilterLotBatchOut,
    BatchFilterLotDrawIn,
    BatchFilterLotEditIn,
    BatchFilterLotMaterialUsageIn,
    BatchFilterLotMaterialUsageOut,
    BatchFilterLotOut,
    BatchFilterLotSourceOut,
    BatchFilterOrderCreateIn,
    BatchFilterOrderOut,
    BatchFilterOrderSourceOut,
    BatchPackLotCreateIn,
    BatchPackLotMaterialUsageIn,
    BatchPackLotMaterialUsageOut,
    BatchPackLotOut,
    BatchPackLotPackDateIn,
    BatchPackLotQtyIn,
    BatchPackLotShiftsIn,
    BatchPackLotSplitIn,
    BatchTankDailyReadingsIn,
    BatchTankEditIn,
    BatchTankMergeIn,
    BatchTankOut,
    BatchTankProcessLogIn,
    EbrLockIn,
    EbrSignIn,
    FilterLotFromOrderIn,
    FinishFilterLotBatchIn,
)
from ..security import User, get_current_user
from ..services import batch_pipeline as svc
from ..services import batch_tank_log as tank_log_svc
from ..services import ebr as ebr_svc

router = APIRouter(prefix="/api", tags=["batch-pipeline"], dependencies=[Depends(get_current_user)])


# ==================== BatchTank ====================
@router.get("/batch-tanks", response_model=list[BatchTankOut])
def list_tanks(db: Session = Depends(get_db)):
    return svc.list_tanks_out(db)


@router.get("/batch-tanks/available-lines")
def get_available_tank_lines(db: Session = Depends(get_db)):
    """Danh mục "Tank lên men" (ProductionLine kind=tank) kèm cờ đang chiếm dụng — dùng cho
    picker "Tank vật lý" khi gộp mẻ vào tank mới. Khai báo TRƯỚC /{tank_id} để không bị route
    động bắt nhầm."""
    return svc.available_tank_lines(db)


@router.get("/batch-tanks/{tank_id}", response_model=BatchTankOut)
def get_tank(tank_id: str, db: Session = Depends(get_db)):
    return svc.get_tank_out(db, tank_id)


@router.get("/batch-tanks/{tank_id}/batches")
def get_tank_batches(tank_id: str, db: Session = Depends(get_db)):
    return {"batch_ids": svc.tank_batch_ids(db, tank_id)}


@router.post("/batch-tanks", response_model=BatchTankOut, status_code=201)
def merge_batches(payload: BatchTankMergeIn, db: Session = Depends(get_db),
                  user: User = Depends(get_current_user)):
    return svc.merge_batches_into_tank(db, payload.batch_ids, payload.model_dump(), user)


@router.put("/batch-tanks/{tank_id}", response_model=BatchTankOut)
def update_tank(tank_id: str, payload: BatchTankEditIn, db: Session = Depends(get_db),
                user: User = Depends(get_current_user)):
    return svc.update_tank(db, tank_id, payload.model_dump(exclude_unset=True), user)


@router.delete("/batch-tanks/{tank_id}", status_code=204)
def delete_tank(tank_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    svc.delete_tank(db, tank_id, user)


@router.post("/batch-tanks/{tank_id}/empty", response_model=BatchTankOut)
def empty_tank(tank_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return svc.empty_tank(db, tank_id, user)


@router.get("/batch-tanks/{tank_id}/ebr")
def get_tank_ebr(tank_id: str, db: Session = Depends(get_db)):
    """Hồ sơ EBR của 1 Tank lên men — snapshot có thể tới từ tự ký/khóa riêng (lock_tank, NGAY
    sau khi xong công đoạn) hoặc cascade khi 1 lô thành phẩm dùng chung tank này bị khóa ở Chiết.
    Xem services/ebr.py::assemble_tank."""
    return ebr_svc.assemble_tank(db, tank_id)


@router.post("/batch-tanks/{tank_id}/ebr/sign")
def sign_tank_ebr(tank_id: str, payload: EbrSignIn, db: Session = Depends(get_db),
                  user: User = Depends(get_current_user)):
    return ebr_svc.sign_tank(db, tank_id, user, payload.password, payload.meaning, payload.reason)


@router.post("/batch-tanks/{tank_id}/ebr/lock")
def lock_tank_ebr(tank_id: str, payload: EbrLockIn, db: Session = Depends(get_db),
                  user: User = Depends(get_current_user)):
    return ebr_svc.lock_tank(db, tank_id, user, payload.password, payload.reason)


def _tank_reading_dict(r) -> dict:
    return {"day_no": r.day_no, "reading_date": r.reading_date,
            "nhiet_do_c": r.nhiet_do_c, "do_s": r.do_s, "mat_do_tb": r.mat_do_tb,
            "measured_by": r.measured_by, "measured_at": r.measured_at,
            "kcs": r.kcs, "kcs_by": r.kcs_by, "kcs_at": r.kcs_at,
            "truc_ca": r.truc_ca, "truc_ca_by": r.truc_ca_by, "truc_ca_at": r.truc_ca_at}


@router.get("/batch-tanks/{tank_id}/process-log")
def get_tank_process_log(tank_id: str, db: Session = Depends(get_db)):
    tank = svc.get_tank(db, tank_id)
    log = tank_log_svc.get_or_create_process_log(db, tank_id)
    readings = tank_log_svc.get_daily_readings(db, tank_id)
    return {
        "auto": tank_log_svc.auto_header_values(db, tank),
        "manual": tank_log_svc.get_manual_values(log),
        "ha_phu_events": tank_log_svc.get_ha_phu_events(log),
        "note": log.note, "updated_by": log.updated_by, "updated_at": log.updated_at,
        "readings": [_tank_reading_dict(r) for r in readings],
    }


@router.put("/batch-tanks/{tank_id}/process-log")
def update_tank_process_log(tank_id: str, payload: BatchTankProcessLogIn, db: Session = Depends(get_db),
                            user: User = Depends(get_current_user)):
    svc.get_tank(db, tank_id)
    log = tank_log_svc.update_process_log(db, tank_id, payload.model_dump(exclude_unset=True), user)
    return {"note": log.note, **tank_log_svc.get_manual_values(log),
            "ha_phu_events": tank_log_svc.get_ha_phu_events(log)}


@router.put("/batch-tanks/{tank_id}/process-log/readings")
def update_tank_daily_readings(tank_id: str, payload: BatchTankDailyReadingsIn, db: Session = Depends(get_db),
                               user: User = Depends(get_current_user)):
    svc.get_tank(db, tank_id)
    rows = [r.model_dump() for r in payload.readings]
    readings = tank_log_svc.upsert_daily_readings(db, tank_id, rows, user)
    return [_tank_reading_dict(r) for r in readings]


# ==================== BatchFilterOrder (lệnh lọc) ====================
@router.get("/batch-filter-orders", response_model=list[BatchFilterOrderOut])
def list_filter_orders(db: Session = Depends(get_db)):
    return svc.list_filter_orders(db)


@router.get("/batch-filter-orders/{order_id}", response_model=BatchFilterOrderOut)
def get_filter_order(order_id: str, db: Session = Depends(get_db)):
    return svc.get_filter_order(db, order_id)


@router.get("/batch-filter-orders/{order_id}/sources", response_model=list[BatchFilterOrderSourceOut])
def get_filter_order_sources(order_id: str, db: Session = Depends(get_db)):
    return svc.list_filter_order_sources_out(db, order_id)


@router.post("/batch-filter-orders", response_model=BatchFilterOrderOut, status_code=201)
def create_filter_order(payload: BatchFilterOrderCreateIn, db: Session = Depends(get_db),
                        user: User = Depends(get_current_user)):
    return svc.create_filter_order(db, [s.model_dump() for s in payload.sources], payload.model_dump(), user)


@router.delete("/batch-filter-orders/{order_id}", status_code=204)
def delete_filter_order(order_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    svc.delete_filter_order(db, order_id, user)


@router.post("/batch-filter-orders/{order_id}/filter-lots", response_model=BatchFilterLotOut, status_code=201)
def draw_filter_lot_from_order(order_id: str, payload: FilterLotFromOrderIn, db: Session = Depends(get_db),
                               user: User = Depends(get_current_user)):
    return svc.draw_from_filter_order(db, order_id, payload.model_dump(), user)


# ==================== BatchFilterLot ====================
@router.get("/batch-filter-lots", response_model=list[BatchFilterLotOut])
def list_filter_lots(db: Session = Depends(get_db)):
    return svc.list_filter_lots(db)


@router.get("/batch-filter-lots/available-bbt-lines")
def get_available_bbt_lines(db: Session = Depends(get_db)):
    """Danh mục "Tank thành phẩm (BBT)" kèm cờ đang chiếm dụng — dùng cho picker "Tank thành
    phẩm" khi tạo Lô lọc. Khai báo TRƯỚC /{filter_lot_id} để không bị route động bắt nhầm."""
    return svc.available_bbt_lines(db)


@router.get("/batch-filter-lots/{filter_lot_id}", response_model=BatchFilterLotOut)
def get_filter_lot(filter_lot_id: str, db: Session = Depends(get_db)):
    return svc.get_filter_lot(db, filter_lot_id)


@router.get("/batch-filter-lots/{filter_lot_id}/sources", response_model=list[BatchFilterLotSourceOut])
def get_filter_lot_sources(filter_lot_id: str, db: Session = Depends(get_db)):
    return svc.list_filter_lot_sources_out(db, filter_lot_id)


@router.get("/batch-filter-lots/{filter_lot_id}/batches", response_model=list[BatchFilterLotBatchOut])
def get_filter_lot_batches(filter_lot_id: str, db: Session = Depends(get_db)):
    return [svc.batch_with_draws(db, b) for b in svc.list_filter_lot_batches(db, filter_lot_id)]


@router.get("/batch-filter-lots/{filter_lot_id}/ebr")
def get_filter_lot_ebr(filter_lot_id: str, db: Session = Depends(get_db)):
    """Mirror get_tank_ebr cho Lô lọc — xem services/ebr.py::assemble_filter_lot."""
    return ebr_svc.assemble_filter_lot(db, filter_lot_id)


@router.post("/batch-filter-lots/{filter_lot_id}/ebr/sign")
def sign_filter_lot_ebr(filter_lot_id: str, payload: EbrSignIn, db: Session = Depends(get_db),
                        user: User = Depends(get_current_user)):
    return ebr_svc.sign_filter_lot(db, filter_lot_id, user, payload.password, payload.meaning, payload.reason)


@router.post("/batch-filter-lots/{filter_lot_id}/ebr/lock")
def lock_filter_lot_ebr(filter_lot_id: str, payload: EbrLockIn, db: Session = Depends(get_db),
                        user: User = Depends(get_current_user)):
    return ebr_svc.lock_filter_lot(db, filter_lot_id, user, payload.password, payload.reason)


@router.post("/batch-filter-lots", response_model=BatchFilterLotOut, status_code=201)
def draw_filter_lot(payload: BatchFilterLotDrawIn, db: Session = Depends(get_db),
                    user: User = Depends(get_current_user)):
    return svc.draw_from_tank_into_filter_lot(
        db, [s.model_dump() for s in payload.sources], payload.model_dump(), user)


@router.post("/batch-filter-lots/{filter_lot_id}/batches", response_model=BatchFilterLotBatchOut, status_code=201)
def add_filter_lot_batch(filter_lot_id: str, db: Session = Depends(get_db),
                         user: User = Depends(get_current_user)):
    b = svc.add_filter_lot_batch(db, filter_lot_id, user)
    return svc.batch_with_draws(db, b)


@router.put("/batch-filter-lots/batches/{batch_link_id}/finish", response_model=BatchFilterLotOut)
def finish_filter_lot_batch(batch_link_id: str, payload: FinishFilterLotBatchIn,
                            db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return svc.finish_filter_lot_batch(db, batch_link_id, [d.model_dump() for d in payload.draws],
                                       payload.nuoc_bai_khi_hl, payload.batch_seq_no, user,
                                       started_at=payload.started_at, ended_at=payload.ended_at)


@router.post("/batch-filter-lots/batches/{batch_link_id}/toggle-final", response_model=BatchFilterLotBatchOut)
def toggle_final_batch(batch_link_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    b = svc.toggle_final_batch(db, batch_link_id, user)
    return svc.batch_with_draws(db, b)


@router.delete("/batch-filter-lots/batches/{batch_link_id}", response_model=BatchFilterLotOut)
def delete_filter_lot_batch(batch_link_id: str, db: Session = Depends(get_db),
                            user: User = Depends(get_current_user)):
    return svc.delete_filter_lot_batch(db, batch_link_id, user)


@router.put("/batch-filter-lots/{filter_lot_id}", response_model=BatchFilterLotOut)
def update_filter_lot(filter_lot_id: str, payload: BatchFilterLotEditIn, db: Session = Depends(get_db),
                      user: User = Depends(get_current_user)):
    return svc.update_filter_lot(db, filter_lot_id, payload.model_dump(exclude_unset=True), user)


@router.delete("/batch-filter-lots/{filter_lot_id}", status_code=204)
def delete_filter_lot(filter_lot_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    svc.delete_filter_lot(db, filter_lot_id, user)


@router.post("/batch-filter-lots/{filter_lot_id}/approve")
def approve_filter_lot(filter_lot_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return svc.approve_filter_lot(db, filter_lot_id, user)


@router.post("/batch-filter-lots/{filter_lot_id}/empty", response_model=BatchFilterLotOut)
def empty_filter_lot(filter_lot_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return svc.empty_filter_lot(db, filter_lot_id, user)


@router.post("/batch-filter-lots/{filter_lot_id}/finish-filtering", response_model=BatchFilterLotOut)
def finish_filtering(filter_lot_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return svc.finish_filtering(db, filter_lot_id, user)


# ==================== BatchPackLot ====================
@router.get("/batch-pack-lots", response_model=list[BatchPackLotOut])
def list_pack_lots(filter_lot_id: str = None, db: Session = Depends(get_db)):
    return svc.list_pack_lots(db, filter_lot_id)


@router.get("/batch-pack-lots/eligible-bbt-lines")
def get_eligible_bbt_lines_for_pack(db: Session = Depends(get_db)):
    """Tank BBT đủ điều kiện "đi chiết" (đã lọc xong hết + KCS duyệt hết + còn dịch) — dùng cho
    picker "Chiết từ tank BBT" khi tạo Lô thành phẩm. Khai báo TRƯỚC /{pack_lot_id} để không bị
    route động bắt nhầm."""
    return svc.eligible_bbt_lines_for_pack(db)


@router.get("/batch-pack-lots/{pack_lot_id}", response_model=BatchPackLotOut)
def get_pack_lot(pack_lot_id: str, db: Session = Depends(get_db)):
    return svc.get_pack_lot(db, pack_lot_id)


@router.get("/batch-pack-lots/{pack_lot_id}/materials", response_model=list[BatchPackLotMaterialUsageOut])
def get_pack_lot_materials(pack_lot_id: str, db: Session = Depends(get_db)):
    return svc.list_pack_lot_materials(db, pack_lot_id)


@router.post("/batch-pack-lots", response_model=BatchPackLotOut, status_code=201)
def create_pack_lot(payload: BatchPackLotCreateIn, db: Session = Depends(get_db),
                    user: User = Depends(get_current_user)):
    return svc.create_pack_lot_from_bbt(db, payload.model_dump(), user)


@router.post("/batch-pack-lots/{pack_lot_id}/materials", response_model=BatchPackLotMaterialUsageOut, status_code=201)
def add_pack_lot_material(pack_lot_id: str, payload: BatchPackLotMaterialUsageIn, db: Session = Depends(get_db),
                          user: User = Depends(get_current_user)):
    return svc.add_pack_lot_material(db, pack_lot_id, payload.model_dump(), user)


@router.delete("/batch-pack-lots/materials/{usage_id}", status_code=204)
def delete_pack_lot_material(usage_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    svc.delete_pack_lot_material(db, usage_id, user)


@router.get("/batch-filter-lots/{filter_lot_id}/materials", response_model=list[BatchFilterLotMaterialUsageOut])
def get_filter_lot_materials(filter_lot_id: str, db: Session = Depends(get_db)):
    return svc.list_filter_lot_materials(db, filter_lot_id)


@router.post("/batch-filter-lots/{filter_lot_id}/materials", response_model=BatchFilterLotMaterialUsageOut, status_code=201)
def add_filter_lot_material(filter_lot_id: str, payload: BatchFilterLotMaterialUsageIn, db: Session = Depends(get_db),
                            user: User = Depends(get_current_user)):
    return svc.add_filter_lot_material(db, filter_lot_id, payload.model_dump(), user)


@router.delete("/batch-filter-lots/materials/{usage_id}", status_code=204)
def delete_filter_lot_material(usage_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    svc.delete_filter_lot_material(db, usage_id, user)


@router.post("/batch-filter-lots/{filter_lot_id}/pack-lots", response_model=BatchPackLotOut, status_code=201)
def split_pack_lot(filter_lot_id: str, payload: BatchPackLotSplitIn, db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)):
    return svc.split_filter_lot_to_pack_lot(db, filter_lot_id, payload.model_dump(), user)


@router.put("/batch-pack-lots/{pack_lot_id}/qty", response_model=BatchPackLotOut)
def update_pack_lot_qty(pack_lot_id: str, payload: BatchPackLotQtyIn, db: Session = Depends(get_db),
                        user: User = Depends(get_current_user)):
    return svc.update_pack_lot_qty(db, pack_lot_id, payload.qty, user)


@router.put("/batch-pack-lots/{pack_lot_id}/shifts", response_model=BatchPackLotOut)
def update_pack_lot_shifts(pack_lot_id: str, payload: BatchPackLotShiftsIn, db: Session = Depends(get_db),
                           user: User = Depends(get_current_user)):
    return svc.update_pack_lot_shifts(db, pack_lot_id, payload.model_dump(exclude_unset=True), user)


@router.put("/batch-pack-lots/{pack_lot_id}/pack-date", response_model=BatchPackLotOut)
def update_pack_lot_pack_date(pack_lot_id: str, payload: BatchPackLotPackDateIn, db: Session = Depends(get_db),
                              user: User = Depends(get_current_user)):
    return svc.update_pack_lot_pack_date(db, pack_lot_id, payload.pack_date, user)


@router.delete("/batch-pack-lots/{pack_lot_id}", status_code=204)
def delete_pack_lot(pack_lot_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    svc.delete_pack_lot(db, pack_lot_id, user)


@router.post("/batch-pack-lots/{pack_lot_id}/approve")
def approve_pack_lot(pack_lot_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return svc.approve_pack_lot(db, pack_lot_id, user)


@router.post("/batch-pack-lots/{pack_lot_id}/release-to-wms")
def release_pack_lot_to_wms(pack_lot_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return svc.release_pack_lot_to_wms(db, pack_lot_id, user)


# ==================== EBR neo ở lô thành phẩm ====================
@router.get("/batch-pack-lots/{pack_lot_id}/ebr")
def get_pack_lot_ebr(pack_lot_id: str, db: Session = Depends(get_db)):
    """Hồ sơ mẻ điện tử (EBR) neo ở lô thành phẩm — gộp cả cây genealogy ngược (lô TP -> lô
    lọc -> tank -> mẻ nấu). Xem services/ebr.py::assemble_pack_lot."""
    return ebr_svc.assemble_pack_lot(db, pack_lot_id)


@router.post("/batch-pack-lots/{pack_lot_id}/ebr/sign")
def sign_pack_lot_ebr(pack_lot_id: str, payload: EbrSignIn, db: Session = Depends(get_db),
                      user: User = Depends(get_current_user)):
    return ebr_svc.sign_pack_lot(db, pack_lot_id, user, payload.password, payload.meaning, payload.reason)


@router.post("/batch-pack-lots/{pack_lot_id}/ebr/lock")
def lock_pack_lot_ebr(pack_lot_id: str, payload: EbrLockIn, db: Session = Depends(get_db),
                      user: User = Depends(get_current_user)):
    return ebr_svc.lock_pack_lot(db, pack_lot_id, user, payload.password, payload.reason)


@router.get("/batch-pack-lots/{pack_lot_id}/ebr/diff")
def diff_pack_lot_ebr(pack_lot_id: str, db: Session = Depends(get_db)):
    """Khác biệt giữa hồ sơ đã khóa và dữ liệu hiện tại — dùng khi "Toàn vẹn" báo hash lệch để
    biết chính xác đã chỉnh gì/ai/lúc nào. Xem services\\ebr.py::diff_pack_lot_snapshot."""
    return ebr_svc.diff_pack_lot_snapshot(db, pack_lot_id)
