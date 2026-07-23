"""Hồ sơ điện tử theo lô: tổng hợp NVL→Nấu→Lên men→Lọc→Chiết cho 1 lô thành 1 tài liệu
xem trên màn hình — ráp lại từ genealogy.trace_backward (đã có sẵn cây phả hệ đầy đủ,
xử lý fan-out nhiều mẻ nấu/nhiều lô NVL) + qc_catalog.stage_qc_status (chỉ tiêu từng
công đoạn) + braumat_import (dữ liệu Ghi chép nấu đầy đủ), tránh người dùng phải tự mở
từng tab Kho NVL/Nấu/Lên men/Lọc/Chiết rồi ghép thủ công."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..errors import NotFoundError
from ..models.brewing import (
    BottleMaterialUsage, BottleRecord, BrewBatch, BrewMaterialUsage, BrewOrder, BrewRecord, FermentRecord,
    FilterMasterOrder, FilterMaterialUsage, FilterOrder, FilterOrderTank, FilterRecord,
)
from ..models.master import FinishedProduct, Material, Product
from ..models.materials import MaterialLot
from . import braumat_import as braumat_svc
from . import ferment_log as ferment_log_svc
from . import genealogy, qc_catalog

_CHAIN_TYPES = ("lot", "brew_batch", "brew", "ferment", "filter", "bottle")
_PLURAL = {"lot": "lots", "brew_batch": "brew_batches", "brew": "brews",
           "ferment": "ferments", "filter": "filters", "bottle": "bottles"}


def _collect_ids(tree: dict) -> dict:
    """Duyệt cây trace_backward, gom id theo từng loại node thuộc chuỗi Nấu-Lọc-Chiết
    (bỏ qua "batch"/"pallet" — không thuộc phạm vi hồ sơ này)."""
    ids = {t: set() for t in _CHAIN_TYPES}

    def walk(node: dict) -> None:
        if node["type"] in ids:
            ids[node["type"]].add(node["id"])
        for child in node.get("children", []):
            walk(child)

    walk(tree)
    return ids


def _lot_detail(db: Session, lot_id: str) -> dict:
    lot = db.get(MaterialLot, lot_id)
    if not lot:
        return None
    material = db.get(Material, lot.material_id) if lot.material_id else None
    return {
        "lot_id": lot.lot_id, "lot_code": lot.lot_code,
        "material_code": material.code if material else None,
        "material_name": material.name if material else None,
        "quantity": lot.quantity, "uom": lot.uom, "status": lot.status,
        "supplier_lot": lot.supplier_lot, "expiry": lot.expiry,
        "qc": qc_catalog.lot_qc_status(db, lot),
    }


def _brew_batch_detail(db: Session, batch_id: str) -> dict:
    batch = db.get(BrewBatch, batch_id)
    if not batch:
        return None
    brew = db.get(BrewRecord, batch.brew_id)
    brew_order = db.get(BrewOrder, brew.brew_order_id) if brew and brew.brew_order_id else None
    materials = db.execute(
        select(BrewMaterialUsage).where(BrewMaterialUsage.batch_id == batch_id)
        .order_by(BrewMaterialUsage.created_at)
    ).scalars().all()
    log = braumat_svc.get_or_create_process_log(db, batch_id)
    steps = braumat_svc.list_process_steps(db, batch_id)
    spec = braumat_svc.get_spec_values(db, brew.product_id) if brew and brew.product_id \
        else {k: None for k in braumat_svc.SPEC_FIELD_KEYS}
    return {
        "batch_id": batch.batch_id, "batch_code": batch.batch_code, "seq": batch.seq,
        "brew_id": batch.brew_id, "brew_code": brew.brew_code if brew else None,
        "brew_order_code": brew_order.order_code if brew_order else None,
        "started_at": batch.started_at, "ended_at": batch.ended_at,
        "materials": [{"material_name": m.material_name, "lot_pm": m.lot_pm,
                       "lot_date": m.lot_date, "fifo_ok": m.fifo_ok,
                       "quantity": m.quantity, "uom": m.uom} for m in materials],
        "qc": qc_catalog.stage_qc_status(db, "nau", "brew_batch", batch.batch_id,
                                         brew.product_id if brew else None),
        "process_log": {
            "braumat_order_number": log.braumat_order_number, "braumat_recipe": log.braumat_recipe,
            "note": log.note, "updated_by": log.updated_by, "updated_at": log.updated_at,
            "manual": braumat_svc.get_manual_values(log), "spec": spec,
            "steps": steps, "checkpoints": braumat_svc.checkpoint_summary(steps),
        },
    }


def _brew_detail(db: Session, brew_id: str) -> dict:
    brew = db.get(BrewRecord, brew_id)
    if not brew:
        return None
    product = db.get(Product, brew.product_id) if brew.product_id else None
    return {
        "brew_id": brew.brew_id, "brew_code": brew.brew_code, "brew_date": brew.brew_date,
        "wort_type": brew.wort_type, "volume_hl": brew.volume_hl,
        "product_id": brew.product_id, "product_code": product.code if product else None,
    }


def _ferment_detail(db: Session, ferment_id: str) -> dict:
    f = db.get(FermentRecord, ferment_id)
    if not f:
        return None
    qc = {stage: qc_catalog.stage_qc_status(db, stage, "ferment", f"{f.lm_code}__{stage}", f.product_id)
          for stage in ("len_men_chinh", "len_men_phu")}
    readings = ferment_log_svc.get_daily_readings(db, ferment_id)
    return {
        "ferment_id": f.ferment_id, "lm_code": f.lm_code, "tank_lm": f.tank_lm,
        "brew_code": f.brew_code, "volume_hl": f.volume_hl, "on_hand_cct": f.on_hand_cct,
        "status": f.status, "qc_approved": f.qc_approved, "qc_approved_by": f.qc_approved_by,
        "qc_approved_at": f.qc_approved_at, "qc": qc,
        "started_at": f.brew_date, "ended_at": f.kt_date,
        # Biểu đồ theo dõi lên men (nhiệt độ/°S/mật độ tb theo ngày) — cùng nguồn dữ liệu với
        # "Ghi chép" (GET /brewing/ferments/{id}/process-log), chỉ lấy phần vẽ biểu đồ cần.
        "readings": [{"day_no": r.day_no, "nhiet_do_c": r.nhiet_do_c, "do_s": r.do_s,
                     "mat_do_tb": r.mat_do_tb} for r in readings],
    }


def _filter_detail(db: Session, filter_id: str) -> dict:
    f = db.get(FilterRecord, filter_id)
    if not f:
        return None
    # "Lọc lại" — mẻ này có nguồn là 1 tank BBT đã lọc xong trước đó (xem
    # FilterOrderTank.tank_type="bbt"/source_bbt_code/reason, routers/brewing.py::add_filter) —
    # hồ sơ điện tử phải thể hiện rõ để truy xuất nguồn gốc.
    bbt_line = db.execute(select(FilterOrderTank).where(
        FilterOrderTank.filter_id == filter_id, FilterOrderTank.tank_type == "bbt")).scalars().first()
    materials = db.execute(select(FilterMaterialUsage).where(FilterMaterialUsage.filter_id == filter_id)
                           .order_by(FilterMaterialUsage.created_at)).scalars().all()
    filter_order = db.get(FilterOrder, f.filter_order_id) if f.filter_order_id else None
    master_order = db.get(FilterMasterOrder, filter_order.master_order_id) \
        if filter_order and filter_order.master_order_id else None
    return {
        "filter_id": f.filter_id, "filter_code": f.filter_code, "brew_code": f.brew_code,
        "filter_order_code": filter_order.order_code if filter_order else None,
        "filter_master_order_code": master_order.order_code if master_order else None,
        "lot_loc": f.lot_loc, "filter_date": f.filter_date, "from_cct": f.from_cct,
        "v_dich_hl": f.v_dich_hl, "beer_type": f.beer_type, "v_beer_hl": f.v_beer_hl,
        "to_bbt": f.to_bbt, "status": f.status,
        "started_at": f.filter_date, "ended_at": f.ended_at,
        "qc": qc_catalog.stage_qc_status(db, "loc", "filter", f.filter_code, beer_type_id=f.beer_type_id,
                                         finished_product_id=f.finished_product_id),
        "is_refilter": bbt_line is not None,
        "refilter_source_bbt_code": bbt_line.source_bbt_code if bbt_line else None,
        "refilter_reason": bbt_line.reason if bbt_line else None,
        "materials": [{"material_name": m.material_name, "lot_pm": m.lot_pm,
                      "lot_date": m.lot_date, "fifo_ok": m.fifo_ok,
                      "quantity": m.quantity, "uom": m.uom} for m in materials],
    }


def _bottle_detail(db: Session, bottle_id: str) -> dict:
    b = db.get(BottleRecord, bottle_id)
    if not b:
        return None
    fp = db.get(FinishedProduct, b.finished_product_id) if b.finished_product_id else None
    qc = {"thanh_pham": qc_catalog.stage_qc_status(db, "thanh_pham", "bottle", f"{b.bottle_code}__thanh_pham",
                                                   finished_product_id=b.finished_product_id, beer_type_id=b.beer_type_id)}
    materials = db.execute(select(BottleMaterialUsage).where(BottleMaterialUsage.bottle_id == bottle_id)
                           .order_by(BottleMaterialUsage.created_at)).scalars().all()
    return {
        "bottle_id": b.bottle_id, "bottle_code": b.bottle_code, "filter_code": b.filter_code,
        "bottle_date": b.bottle_date, "beer_type": b.beer_type, "lot_no": b.lot_no,
        "finished_product_code": fp.code if fp else None,
        "v_cap_chiet_hl": b.v_cap_chiet_hl, "from_bbt": b.from_bbt, "line": b.line,
        "ca1": b.ca1, "ca2": b.ca2, "ca3": b.ca3,
        "stocked": b.stocked, "approved": b.approved,
        "started_at": b.bottle_date, "ended_at": b.ended_at,
        "qc": qc,
        "materials": [{"material_name": m.material_name, "lot_pm": m.lot_pm,
                      "lot_date": m.lot_date, "fifo_ok": m.fifo_ok,
                      "quantity": m.quantity, "uom": m.uom} for m in materials],
    }


_DETAIL_BUILDERS = {
    "lot": _lot_detail, "brew_batch": _brew_batch_detail, "brew": _brew_detail,
    "ferment": _ferment_detail, "filter": _filter_detail, "bottle": _bottle_detail,
}


def build_lot_record(db: Session, code: str) -> dict:
    """Ráp hồ sơ điện tử đầy đủ cho 1 lô — tra `code` bằng mọi mã đã hỗ trợ ở
    genealogy.find_node (mã nấu/lô LM/mã lọc/mã chiết/số lô bia), truy ngược cả chuỗi
    NVL→Nấu→Lên men→Lọc→Chiết, rồi lấy chi tiết đầy đủ (kèm chỉ tiêu chất lượng + Ghi
    chép nấu) cho từng bản ghi trong chuỗi đó."""
    resolved = genealogy.find_node(db, code)
    if not resolved:
        raise NotFoundError(f"Không tìm thấy lô/mã '{code}'.")
    node_type, node_id = resolved
    tree = genealogy.trace_backward(db, node_type, node_id)
    ids = _collect_ids(tree)

    out = {"root": {"type": node_type, "id": node_id, "code": code}}
    for t in _CHAIN_TYPES:
        out[_PLURAL[t]] = [d for d in (_DETAIL_BUILDERS[t](db, i) for i in ids[t]) if d]
    return out


def build_brew_forward_record(db: Session, brew_id: str) -> dict:
    """Truy xuôi theo nấu: từ 1 lô nấu (mã nấu) đã chọn, lấy XUÔI CHIỀU toàn bộ dữ liệu nội
    bộ nhà máy liên quan — mẻ/NVL của chính lô nấu đó, (các) lô lên men mà nó góp vào, mẻ lọc
    lấy từ (các) tank lên men đó, mẻ chiết lấy từ các mẻ lọc đó. DỪNG Ở CHIẾT — không đi tiếp
    ra pallet/Kho TP/xuất kho (khác genealogy.trace_forward thông thường vốn đi tới tận nơi
    xuất — cái này chỉ để truy vết nội bộ trong nhà máy, xem routers/brewing.py::add_edge
    cho thứ tự cạnh brew->ferment->filter->bottle)."""
    brew = db.get(BrewRecord, brew_id)
    if not brew:
        raise NotFoundError("Không tìm thấy lô nấu.")
    tree = genealogy.trace_forward(db, "brew", brew_id, stop_types={"bottle"})
    ids = {"ferment": set(), "filter": set(), "bottle": set()}

    def walk(node: dict) -> None:
        if node["type"] in ids:
            ids[node["type"]].add(node["id"])
        for child in node.get("children", []):
            walk(child)

    walk(tree)
    batches = db.execute(
        select(BrewBatch).where(BrewBatch.brew_id == brew_id).order_by(BrewBatch.seq)
    ).scalars().all()
    return {
        "root": {"type": "brew", "id": brew_id, "code": brew.brew_code},
        "tree": tree,
        "lots": [],
        "brew_batches": [d for d in (_brew_batch_detail(db, b.batch_id) for b in batches) if d],
        "ferments": [d for d in (_ferment_detail(db, i) for i in ids["ferment"]) if d],
        "filters": [d for d in (_filter_detail(db, i) for i in ids["filter"]) if d],
        "bottles": [d for d in (_bottle_detail(db, i) for i in ids["bottle"]) if d],
    }
