"""Nấu-Lọc-Chiết chi tiết: nguyên liệu, nấu, lên men, lọc, chiết, chỉ tiêu, cảnh báo."""


from fastapi import APIRouter, Depends, File, Query, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from datetime import timedelta

from ..audit import record_audit
from ..common import Role, new_id, resolve_years, utcnow
from ..database import get_db
from ..errors import DomainError, NotFoundError, PermissionError_
from ..models.brewing import (
    BottleMaterialUsage,
    BottleRecord,
    BrewBatch,
    BrewMasterOrder,
    BrewMaterialUsage,
    BrewOrder,
    BrewProcessLog,
    BrewProcessStep,
    BrewRecord,
    FermentBrewLink,
    FermentDailyReading,
    FermentProcessLog,
    FermentRecord,
    FilterMasterOrder,
    FilterMaterialUsage,
    FilterOrder,
    FilterOrderTank,
    FilterRecord,
    MaterialReceipt,
    StageIndicator,
)
from ..models.lines import ProductionLine
from ..models.master import BeerType, FinishedProduct, Material, Product
from ..models.materials import GenealogyEdge, MaterialLot
from ..models.quality import QualityResult
from ..models.wms import FinishedGoodsUnit
from ..schemas import (
    BottleIn,
    BottleMaterialUsageIn,
    BrewBatchIn,
    BrewIn,
    BrewMasterOrderIn,
    BrewMaterialUsageIn,
    BrewOrderIn,
    BrewProcessLogIn,
    FermentDailyReadingsIn,
    FermentIn,
    FermentProcessLogIn,
    FilterIn,
    FilterMaterialUsageIn,
    FilterMasterOrderIn,
    FilterOrderIn,
    FinishBottleIn,
    FinishFilterTankIn,
    FinishIn,
    MaterialReceiptIn,
    QcSampleIn,
    StageIndicatorIn,
    StageQcResultIn,
)
from ..security import User, get_current_user, require_any_perm, require_perm
from ..services import braumat_import as braumat_svc
from ..services import brew_order as brew_order_svc
from ..services import dashboard as dashboard_svc
from ..services import derived
from ..services import ferment_log as ferment_log_svc
from ..services import filter_order as filter_order_svc
from ..services import genealogy
from ..services import lot_lock as lot_lock_svc
from ..services import lot_record as lot_record_svc
from ..services import ops_setting as ops_setting_svc
from ..services import qc_catalog
from ..services import quality
from ..services import warehouse as warehouse_svc
from ..services import wms as wms_svc

# Mọi route yêu cầu đăng nhập (an toàn mặc định); thao tác ghi thêm require_perm bên dưới.
router = APIRouter(prefix="/api/brewing", tags=["brewing"],
                   dependencies=[Depends(get_current_user)])

# Trạng thái lọc/chiết hiển thị
FILTER_STATUS = {"dang_loc": "Đang lọc", "cho_duyet": "Chờ duyệt", "cho_chiet": "Chờ chiết", "chiet_1_phan": "Đang chiết", "da_chiet_het": "Đã chiết hết"}
EXEC_STATUS = {"dang_thuc_hien": "Đang thực hiện", "hoan_thanh": "Hoàn thành"}


def _years_or_current(years) -> list:
    """Áp mặc định năm hiện tại cho 6 màn hình lọc-theo-năm (Thông tin nấu/lên men/lọc/chiết,
    Lệnh nấu, Lệnh lọc) khi người dùng chưa chọn năm nào — resolve_years() tự nó KHÔNG áp mặc
    định (trả None) vì còn được services/dashboard.py::production_summary dùng lại để đếm
    TOÀN BỘ lịch sử, không giới hạn năm."""
    try:
        return resolve_years(years) or [utcnow().year]
    except ValueError as e:
        raise DomainError(str(e))


def _exec_status(ended_at) -> str:
    """Trạng thái thực thi của vận hành (đã bấm Kết thúc chưa) — dùng chung cho mẻ nấu/lọc/
    chiết, tách biệt với trạng thái suy ra từ tồn kho (FILTER_STATUS)."""
    return "hoan_thanh" if ended_at is not None else "dang_thuc_hien"


def _has_indicators(db, stage, code):
    return db.execute(select(StageIndicator).where(
        StageIndicator.stage == stage, StageIndicator.scope_code == code)).first() is not None


def _brew_and_order(db, brew_id):
    b = db.get(BrewRecord, brew_id)
    return b, (db.get(BrewOrder, b.brew_order_id) if b and b.brew_order_id else None)


def _assert_stage_scope_unlocked(db, scope_type: str, scope_id: str) -> None:
    """Resolve scope_type/scope_id (quy ước dùng bởi qc_catalog/StageIndicator, xem
    data-stageqc ở app.js) về đúng bản ghi để kiểm tra khóa trước khi ghi chỉ tiêu/indicator."""
    if scope_type == "brew_batch":
        batch = db.get(BrewBatch, scope_id)
        if batch:
            _assert_unlocked(batch, *_brew_and_order(db, batch.brew_id))
    elif scope_type == "ferment":
        f = db.execute(select(FermentRecord).where(FermentRecord.lm_code == scope_id.split("__")[0])).scalar_one_or_none()
        _assert_unlocked(f)
    elif scope_type == "filter":
        f = db.execute(select(FilterRecord).where(FilterRecord.filter_code == scope_id)).scalar_one_or_none()
        if f:
            _assert_unlocked(f, *_filter_order_chain(db, f.filter_order_id))
    elif scope_type == "bottle":
        b = db.execute(select(BottleRecord).where(BottleRecord.bottle_code == scope_id.split("__")[0])).scalar_one_or_none()
        _assert_unlocked(b)


def _filter_order_chain(db, filter_order_id):
    order = db.get(FilterOrder, filter_order_id) if filter_order_id else None
    master = db.get(FilterMasterOrder, order.master_order_id) if order and order.master_order_id else None
    return order, master


def _brew_order_chain(db, brew_order_id):
    order = db.get(BrewOrder, brew_order_id) if brew_order_id else None
    master = db.get(BrewMasterOrder, order.master_order_id) if order and order.master_order_id else None
    return order, master


def _assert_unlocked(*objs):
    """Chặn sửa/xóa/chuyển trạng thái nếu CHÍNH bản ghi HOẶC bất kỳ lệnh cha nào trong chuỗi
    đã bị "Khóa lô" (xem services/lot_lock.py::lock_lot — KCS khóa tại 1 mẻ chiết, khóa cả
    chuỗi ngược dòng) HOẶC đang bị QA "HOLD" (xem services/quality.py::set_hold — công đoạn
    Nấu/Lên men/Lọc/Chiết, tách biệt với khóa sổ). Truyền vào bản ghi + các cha của nó (VD mẻ,
    mã nấu, Lệnh nấu) — Lệnh nấu/Lệnh lọc không có quality_status riêng nên chỉ getattr rỗng."""
    for obj in objs:
        if obj is None:
            continue
        if getattr(obj, "locked", False):
            raise DomainError("Bản ghi đã bị khóa (lô đã chốt) — không thể sửa/xóa. Chỉ admin mới mở khóa được.")
        if getattr(obj, "quality_status", None) == "on_hold":
            raise DomainError("Bản ghi đang bị QA giữ (HOLD) — không thể sửa/xóa/chuyển bước. Phải RELEASE trước (tab Chất lượng).")


def _stage_ok(db, stage, scope_type, scope_id, product_id=None, beer_type_id=None, finished_product_id=None) -> bool:
    """Đủ chỉ tiêu bắt buộc của 1 stage hay chưa — dùng để tô màu dòng Nấu/Lên men/Lọc/Chiết
    (khớp đúng key stage/scope_type/scope_id mà nút "Chỉ tiêu" ở frontend dùng thật, xem
    app.js data-stageqc — KHÔNG dùng cột has_indicators/StageIndicator, cột đó chỉ được set
    qua /indicators mà frontend không bao giờ gọi tới, nên luôn False)."""
    st = qc_catalog.stage_qc_status(db, stage, scope_type, scope_id, product_id,
                                    finished_product_id=finished_product_id, beer_type_id=beer_type_id)
    return st["can_release"]


# ===== Lệnh nấu (Brew Production Order) =====
@router.get("/orders")
def list_brew_orders(db: Session = Depends(get_db)):
    return brew_order_svc.list_orders(db)


@router.get("/orders/bom-preview")
def preview_brew_order_bom(product_id: str = None, planned_batch_count: int = 1, planned_volume_hl: float = 0.0,
                           db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Xem trước bảng định mức NVL (tự nạp từ Công thức) + tồn kho hiện tại — TRƯỚC khi tạo
    lệnh nấu thật, để biết ngay có đủ NVL hay không (nút "Xem NVL" ở form Tạo Lệnh nấu). Cũng
    dùng làm gợi ý NVL/mẻ trong modal "+ NVL" khi lệnh nấu chưa có định mức riêng từng dòng
    (openBrewMaterialsModal) — người thao tác mẻ (batch.execute) không nhất thiết có quyền
    order.create nên chấp nhận cả 2 quyền, không chỉ order.create."""
    require_any_perm(user, ["order.create", "batch.execute"])
    return brew_order_svc.preview_bom_lines(db, product_id, planned_batch_count, planned_volume_hl)


@router.post("/orders", status_code=201)
def create_brew_order(payload: BrewOrderIn, db: Session = Depends(get_db),
                      user: User = Depends(get_current_user)):
    require_perm(user, "order.create")
    order = brew_order_svc.create_order(db, payload.model_dump(), user)
    return {"brew_order_id": order.brew_order_id, "order_code": order.order_code}


@router.get("/orders/{brew_order_id}")
def get_brew_order(brew_order_id: str, db: Session = Depends(get_db)):
    return brew_order_svc.get_order(db, brew_order_id)


@router.put("/orders/{brew_order_id}")
def update_brew_order(brew_order_id: str, payload: BrewOrderIn, db: Session = Depends(get_db),
                      user: User = Depends(get_current_user)):
    require_perm(user, "order.create")
    _assert_unlocked(*_brew_order_chain(db, brew_order_id))
    order = brew_order_svc.update_order(db, brew_order_id, payload.model_dump(), user)
    return {"brew_order_id": order.brew_order_id, "order_code": order.order_code}


@router.delete("/orders/{brew_order_id}", status_code=204)
def delete_brew_order(brew_order_id: str, db: Session = Depends(get_db),
                      user: User = Depends(get_current_user)):
    require_perm(user, "order.create")
    _assert_unlocked(*_brew_order_chain(db, brew_order_id))
    brew_order_svc.delete_order(db, brew_order_id, user)


# ===== Lệnh nấu LỚN (chứa nhiều "lệnh nấu nhỏ" — mỗi lệnh nhỏ là 1 BrewOrder ở trên) =====
@router.get("/brew-master-orders")
def list_brew_master_orders(years: list[int] = Query(None), db: Session = Depends(get_db)):
    return brew_order_svc.list_master_orders(db, _years_or_current(years))


@router.post("/brew-master-orders", status_code=201)
def create_brew_master_order(payload: BrewMasterOrderIn, db: Session = Depends(get_db),
                             user: User = Depends(get_current_user)):
    require_perm(user, "order.create")
    master = brew_order_svc.create_master_order(db, payload.model_dump(), user)
    return {"brew_master_order_id": master.brew_master_order_id, "order_code": master.order_code}


@router.get("/brew-master-orders/{brew_master_order_id}")
def get_brew_master_order(brew_master_order_id: str, db: Session = Depends(get_db)):
    return brew_order_svc.get_master_order(db, brew_master_order_id)


@router.put("/brew-master-orders/{brew_master_order_id}")
def update_brew_master_order(brew_master_order_id: str, payload: BrewMasterOrderIn,
                             db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    require_perm(user, "order.create")
    _assert_unlocked(db.get(BrewMasterOrder, brew_master_order_id))
    master = brew_order_svc.update_master_order(db, brew_master_order_id, payload.model_dump(), user)
    return {"brew_master_order_id": master.brew_master_order_id, "order_code": master.order_code}


@router.delete("/brew-master-orders/{brew_master_order_id}", status_code=204)
def delete_brew_master_order(brew_master_order_id: str, db: Session = Depends(get_db),
                             user: User = Depends(get_current_user)):
    require_perm(user, "order.create")
    _assert_unlocked(db.get(BrewMasterOrder, brew_master_order_id))
    brew_order_svc.delete_master_order(db, brew_master_order_id, user)


# ===== Lệnh lọc (không phối = 1 tank, phối = nhiều tank) =====
@router.get("/filter-orders")
def list_filter_orders(db: Session = Depends(get_db)):
    return filter_order_svc.list_orders(db)


@router.post("/filter-orders", status_code=201)
def create_filter_order(payload: FilterOrderIn, db: Session = Depends(get_db),
                        user: User = Depends(get_current_user)):
    require_perm(user, "order.create")
    order = filter_order_svc.create_order(db, payload.model_dump(), user)
    return {"filter_order_id": order.filter_order_id, "order_code": order.order_code}


@router.get("/filter-orders/{filter_order_id}")
def get_filter_order(filter_order_id: str, db: Session = Depends(get_db)):
    return filter_order_svc.get_order(db, filter_order_id)


@router.put("/filter-orders/{filter_order_id}")
def update_filter_order(filter_order_id: str, payload: FilterOrderIn, db: Session = Depends(get_db),
                        user: User = Depends(get_current_user)):
    require_perm(user, "order.create")
    existing = db.get(FilterOrder, filter_order_id)
    _assert_unlocked(existing, db.get(FilterMasterOrder, existing.master_order_id) if existing and existing.master_order_id else None)
    order = filter_order_svc.update_order(db, filter_order_id, payload.model_dump(), user)
    return {"filter_order_id": order.filter_order_id, "order_code": order.order_code}


@router.delete("/filter-orders/{filter_order_id}", status_code=204)
def delete_filter_order(filter_order_id: str, db: Session = Depends(get_db),
                        user: User = Depends(get_current_user)):
    require_perm(user, "order.create")
    existing = db.get(FilterOrder, filter_order_id)
    _assert_unlocked(existing, db.get(FilterMasterOrder, existing.master_order_id) if existing and existing.master_order_id else None)
    filter_order_svc.delete_order(db, filter_order_id, user)


@router.get("/next-batch-seq-no")
def get_next_batch_seq_no(exclude_line_id: str = None, db: Session = Depends(get_db)):
    """Gợi ý "Mẻ lọc số" kế tiếp cho modal Kết thúc mẻ (quét toàn bộ lô lọc trong hệ thống,
    KHÔNG giới hạn theo 1 lệnh lọc) + danh sách số đã dùng để frontend hỏi xác nhận khi vận
    hành gõ trùng — xem filter_order_svc.next_batch_seq_no."""
    return filter_order_svc.next_batch_seq_no(db, exclude_line_id)


# ===== Lệnh lọc LỚN (chứa nhiều "lệnh lọc nhỏ" — mỗi lệnh nhỏ là 1 FilterOrder ở trên) =====
@router.get("/filter-master-orders")
def list_filter_master_orders(years: list[int] = Query(None), db: Session = Depends(get_db)):
    return filter_order_svc.list_master_orders(db, _years_or_current(years))


@router.post("/filter-master-orders", status_code=201)
def create_filter_master_order(payload: FilterMasterOrderIn, db: Session = Depends(get_db),
                               user: User = Depends(get_current_user)):
    require_perm(user, "order.create")
    master = filter_order_svc.create_master_order(db, payload.model_dump(), user)
    return {"filter_master_order_id": master.filter_master_order_id, "order_code": master.order_code}


@router.get("/filter-master-orders/{filter_master_order_id}")
def get_filter_master_order(filter_master_order_id: str, db: Session = Depends(get_db)):
    return filter_order_svc.get_master_order(db, filter_master_order_id)


@router.put("/filter-master-orders/{filter_master_order_id}")
def update_filter_master_order(filter_master_order_id: str, payload: FilterMasterOrderIn,
                               db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    require_perm(user, "order.create")
    _assert_unlocked(db.get(FilterMasterOrder, filter_master_order_id))
    master = filter_order_svc.update_master_order(db, filter_master_order_id, payload.model_dump(), user)
    return {"filter_master_order_id": master.filter_master_order_id, "order_code": master.order_code}


@router.delete("/filter-master-orders/{filter_master_order_id}", status_code=204)
def delete_filter_master_order(filter_master_order_id: str, db: Session = Depends(get_db),
                               user: User = Depends(get_current_user)):
    require_perm(user, "order.create")
    _assert_unlocked(db.get(FilterMasterOrder, filter_master_order_id))
    filter_order_svc.delete_master_order(db, filter_master_order_id, user)


# ===== Thông tin nguyên liệu =====
@router.get("/materials")
def list_materials(db: Session = Depends(get_db)):
    rows = db.execute(select(MaterialReceipt).order_by(MaterialReceipt.receipt_date.desc())).scalars().all()
    out = []
    for r in rows:
        # màu: đỏ=chưa số lô, xanh lá=chưa chỉ tiêu, xanh dương=đầy đủ
        if not (r.lot_pm and r.lot_kcs):
            color = "red"
        elif not r.has_indicators:
            color = "green"
        else:
            color = "blue"
        out.append({"receipt_id": r.receipt_id, "mskt": r.mskt, "receipt_date": r.receipt_date,
                    "material_name": r.material_name, "lot_pm": r.lot_pm, "lot_kcs": r.lot_kcs,
                    "quantity": r.quantity, "uom": r.uom, "location": r.location, "note": r.note,
                    "supplier": r.supplier, "color": color})
    return out


@router.post("/materials", status_code=201)
def add_material(payload: MaterialReceiptIn, db: Session = Depends(get_db),
                 user: User = Depends(get_current_user)):
    require_perm(user, "batch.execute")
    data = payload.model_dump()
    data["mskt"] = data.get("mskt") or f"{50000 + int(utcnow().timestamp()) % 9999}"
    r = MaterialReceipt(receipt_id=new_id(), **data)
    db.add(r); db.commit(); db.refresh(r)
    return r


@router.delete("/materials/{receipt_id}", status_code=204)
def delete_material(receipt_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    require_perm(user, "batch.execute")
    r = db.get(MaterialReceipt, receipt_id)
    if not r:
        raise NotFoundError("Bản ghi nguyên liệu không tồn tại.")
    db.delete(r)
    db.commit()


# ===== Thông tin nấu =====
@router.get("/brews")
def list_brews(years: list[int] = Query(None), db: Session = Depends(get_db)):
    years = _years_or_current(years)
    rows = db.execute(select(BrewRecord).where(BrewRecord.brew_year.in_(years))
                      .order_by(BrewRecord.brew_date.desc())).scalars().all()
    links = db.execute(select(FermentBrewLink)).scalars().all()
    ferment_id_by_brew = {link.brew_id: link.ferment_id for link in links}
    ferments = {f.ferment_id: f for f in db.execute(select(FermentRecord)).scalars().all()}
    products = {p.product_id: p for p in db.execute(select(Product)).scalars().all()}
    orders = {o.brew_order_id: o for o in db.execute(select(BrewOrder)).scalars().all()}
    masters = {m.brew_master_order_id: m for m in db.execute(select(BrewMasterOrder)).scalars().all()}
    batch_counts: dict[str, int] = {}
    for row in db.execute(select(BrewBatch.brew_id)).all():
        batch_counts[row[0]] = batch_counts.get(row[0], 0) + 1
    # Sản lượng nấu THỰC TẾ = tổng "Tổng lượng dịch (hl)" (Ghi chép nấu, mục Lắng xoáy + hạ
    # T°) cộng dồn qua mọi mẻ của mã nấu — khác với volume_hl (kế hoạch, nhập lúc tạo mã nấu).
    actual_volume_by_brew = brew_order_svc._real_actual_by_brew(db, [b.brew_id for b in rows])
    # Màu dòng mã nấu = tổng hợp từ TẤT CẢ mẻ (BrewBatch) con — đủ chỉ tiêu "nau" (bắt buộc,
    # tra qua stage_qc_status khớp đúng scope mà nút "Chỉ tiêu" dùng, xem app.js:2759) VÀ có
    # NVL (BrewMaterialUsage) cho MỌI mẻ mới xanh dương; thiếu chỉ tiêu ở 1 mẻ bất kỳ → đỏ;
    # đủ chỉ tiêu nhưng thiếu NVL ở 1 mẻ bất kỳ → xanh lá. Không mẻ nào → đỏ (chưa có gì).
    all_batches = db.execute(select(BrewBatch)).scalars().all()
    batches_by_brew: dict[str, list] = {}
    for batch in all_batches:
        batches_by_brew.setdefault(batch.brew_id, []).append(batch)
    nvl_batch_ids = {row[0] for row in db.execute(select(BrewMaterialUsage.batch_id).distinct()).all()}
    out = []
    for b in rows:
        f = ferments.get(ferment_id_by_brew.get(b.brew_id))
        prod = products.get(b.product_id)
        order = orders.get(b.brew_order_id)
        # Lệnh nấu nhỏ hiển thị theo Số lệnh của Lệnh nấu LỚN cha (order_code của lệnh nhỏ tự
        # sinh SUB-... không có ý nghĩa với người dùng) — nếu lệnh nhỏ đứng độc lập (không
        # thuộc lệnh lớn nào), vẫn hiển thị order_code của chính nó như trước.
        master = masters.get(order.master_order_id) if order and order.master_order_id else None
        order_code_display = master.order_code if master else (order.order_code if order else None)
        batches = batches_by_brew.get(b.brew_id, [])
        if not batches:
            color = "red"
        else:
            all_qc_ok = all(_stage_ok(db, "nau", "brew_batch", batch.batch_id, b.product_id) for batch in batches)
            all_nvl_ok = all(batch.batch_id in nvl_batch_ids for batch in batches)
            color = "red" if not all_qc_ok else ("green" if not all_nvl_ok else "blue")
        out.append({"brew_id": b.brew_id, "brew_code": b.brew_code, "brew_date": b.brew_date,
                    "wort_type": b.wort_type, "product_id": b.product_id, "product_code": prod.code if prod else None,
                    "volume_hl": b.volume_hl, "note": b.note, "batch_count": batch_counts.get(b.brew_id, 0),
                    "actual_volume_hl": round(actual_volume_by_brew[b.brew_id], 3) if b.brew_id in actual_volume_by_brew else None,
                    "lm_code": f.lm_code if f else None, "tank_lm": f.tank_lm if f else None,
                    "kt_date": f.kt_date if f else None,
                    "brew_order_id": b.brew_order_id, "brew_order_code": order_code_display,
                    "color": color,
                    "locked": b.locked or bool(order and order.locked), "locked_by": b.locked_by or (order.locked_by if order else None)})
    return out


@router.post("/brews", status_code=201)
def add_brew(payload: BrewIn, db: Session = Depends(get_db),
             user: User = Depends(get_current_user)):
    """Tạo mẻ nấu (1 mã nấu = 1 lần nấu vào 1 tank) — tự tạo lô lên men (FermentRecord) tương ứng.
    product_id (loại bia) quyết định nhóm chỉ tiêu chất lượng áp dụng. Sau khi tạo, khai báo các
    mẻ cụ thể (BrewBatch, VD số mẻ Braumat 123/124/125/126) qua /brews/{brew_id}/batches — mỗi
    mẻ mới có nguyên liệu & chỉ tiêu riêng."""
    require_perm(user, "batch.execute")
    data = payload.model_dump()
    tank_lm = data.pop("tank_lm", None)
    lm_code = data.pop("lm_code", None)
    yeast_gen = data.pop("yeast_gen", None)
    brew_order_id = data.get("brew_order_id")
    order = db.get(BrewOrder, brew_order_id)
    if not order:
        raise NotFoundError("Lệnh nấu không tồn tại.")
    _assert_unlocked(order)
    record_summaries = brew_order_svc._record_summaries(db, brew_order_id)
    if brew_order_svc._is_complete(db, record_summaries, order.planned_volume_hl, order.volume_tolerance_hl):
        raise DomainError("Lệnh nấu này đã hoàn thành (đủ sản lượng kế hoạch) — không thể thêm mã nấu mới.")
    # Dịch bia trích từ Lệnh nấu (nguồn xác thực duy nhất) — không cho lệch giữa mã nấu và
    # lệnh nấu của nó (nếu không, gợi ý NVL/BOM theo dịch bia ở lệnh nấu sẽ sai với mã nấu thật).
    if order.product_id:
        data["product_id"] = order.product_id
    brew_year = (data.get("brew_date") or utcnow()).year
    data["brew_year"] = brew_year
    if lm_code:
        if not tank_lm:
            raise DomainError("Chọn Tank lên men.")
        if db.execute(select(FermentRecord).where(FermentRecord.lm_code == lm_code,
                      FermentRecord.ferment_year == brew_year)).scalar_one_or_none():
            raise DomainError(f"Mã lô LM '{lm_code}' đã tồn tại trong năm {brew_year}.")
    b = BrewRecord(brew_id=new_id(), **data)
    db.add(b)
    db.flush()

    if lm_code:
        # kt_date (ngày nạp đầy tank) không nhập tay — tự tính bằng _sync_ferment_kt_date khi
        # mẻ cuối cùng trong tank được bấm "Kết thúc" (xem finish_brew_batch).
        ferment = FermentRecord(ferment_id=new_id(), lm_code=lm_code, brew_code=b.brew_code,
                                ferment_year=brew_year,
                                brew_date=b.brew_date, wort_type=b.wort_type,
                                product_id=b.product_id, yeast_gen=yeast_gen, tank_lm=tank_lm,
                                volume_hl=b.volume_hl, on_hand_cct=b.volume_hl, status="len_men")
        db.add(ferment)
        db.flush()
        db.add(FermentBrewLink(link_id=new_id(), ferment_id=ferment.ferment_id, brew_id=b.brew_id))
        genealogy.add_edge(db, from_type="brew", from_id=b.brew_id, to_type="ferment",
                           to_id=ferment.ferment_id, relation="lên men")
        ferment.batch_numbers = b.brew_code

    db.commit(); db.refresh(b)
    return b


def _sync_ferment_kt_date(db: Session, ferment_id: str) -> None:
    """Ngày KT (nạp đầy tank) chỉ có giá trị khi TẤT CẢ mẻ của TẤT CẢ mã nấu nạp vào tank này
    đã được bấm "Kết thúc" — còn thiếu mẻ nào (hoặc chưa có mẻ nào) thì để trống, vì tank
    chưa thật sự "đầy" cho tới lúc đó. Khi đã đủ, giá trị = giờ kết thúc mẻ CUỐI CÙNG (lớn
    nhất). Gọi lại mỗi khi 1 mẻ kết thúc/sửa giờ/bị xóa."""
    ferment = db.get(FermentRecord, ferment_id)
    if not ferment:
        return
    brew_ids = [r[0] for r in db.execute(
        select(FermentBrewLink.brew_id).where(FermentBrewLink.ferment_id == ferment_id)).all()]
    ended_ats = [r[0] for r in db.execute(
        select(BrewBatch.ended_at).where(BrewBatch.brew_id.in_(brew_ids))).all()] if brew_ids else []
    ferment.kt_date = max(ended_ats) if ended_ats and all(e is not None for e in ended_ats) else None


def _filter_order_ids_for_ferments(db: Session, ferment_ids: list[str]) -> list[str]:
    """Các Lệnh lọc có tank nguồn nằm trong `ferment_ids` — tra qua FilterOrderTank thay vì
    FilterRecord.ferment_id trực tiếp, vì lọc PHỐI có nhiều tank/dòng (FilterRecord.ferment_id
    khi đó là None)."""
    if not ferment_ids:
        return []
    return [row[0] for row in db.execute(
        select(FilterOrderTank.filter_order_id).where(FilterOrderTank.ferment_id.in_(ferment_ids))).all()]


def _brew_already_filtered(db: Session, brew_id: str) -> bool:
    """Mã nấu đã có lô lên men liên kết đi vào Lọc chưa — nếu có thì không cho xóa mã
    nấu/mẻ nữa (đã bàn giao cho công đoạn sau, xóa sẽ làm mất dấu vết truy xuất nguồn gốc)."""
    ferment_ids = [row[0] for row in db.execute(
        select(FermentBrewLink.ferment_id).where(FermentBrewLink.brew_id == brew_id)).all()]
    filter_order_ids = _filter_order_ids_for_ferments(db, ferment_ids)
    if not filter_order_ids:
        return False
    return db.execute(select(FilterRecord.filter_id)
                      .where(FilterRecord.filter_order_id.in_(filter_order_ids))).first() is not None


@router.delete("/brews/{brew_id}", status_code=204)
def delete_brew(brew_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    require_perm(user, "batch.execute")
    b = db.get(BrewRecord, brew_id)
    if not b:
        raise NotFoundError("Bản ghi nấu không tồn tại.")
    _assert_unlocked(b, db.get(BrewOrder, b.brew_order_id) if b.brew_order_id else None)
    if _brew_already_filtered(db, brew_id):
        raise DomainError(f"Mã nấu '{b.brew_code}' đã được lọc — không thể xóa (ảnh hưởng truy xuất nguồn gốc).")
    ferment_ids_to_sync = {link.ferment_id for link in db.execute(
        select(FermentBrewLink).where(FermentBrewLink.brew_id == brew_id)).scalars().all()}
    for link in db.execute(select(FermentBrewLink).where(FermentBrewLink.brew_id == brew_id)).scalars().all():
        db.delete(link)
    db.flush()  # MSSQL enforce FK: xóa hết bản con (link) trước bản cha (brew_record).
    for batch in db.execute(select(BrewBatch).where(BrewBatch.brew_id == brew_id)).scalars().all():
        for u in db.execute(select(BrewMaterialUsage).where(BrewMaterialUsage.batch_id == batch.batch_id)).scalars().all():
            if u.movement_id:
                warehouse_svc.undo_issue(db, u.movement_id, user, strict=False)
            db.delete(u)
        for r in db.execute(select(QualityResult).where(QualityResult.scope_type == "brew_batch", QualityResult.scope_id == batch.batch_id)).scalars().all():
            db.delete(r)
        for s in db.execute(select(BrewProcessStep).where(BrewProcessStep.batch_id == batch.batch_id)).scalars().all():
            db.delete(s)
        for lg in db.execute(select(BrewProcessLog).where(BrewProcessLog.batch_id == batch.batch_id)).scalars().all():
            db.delete(lg)
        db.flush()  # xóa usage/quality_result/process_step/process_log (con) trước brew_batch (cha).
        genealogy.delete_edges_for(db, "brew_batch", batch.batch_id)
        db.delete(batch)
    db.flush()  # xóa brew_batch (con) trước brew_record (cha).
    genealogy.delete_edges_for(db, "brew", brew_id)
    db.delete(b)
    db.flush()
    for ferment_id in ferment_ids_to_sync:
        # Lô lên men không còn mã nấu nào tham chiếu (1 lô LM có thể gộp nhiều mã nấu vào
        # cùng tank) — xóa CẢ lô lên men luôn, tránh để lại bản ghi mồ côi chiếm mã lô LM
        # (khiến không tạo lại được mã nấu mới dùng cùng mã lô LM đó) — xem _assert_releasable
        # và bug "Mã lô LM đã tồn tại" đã gặp trước đây.
        still_linked = db.execute(select(FermentBrewLink).where(
            FermentBrewLink.ferment_id == ferment_id)).first() is not None
        if still_linked:
            _sync_ferment_kt_date(db, ferment_id)
            continue
        f = db.get(FermentRecord, ferment_id)
        if not f:
            continue
        for r in db.execute(select(QualityResult).where(QualityResult.scope_type == "ferment",
                            QualityResult.scope_id.in_([f"{f.lm_code}__len_men_chinh", f"{f.lm_code}__len_men_phu"]))).scalars().all():
            db.delete(r)
        for rd in db.execute(select(FermentDailyReading).where(FermentDailyReading.ferment_id == ferment_id)).scalars().all():
            db.delete(rd)
        for lg in db.execute(select(FermentProcessLog).where(FermentProcessLog.ferment_id == ferment_id)).scalars().all():
            db.delete(lg)
        db.flush()  # xóa reading/process_log/quality_result (con) trước ferment_record (cha).
        genealogy.delete_edges_for(db, "ferment", ferment_id)
        db.delete(f)
    db.commit()


@router.post("/brews/{brew_id}/lock-lot")
def lock_brew_lot(brew_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """KCS khóa Nấu (mã nấu + mọi mẻ của nó) khi tất cả mẻ đã hoàn thành và đủ chỉ tiêu bắt
    buộc — công đoạn đầu tiên trong chuỗi khóa lô (xem services/lot_lock.py)."""
    require_perm(user, "quality.release")
    locked = lot_lock_svc.lock_brew(db, brew_id, user)
    return {"brew_id": locked.brew_id, "locked": True}


@router.post("/brews/{brew_id}/unlock-lot")
def unlock_brew_lot(brew_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Chỉ admin được mở khóa Nấu — phải mở khóa Lên men (công đoạn hạ lưu) trước."""
    if user.role != Role.ADMIN.value:
        raise PermissionError_("Chỉ admin được mở khóa lô.")
    unlocked = lot_lock_svc.unlock_brew(db, brew_id, user)
    return {"brew_id": unlocked.brew_id, "locked": False}


# ===== Mẻ (thuộc 1 mã nấu) =====
@router.get("/brew-batches")
def list_all_brew_batches(db: Session = Depends(get_db)):
    """Liệt kê phẳng TOÀN BỘ mẻ nấu (mọi mã nấu) — dùng cho Phạm vi Hold/Release theo công
    đoạn Nấu (tab Chất lượng), khác với /brews/{brew_id}/batches (theo 1 mã nấu)."""
    rows = db.execute(select(BrewBatch).order_by(BrewBatch.batch_year.desc(), BrewBatch.batch_code.desc())).scalars().all()
    brews = {b.brew_id: b for b in db.execute(select(BrewRecord)).scalars().all()}
    out = []
    for b in rows:
        brew = brews.get(b.brew_id)
        out.append({"batch_id": b.batch_id, "brew_id": b.brew_id, "batch_code": b.batch_code,
                    "brew_code": brew.brew_code if brew else None,
                    "quality_status": b.quality_status})
    return out


@router.get("/brews/{brew_id}/batches")
def list_brew_batches(brew_id: str, db: Session = Depends(get_db)):
    rows = db.execute(select(BrewBatch).where(BrewBatch.brew_id == brew_id)
                      .order_by(BrewBatch.seq, BrewBatch.created_at)).scalars().all()
    line_ids = {b.line_id for b in rows if b.line_id}
    lines = {l.line_id: l for l in db.execute(select(ProductionLine).where(
        ProductionLine.line_id.in_(line_ids))).scalars().all()} if line_ids else {}
    out = []
    for b in rows:
        exec_status = _exec_status(b.ended_at)
        line = lines.get(b.line_id)
        out.append({"batch_id": b.batch_id, "brew_id": b.brew_id, "batch_code": b.batch_code,
                    "line_id": b.line_id, "line_code": line.code if line else None,
                    "line_name": line.name if line else None,
                    "seq": b.seq, "note": b.note, "created_at": b.created_at,
                    "started_at": b.started_at, "ended_at": b.ended_at,
                    "exec_status": exec_status, "exec_status_label": EXEC_STATUS[exec_status],
                    "quality_status": b.quality_status})
    return out


@router.post("/brews/{brew_id}/batches", status_code=201)
def add_brew_batch(brew_id: str, payload: BrewBatchIn, db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)):
    require_perm(user, "batch.execute")
    brew, order = _brew_and_order(db, brew_id)
    if not brew:
        raise NotFoundError("Bản ghi nấu không tồn tại.")
    _assert_unlocked(brew, order)
    line = db.get(ProductionLine, payload.line_id)
    if not line or line.kind != "brewhouse":
        raise DomainError("Dây chuyền nấu không hợp lệ — phải chọn từ Danh mục dây chuyền (loại: Nhà nấu/brewhouse).")
    data = payload.model_dump()
    if not data.get("started_at"):
        data["started_at"] = utcnow()
    # Số mẻ (batch_code) là 1 dãy đếm chung TOÀN NHÀ MÁY, không phải riêng từng mã nấu —
    # 2 mã nấu khác nhau không được dùng trùng số mẻ. Dãy số reset lại mỗi năm (theo năm
    # của started_at) nên chỉ chặn trùng trong CÙNG năm — sang năm mới lại đánh số từ 1.
    batch_year = data["started_at"].year
    if db.execute(select(BrewBatch).where(BrewBatch.batch_year == batch_year,
                                          BrewBatch.batch_code == payload.batch_code)).scalar_one_or_none():
        raise DomainError(f"Mã mẻ '{payload.batch_code}' đã tồn tại trong năm {batch_year} (dù ở mã nấu khác) — số mẻ phải duy nhất trong năm.")
    batch = BrewBatch(batch_id=new_id(), brew_id=brew_id, batch_year=batch_year, **data)
    db.add(batch); db.flush()
    genealogy.add_edge(db, from_type="brew_batch", from_id=batch.batch_id, to_type="brew",
                       to_id=brew_id, relation="mẻ")
    # Mẻ mới thêm chưa "Kết thúc" — nếu tank lên men trước đó đã coi là nạp đầy (kt_date có
    # giá trị) thì phải tính lại về rỗng, đưa trạng thái lên men về "đang nấu" cho tới khi mẻ
    # mới này (và mọi mẻ khác) cũng kết thúc — xem services/derived.py::ferment_status.
    link = db.execute(select(FermentBrewLink).where(FermentBrewLink.brew_id == brew_id)).scalar_one_or_none()
    if link:
        _sync_ferment_kt_date(db, link.ferment_id)
    db.commit(); db.refresh(batch)
    return batch


@router.post("/brews/{brew_id}/batches/{batch_id}/finish")
def finish_brew_batch(brew_id: str, batch_id: str, payload: FinishIn = FinishIn(),
                      db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Vận hành chọn tay giờ kết thúc mẻ — gọi lại được nhiều lần để sửa giờ nếu bấm nhầm."""
    require_perm(user, "batch.execute")
    batch = db.get(BrewBatch, batch_id)
    if not batch or batch.brew_id != brew_id:
        raise NotFoundError("Mẻ không tồn tại.")
    _assert_unlocked(batch, *_brew_and_order(db, brew_id))
    batch.ended_at = payload.ended_at or utcnow()
    db.flush()
    link = db.execute(select(FermentBrewLink).where(FermentBrewLink.brew_id == brew_id)).scalar_one_or_none()
    if link:
        _sync_ferment_kt_date(db, link.ferment_id)
    db.commit(); db.refresh(batch)
    return batch


@router.delete("/brews/{brew_id}/batches/{batch_id}", status_code=204)
def delete_brew_batch(brew_id: str, batch_id: str, db: Session = Depends(get_db),
                      user: User = Depends(get_current_user)):
    require_perm(user, "batch.execute")
    batch = db.get(BrewBatch, batch_id)
    if not batch or batch.brew_id != brew_id:
        raise NotFoundError("Mẻ không tồn tại.")
    _assert_unlocked(batch, *_brew_and_order(db, brew_id))
    if _brew_already_filtered(db, brew_id):
        raise DomainError(f"Mã nấu của mẻ '{batch.batch_code}' đã được lọc — không thể xóa (ảnh hưởng truy xuất nguồn gốc).")
    for u in db.execute(select(BrewMaterialUsage).where(BrewMaterialUsage.batch_id == batch_id)).scalars().all():
        if u.movement_id:
            warehouse_svc.undo_issue(db, u.movement_id, user, strict=False)
        db.delete(u)
    for r in db.execute(select(QualityResult).where(QualityResult.scope_type == "brew_batch", QualityResult.scope_id == batch.batch_id)).scalars().all():
        db.delete(r)
    for s in db.execute(select(BrewProcessStep).where(BrewProcessStep.batch_id == batch_id)).scalars().all():
        db.delete(s)
    log = db.execute(select(BrewProcessLog).where(BrewProcessLog.batch_id == batch_id)).scalar_one_or_none()
    if log:
        db.delete(log)
    db.flush()  # MSSQL enforce FK: xóa usage/quality_result/process_step/process_log (con) trước brew_batch (cha).
    genealogy.delete_edges_for(db, "brew_batch", batch_id)
    db.delete(batch)
    db.flush()
    link = db.execute(select(FermentBrewLink).where(FermentBrewLink.brew_id == brew_id)).scalar_one_or_none()
    if link:
        _sync_ferment_kt_date(db, link.ferment_id)
    db.commit()


# ===== Ghi chép nấu (Step Protocol Braumat + biểu mẫu KCS) cho 1 mẻ cụ thể =====
@router.post("/brews/{brew_id}/batches/{batch_id}/process-log/import")
async def import_brew_process_log(brew_id: str, batch_id: str,
                                  files: list[UploadFile] = File(...),
                                  db: Session = Depends(get_db),
                                  user: User = Depends(get_current_user)):
    """Import 1 hoặc nhiều file Step Protocol PDF (Braumat) — mỗi file thường là 1 Unit
    (trạm công đoạn: RiceCooker, MashTun, LauterTun, WortKettle...), có thể tải lên cùng
    lúc nhiều file của cùng 1 mẻ."""
    batch = db.get(BrewBatch, batch_id)
    if not batch or batch.brew_id != brew_id:
        raise NotFoundError("Mẻ không tồn tại.")
    _assert_unlocked(batch, *_brew_and_order(db, brew_id))
    data = [(f.filename, await f.read()) for f in files]
    return braumat_svc.import_step_protocols(db, batch_id, data, user)


@router.get("/brews/{brew_id}/batches/{batch_id}/process-log")
def get_brew_process_log(brew_id: str, batch_id: str, db: Session = Depends(get_db)):
    batch = db.get(BrewBatch, batch_id)
    if not batch or batch.brew_id != brew_id:
        raise NotFoundError("Mẻ không tồn tại.")
    brew = db.get(BrewRecord, brew_id)
    log = braumat_svc.get_or_create_process_log(db, batch_id)
    steps = braumat_svc.list_process_steps(db, batch_id)
    spec = braumat_svc.get_spec_values(db, brew.product_id) if brew and brew.product_id \
        else {k: None for k in braumat_svc.SPEC_FIELD_KEYS}
    return {
        "braumat_order_number": log.braumat_order_number, "braumat_recipe": log.braumat_recipe,
        "batch_code": batch.batch_code, "brew_code": brew.brew_code if brew else None,
        "product_id": brew.product_id if brew else None,
        "note": log.note, "updated_by": log.updated_by, "updated_at": log.updated_at,
        "manual": braumat_svc.get_manual_values(log), "spec": spec,
        "steps": steps, "checkpoints": braumat_svc.checkpoint_summary(steps),
    }


@router.put("/brews/{brew_id}/batches/{batch_id}/process-log")
def update_brew_process_log(brew_id: str, batch_id: str, payload: BrewProcessLogIn,
                            db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    batch = db.get(BrewBatch, batch_id)
    if not batch or batch.brew_id != brew_id:
        raise NotFoundError("Mẻ không tồn tại.")
    _assert_unlocked(batch, *_brew_and_order(db, brew_id))
    log = braumat_svc.update_process_log(db, batch_id, payload.model_dump(exclude_unset=True), user)
    return {"note": log.note, **braumat_svc.get_manual_values(log)}


# ===== Nguyên liệu dùng cho 1 mẻ cụ thể =====
@router.get("/brews/{brew_id}/batches/{batch_id}/materials")
def list_brew_materials(brew_id: str, batch_id: str, db: Session = Depends(get_db)):
    rows = db.execute(select(BrewMaterialUsage).where(BrewMaterialUsage.batch_id == batch_id)
                      .order_by(BrewMaterialUsage.created_at)).scalars().all()
    return rows


@router.post("/brews/{brew_id}/batches/{batch_id}/materials", status_code=201)
def add_brew_material(brew_id: str, batch_id: str, payload: BrewMaterialUsageIn, db: Session = Depends(get_db),
                      user: User = Depends(get_current_user)):
    """Gán nguyên liệu cho 1 mẻ — ưu tiên lot_id (lô thật trong Kho phân xưởng): trừ tồn kho
    thật qua warehouse_svc.issue(), ghi lại movement_id để hoàn kho khi xóa. receipt_id/tên tự do
    chỉ còn là lối dự phòng cho nguyên liệu chưa có trong Kho NVL."""
    require_perm(user, "batch.execute")
    batch = db.get(BrewBatch, batch_id)
    if not batch or batch.brew_id != brew_id:
        raise NotFoundError("Mẻ không tồn tại.")
    _assert_unlocked(batch, *_brew_and_order(db, brew_id))
    data = payload.model_dump()
    lot_id = data.pop("lot_id", None)
    if lot_id:
        lot = db.get(MaterialLot, lot_id)
        if not lot:
            raise NotFoundError("Lô nguyên liệu không tồn tại.")
        if not warehouse_svc._is_workshop_location(lot.location):
            raise DomainError(f"Lô {lot.lot_code} không ở Kho phân xưởng — chỉ được dùng nguyên liệu từ Kho phân xưởng cho mẻ nấu.")
        material = db.get(Material, lot.material_id) if lot.material_id else None
        data["material_name"] = material.name if material else lot.lot_code
        data["lot_pm"] = lot.lot_code
        data["lot_date"] = lot.created_at
        data["fifo_ok"] = warehouse_svc.is_oldest_workshop_lot(db, lot.material_id, lot_id)
        data["uom"] = lot.uom
        result = warehouse_svc.issue(db, lot_id, data["quantity"], user, mode="tu_do",
                                     reason=f"Dùng cho mẻ nấu {batch.batch_code}", ref_doc=batch.batch_code)
        data["lot_id"] = lot_id
        data["movement_id"] = result["movement_id"]
    else:
        receipt_id = data.get("receipt_id")
        if receipt_id:
            receipt = db.get(MaterialReceipt, receipt_id)
            if not receipt:
                raise NotFoundError("Bản ghi nguyên liệu không tồn tại.")
            data["material_name"] = data.get("material_name") or receipt.material_name
            data["lot_pm"] = data.get("lot_pm") or receipt.lot_pm
        if not data.get("material_name"):
            raise DomainError("Chọn nguyên liệu hoặc nhập tên nguyên liệu.")
    u = BrewMaterialUsage(usage_id=new_id(), batch_id=batch_id, **data)
    db.add(u)
    if lot_id:
        genealogy.add_edge(db, from_type="lot", from_id=lot_id, to_type="brew_batch", to_id=batch_id,
                           relation="consume", quantity=data["quantity"], uom=data.get("uom"))
    db.commit(); db.refresh(u)
    return u


@router.put("/brews/{brew_id}/batches/{batch_id}/materials/{usage_id}")
def update_brew_material(brew_id: str, batch_id: str, usage_id: str, payload: BrewMaterialUsageIn,
                         db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    require_perm(user, "batch.execute")
    u = db.get(BrewMaterialUsage, usage_id)
    if not u or u.batch_id != batch_id:
        raise NotFoundError("Dòng nguyên liệu không tồn tại.")
    _assert_unlocked(db.get(BrewBatch, batch_id), *_brew_and_order(db, brew_id))
    data = payload.model_dump()
    if not data.get("material_name"):
        raise DomainError("Chọn nguyên liệu hoặc nhập tên nguyên liệu.")
    new_qty = data.get("quantity")
    if u.lot_id and u.movement_id and new_qty != u.quantity:
        warehouse_svc.undo_issue(db, u.movement_id, user)
        batch = db.get(BrewBatch, batch_id)
        lot = db.get(MaterialLot, u.lot_id)
        if lot:
            u.fifo_ok = warehouse_svc.is_oldest_workshop_lot(db, lot.material_id, u.lot_id)
        result = warehouse_svc.issue(db, u.lot_id, new_qty, user, mode="tu_do",
                                     reason=f"Dùng cho mẻ nấu {batch.batch_code} (sửa số lượng)", ref_doc=batch.batch_code)
        u.movement_id = result["movement_id"]
    for k, v in data.items():
        if k not in ("receipt_id", "lot_id") or v:
            setattr(u, k, v)
    db.commit(); db.refresh(u)
    return u


@router.delete("/brews/{brew_id}/batches/{batch_id}/materials/{usage_id}", status_code=204)
def delete_brew_material(brew_id: str, batch_id: str, usage_id: str, db: Session = Depends(get_db),
                         user: User = Depends(get_current_user)):
    require_perm(user, "batch.execute")
    u = db.get(BrewMaterialUsage, usage_id)
    if not u or u.batch_id != batch_id:
        raise NotFoundError("Dòng nguyên liệu không tồn tại.")
    _assert_unlocked(db.get(BrewBatch, batch_id), *_brew_and_order(db, brew_id))
    if u.movement_id:
        warehouse_svc.undo_issue(db, u.movement_id, user, strict=False)
    db.delete(u)
    db.commit()


# ===== Thông tin lên men =====
@router.get("/ferments")
def list_ferments(years: list[int] = Query(None), db: Session = Depends(get_db)):
    years = _years_or_current(years)
    rows = db.execute(select(FermentRecord).where(FermentRecord.ferment_year.in_(years))
                      .order_by(FermentRecord.brew_date.desc())).scalars().all()
    total_brew = sum(r.volume_hl for r in rows)
    total_cct = sum(r.on_hand_cct for r in rows)
    links = db.execute(select(FermentBrewLink)).scalars().all()
    brews_by_ferment: dict[str, list[str]] = {}
    for link in links:
        brews_by_ferment.setdefault(link.ferment_id, []).append(link.brew_id)
    products = {p.product_id: p for p in db.execute(select(Product)).scalars().all()}
    items = []
    beer_types = {bt.beer_type_id: bt for bt in db.execute(select(BeerType)).scalars().all()}
    for r in rows:
        prod = products.get(r.product_id)
        beer_type = beer_types.get(prod.beer_type_id) if prod and prod.beer_type_id else None
        ready_date = None
        days_elapsed = None
        if r.brew_date:
            days_elapsed = (utcnow().replace(tzinfo=None) - r.brew_date.replace(tzinfo=None)).days
            if prod and prod.ferment_days_std:
                ready_date = r.brew_date + timedelta(days=prod.ferment_days_std)
        # Lên men không có khái niệm NVL riêng (men/nguyên liệu tính ở Nấu) — chỉ 2 màu theo
        # chỉ tiêu CT chính + CT phụ (khớp đúng scope 2 nút app.js:4150-4151).
        chinh_ok = _stage_ok(db, "len_men_chinh", "ferment", f"{r.lm_code}__len_men_chinh", r.product_id)
        phu_ok = _stage_ok(db, "len_men_phu", "ferment", f"{r.lm_code}__len_men_phu", r.product_id)
        color = "blue" if (chinh_ok and phu_ok) else "red"
        # Số chỉ tiêu CT chính + CT phụ đang FAIL (giá trị MỚI NHẤT theo từng chỉ tiêu) — dùng cho
        # badge cảnh báo ở biểu đồ Dashboard, tái dùng đúng helper latest_results_by_param đã có
        # (services/quality.py) thay vì viết lại logic khử trùng lặp/lấy-mới-nhất.
        qc_fail_count = sum(
            1 for res in quality.latest_results_by_param(db, "ferment", f"{r.lm_code}__len_men_chinh").values()
            if res.status == "fail"
        ) + sum(
            1 for res in quality.latest_results_by_param(db, "ferment", f"{r.lm_code}__len_men_phu").values()
            if res.status == "fail"
        )
        items.append({"ferment_id": r.ferment_id, "lm_code": r.lm_code, "brew_code": r.brew_code,
                      "color": color,
                      "brew_date": r.brew_date, "kt_date": r.kt_date, "batch_numbers": r.batch_numbers,
                      "brew_ids": brews_by_ferment.get(r.ferment_id, []),
                      "wort_type": r.wort_type, "product_id": r.product_id,
                      "product_code": prod.code if prod else None,
                      "beer_type_id": prod.beer_type_id if prod else None,
                      "beer_type_name": beer_type.name if beer_type else None,
                      "ferment_days_std": prod.ferment_days_std if prod else None,
                      "days_elapsed": days_elapsed, "ready_date": ready_date,
                      "yeast_gen": r.yeast_gen, "tank_lm": r.tank_lm,
                      "volume_hl": r.volume_hl, "on_hand_cct": r.on_hand_cct,
                      "status": derived.ferment_status(r), "ferment_days": r.ferment_days,
                      "qc_approved": r.qc_approved, "qc_approved_by": r.qc_approved_by,
                      "qc_approved_at": r.qc_approved_at,
                      "locked": r.locked, "locked_by": r.locked_by,
                      "quality_status": r.quality_status, "qc_fail_count": qc_fail_count})
    return {"items": items, "total_brew_hl": round(total_brew, 1), "total_cct_hl": round(total_cct, 1)}


@router.post("/ferments/{ferment_id}/approve")
def approve_ferment(ferment_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """KCS ký xác nhận tank lên men đạt, đồng ý cho chiết — gate cho việc tạo bản ghi
    lọc từ tank này (xem add_filter). Yêu cầu đã khai báo đủ chỉ tiêu lên men phụ bắt buộc
    trước khi ký; chỉ tiêu FAIL (vượt giới hạn) không còn chặn duyệt, chỉ cảnh báo
    (qc_has_fail trong response) — KCS tự quyết định dựa trên cảnh báo đó."""
    require_perm(user, "quality.release")
    f = db.get(FermentRecord, ferment_id)
    if not f:
        raise NotFoundError("Bản ghi lên men không tồn tại.")
    _assert_unlocked(f)
    status = qc_catalog.stage_qc_status(db, "len_men_phu", "ferment", f"{f.lm_code}__len_men_phu", f.product_id)
    if status["pending"]:
        raise DomainError(f"Còn thiếu chỉ tiêu bắt buộc (lên men phụ): {', '.join(status['pending'])}.")
    f.qc_approved = True
    f.qc_approved_by = user.username
    f.qc_approved_at = utcnow()
    db.commit()
    return {"ferment_id": ferment_id, "qc_approved": True, "qc_has_fail": status["has_fail"]}


@router.post("/ferments/{ferment_id}/lock-lot")
def lock_ferment_lot(ferment_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """KCS khóa Lên men — yêu cầu Nấu (mã nấu nguồn) đã khóa trước, đã Duyệt LM và đủ chỉ
    tiêu lên men chính (xem services/lot_lock.py)."""
    require_perm(user, "quality.release")
    locked = lot_lock_svc.lock_ferment(db, ferment_id, user)
    return {"ferment_id": locked.ferment_id, "locked": True}


@router.post("/ferments/{ferment_id}/unlock-lot")
def unlock_ferment_lot(ferment_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Chỉ admin được mở khóa Lên men — phải mở khóa Lọc (công đoạn hạ lưu) trước."""
    if user.role != Role.ADMIN.value:
        raise PermissionError_("Chỉ admin được mở khóa lô.")
    unlocked = lot_lock_svc.unlock_ferment(db, ferment_id, user)
    return {"ferment_id": unlocked.ferment_id, "locked": False}


@router.post("/ferments", status_code=201)
def add_ferment(payload: FermentIn, db: Session = Depends(get_db),
                user: User = Depends(get_current_user)):
    require_perm(user, "batch.execute")
    data = payload.model_dump()
    brew_ids = data.pop("brew_ids", [])
    for brew_id in brew_ids:
        _assert_unlocked(*_brew_and_order(db, brew_id))
    ferment_year = (data.get("brew_date") or utcnow()).year
    if db.execute(select(FermentRecord).where(FermentRecord.lm_code == data["lm_code"],
                  FermentRecord.ferment_year == ferment_year)).scalar_one_or_none():
        raise DomainError(f"Mã lô LM '{data['lm_code']}' đã tồn tại trong năm {ferment_year}.")
    data["ferment_year"] = ferment_year
    f = FermentRecord(ferment_id=new_id(), **data)
    if not f.on_hand_cct:
        f.on_hand_cct = f.volume_hl
    db.add(f)
    if brew_ids:
        brews = db.execute(select(BrewRecord).where(BrewRecord.brew_id.in_(brew_ids))).scalars().all()
        for brew_id in brew_ids:
            db.add(FermentBrewLink(link_id=new_id(), ferment_id=f.ferment_id, brew_id=brew_id))
            genealogy.add_edge(db, from_type="brew", from_id=brew_id, to_type="ferment",
                               to_id=f.ferment_id, relation="lên men")
        f.batch_numbers = ", ".join(b.brew_code for b in brews)
    db.commit(); db.refresh(f)
    return f


@router.delete("/ferments/{ferment_id}", status_code=204)
def delete_ferment(ferment_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    require_perm(user, "batch.execute")
    f = db.get(FermentRecord, ferment_id)
    if not f:
        raise NotFoundError("Bản ghi lên men không tồn tại.")
    _assert_unlocked(f)
    filter_order_ids = _filter_order_ids_for_ferments(db, [ferment_id])
    if filter_order_ids and db.execute(select(FilterRecord).where(FilterRecord.filter_order_id.in_(filter_order_ids))).first():
        raise DomainError("Đã có bản ghi lọc lấy từ lô lên men này — xóa bản ghi lọc trước khi xóa lên men.")
    for link in db.execute(select(FermentBrewLink).where(FermentBrewLink.ferment_id == ferment_id)).scalars().all():
        db.delete(link)
    for r in db.execute(select(QualityResult).where(QualityResult.scope_type == "ferment",
                        QualityResult.scope_id.in_([f"{f.lm_code}__len_men_chinh", f"{f.lm_code}__len_men_phu"]))).scalars().all():
        db.delete(r)
    for rd in db.execute(select(FermentDailyReading).where(FermentDailyReading.ferment_id == ferment_id)).scalars().all():
        db.delete(rd)
    for lg in db.execute(select(FermentProcessLog).where(FermentProcessLog.ferment_id == ferment_id)).scalars().all():
        db.delete(lg)
    db.flush()  # MSSQL enforce FK: xóa link/reading/process_log/quality_result (con) trước ferment_record (cha).
    genealogy.delete_edges_for(db, "ferment", ferment_id)
    db.delete(f)
    db.commit()


def _ferment_reading_dict(r: FermentDailyReading) -> dict:
    return {"day_no": r.day_no, "reading_date": r.reading_date,
            "nhiet_do_c": r.nhiet_do_c, "do_s": r.do_s, "mat_do_tb": r.mat_do_tb,
            "measured_by": r.measured_by, "measured_at": r.measured_at,
            "kcs": r.kcs, "kcs_by": r.kcs_by, "kcs_at": r.kcs_at,
            "truc_ca": r.truc_ca, "truc_ca_by": r.truc_ca_by, "truc_ca_at": r.truc_ca_at}


@router.get("/ferments/{ferment_id}/process-log")
def get_ferment_process_log(ferment_id: str, db: Session = Depends(get_db)):
    f = db.get(FermentRecord, ferment_id)
    if not f:
        raise NotFoundError("Bản ghi lên men không tồn tại.")
    log = ferment_log_svc.get_or_create_process_log(db, ferment_id)
    readings = ferment_log_svc.get_daily_readings(db, ferment_id)
    return {
        "auto": ferment_log_svc.auto_header_values(db, f),
        "manual": ferment_log_svc.get_manual_values(log),
        "ha_phu_events": ferment_log_svc.get_ha_phu_events(log),
        "note": log.note, "updated_by": log.updated_by, "updated_at": log.updated_at,
        "readings": [_ferment_reading_dict(r) for r in readings],
    }


@router.put("/ferments/{ferment_id}/process-log")
def update_ferment_process_log(ferment_id: str, payload: FermentProcessLogIn,
                               db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    f = db.get(FermentRecord, ferment_id)
    if not f:
        raise NotFoundError("Bản ghi lên men không tồn tại.")
    _assert_unlocked(f)
    log = ferment_log_svc.update_process_log(db, ferment_id, payload.model_dump(exclude_unset=True), user)
    return {"note": log.note, **ferment_log_svc.get_manual_values(log),
            "ha_phu_events": ferment_log_svc.get_ha_phu_events(log)}


@router.put("/ferments/{ferment_id}/process-log/readings")
def update_ferment_daily_readings(ferment_id: str, payload: FermentDailyReadingsIn,
                                  db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    f = db.get(FermentRecord, ferment_id)
    if not f:
        raise NotFoundError("Bản ghi lên men không tồn tại.")
    _assert_unlocked(f)
    rows = [r.model_dump() for r in payload.readings]
    readings = ferment_log_svc.upsert_daily_readings(db, ferment_id, rows, user)
    return [_ferment_reading_dict(r) for r in readings]


# ===== Thông tin lọc =====
@router.get("/filters")
def list_filters(years: list[int] = Query(None), db: Session = Depends(get_db)):
    years = _years_or_current(years)
    rows = db.execute(select(FilterRecord).where(FilterRecord.filter_year.in_(years))
                      .order_by(FilterRecord.filter_date.desc())).scalars().all()
    products = {p.product_id: p for p in db.execute(select(Product)).scalars().all()}
    finished_products = {fp.finished_product_id: fp for fp in db.execute(select(FinishedProduct)).scalars().all()}
    nvl_filter_ids = {row[0] for row in db.execute(select(FilterMaterialUsage.filter_id).distinct()).all()}
    filter_orders = {o.filter_order_id: o for o in db.execute(select(FilterOrder)).scalars().all()}
    # Dịch bia (Product) của TỪNG tank nguồn — 1 mẻ lọc "phối" gộp >=2 tank nguồn khác dịch bia,
    # FilterRecord.product_id chỉ tham khảo 1 tank nên không đủ; lấy riêng theo thứ tự tank (seq)
    # để hiển thị "dịch tank 1 + dịch tank 2..." ở bảng "Thông tin lọc" (xem VIEWS.process sec=loc).
    filter_ids = [r.filter_id for r in rows]
    tank_lines = db.execute(select(FilterOrderTank).where(FilterOrderTank.filter_id.in_(filter_ids))
                            .order_by(FilterOrderTank.seq)).scalars().all() if filter_ids else []
    lines_by_filter: dict[str, list] = {}
    for l in tank_lines:
        lines_by_filter.setdefault(l.filter_id, []).append(l)
    ferment_ids = {l.ferment_id for l in tank_lines if l.ferment_id}
    ferments_by_id = {f.ferment_id: f for f in db.execute(
        select(FermentRecord).where(FermentRecord.ferment_id.in_(ferment_ids))).scalars().all()} if ferment_ids else {}
    source_filter_ids = {l.source_filter_id for l in tank_lines if l.source_filter_id}
    source_filters_by_id = {f.filter_id: f for f in db.execute(
        select(FilterRecord).where(FilterRecord.filter_id.in_(source_filter_ids))).scalars().all()} if source_filter_ids else {}

    def _source_products(filter_id: str) -> list:
        out_codes = []
        for l in lines_by_filter.get(filter_id, []):
            pid = None
            if l.tank_type == "bbt":
                src = source_filters_by_id.get(l.source_filter_id)
                pid = src.product_id if src else None
            else:
                ferment = ferments_by_id.get(l.ferment_id)
                pid = ferment.product_id if ferment else None
            out_codes.append(products[pid].code if pid in products else None)
        return out_codes

    out = []
    for r in rows:
        order = filter_orders.get(r.filter_order_id)
        if r.filter_type == "ve_bbt_phoi":
            color = "cyan"
        elif not _stage_ok(db, "loc", "filter", r.filter_code, r.product_id, beer_type_id=r.beer_type_id,
                           finished_product_id=r.finished_product_id):
            color = "red"
        elif r.filter_id not in nvl_filter_ids:
            color = "green"
        else:
            color = "blue"
        status = derived.filter_status(r)
        exec_status = _exec_status(r.ended_at)
        out.append({"filter_id": r.filter_id, "filter_code": r.filter_code, "brew_code": r.brew_code,
                    "filter_order_id": r.filter_order_id,
                    "lot_loc": r.lot_loc, "filter_phoi_code": r.filter_phoi_code, "filter_date": r.filter_date,
                    "filter_type": r.filter_type, "wort_type": r.wort_type, "from_cct": r.from_cct,
                    "product_id": r.product_id, "product_code": products[r.product_id].code if r.product_id in products else None,
                    "beer_type_id": r.beer_type_id,
                    "finished_product_id": r.finished_product_id,
                    "finished_product_code": finished_products[r.finished_product_id].code if r.finished_product_id in finished_products else None,
                    "finished_product_name": finished_products[r.finished_product_id].name if r.finished_product_id in finished_products else None,
                    "v_dich_hl": r.v_dich_hl, "beer_type": r.beer_type, "nuoc_bai_khi_hl": r.nuoc_bai_khi_hl,
                    "v_beer_hl": r.v_beer_hl,
                    "to_bbt": r.to_bbt, "status": status, "status_label": FILTER_STATUS.get(status, status),
                    "on_hand_bbt": r.on_hand_bbt, "color": color,
                    "ended_at": r.ended_at, "exec_status": exec_status, "exec_status_label": EXEC_STATUS[exec_status],
                    "qc_approved": r.qc_approved, "qc_approved_by": r.qc_approved_by, "qc_approved_at": r.qc_approved_at,
                    "locked": r.locked or bool(order and order.locked), "locked_by": r.locked_by or (order.locked_by if order else None),
                    "batch_number": r.batch_number, "order_number": r.order_number,
                    "quality_status": r.quality_status, "source_products": _source_products(r.filter_id)})
    return out


@router.post("/filters/{filter_id}/approve")
def approve_filter(filter_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """KCS ký duyệt mẻ lọc — yêu cầu đã khai báo đủ chỉ tiêu lọc bắt buộc trước khi ký,
    mirror approve_ferment. Chỉ tiêu FAIL (vượt giới hạn) không còn chặn duyệt, chỉ cảnh báo
    (qc_has_fail trong response)."""
    require_perm(user, "quality.release")
    f = db.get(FilterRecord, filter_id)
    if not f:
        raise NotFoundError("Bản ghi lọc không tồn tại.")
    _assert_unlocked(f, *_filter_order_chain(db, f.filter_order_id))
    if f.qc_approved:
        raise DomainError("Mẻ lọc này đã được duyệt.")
    if f.ended_at is None:
        raise DomainError("Mẻ lọc đang lọc (chưa kết thúc hết các tank) — chỉ duyệt KCS khi đã lọc xong.")
    status = qc_catalog.stage_qc_status(db, "loc", "filter", f.filter_code, beer_type_id=f.beer_type_id,
                                        finished_product_id=f.finished_product_id)
    if status["pending"]:
        raise DomainError(f"Còn thiếu chỉ tiêu bắt buộc (lọc): {', '.join(status['pending'])}.")
    f.qc_approved = True
    f.qc_approved_by = user.username
    f.qc_approved_at = utcnow()
    db.commit()
    return {"filter_id": filter_id, "qc_approved": True, "qc_has_fail": status["has_fail"]}


@router.post("/filters/{filter_id}/lock-lot")
def lock_filter_lot(filter_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """KCS khóa Lọc — yêu cầu (các) nguồn (Lên men hoặc mẻ lọc lại) đã khóa trước, đã Duyệt
    KCS và đã kết thúc đủ tank (xem services/lot_lock.py)."""
    require_perm(user, "quality.release")
    locked = lot_lock_svc.lock_filter(db, filter_id, user)
    return {"filter_id": locked.filter_id, "locked": True}


@router.post("/filters/{filter_id}/unlock-lot")
def unlock_filter_lot(filter_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Chỉ admin được mở khóa Lọc — phải mở khóa Chiết (công đoạn hạ lưu) trước."""
    if user.role != Role.ADMIN.value:
        raise PermissionError_("Chỉ admin được mở khóa lô.")
    unlocked = lot_lock_svc.unlock_filter(db, filter_id, user)
    return {"filter_id": unlocked.filter_id, "locked": False}


def _next_lot_number(db: Session, model, field: str) -> str:
    """Số lô tự sinh = số lớn nhất hiện có (trong cột field của model) + 1 — tự động hoá số
    lô lọc/số lô chiết, không cần người vận hành tự gõ tay/tự nhớ số tiếp theo."""
    vals = db.execute(select(getattr(model, field))).scalars().all()
    nums = [int(v) for v in vals if v and v.isdigit()]
    return str(max(nums) + 1) if nums else "1"


@router.post("/filters", status_code=201)
def add_filter(payload: FilterIn, db: Session = Depends(get_db),
               user: User = Depends(get_current_user)):
    """Tank nguồn không tự chọn tay — bắt buộc chọn 1 Lệnh lọc (xem filter_order_svc);
    product_id/wort_type/brew_code/from_cct tự điền từ tank(s) của lệnh đó (không phối: 1
    tank; phối: nhiều tank, from_cct liệt kê tên các tank). Tank BBT (to_bbt): mẻ lọc ĐẦU TIÊN
    của 1 lệnh chọn tự do; mẻ SAU của cùng lệnh CHỈ được đổi sang tank khác nếu mẻ gần nhất đã
    "kết thúc" (ended_at) — còn dở dang thì bắt buộc dùng lại đúng tank đó (không cho đổi giữa
    chừng). Lý do: 1 tank BBT có thể quá bé so với 1 mẻ lọc thật, phải tách sang tank khác giữa
    chừng — batch_number/order_number của mẻ trước được tự kế thừa sang bản ghi mới (cùng 1 mẻ
    giấy, chỉ khác tank chứa, có thể sửa lại ở "Kết thúc" nếu thực ra là mẻ khác). Mọi lượt
    chọn tank (mẻ đầu, hoặc mẻ sau khi tank trước đã kết thúc) đều qua kiểm tra tank chưa được
    KCS duyệt (xem filter_order_svc._bbt_target_blocked_by) — nhiều Lệnh lọc KHÁC NHAU được
    phép cùng đổ vào 1 tank vật lý (thể tích cộng dồn) MIỄN chưa có mẻ nào trong tank được
    duyệt KCS; sau khi duyệt, tank khoá lại chỉ còn chờ chiết ra. 1 lệnh có thể có NHIỀU bản
    ghi lọc ("mẻ lọc") — sản lượng (v_beer_hl) của tất cả mẻ lọc cộng dồn lại và so với thể
    tích kế hoạch (FilterOrder.planned_volume_hl) ±sai số cho phép; khi đã đạt (is_complete)
    thì không tạo thêm được nữa (xem filter_order_svc._is_complete). Đã bắt đầu chiết (có
    BottleRecord tham chiếu 1 trong các mẻ lọc của lệnh) thì cũng không cho thêm mẻ lọc mới nữa
    — chỉ được thêm khi lệnh còn ở trạng thái Đang lọc (xem filter_order_svc._chiet_started)."""
    require_perm(user, "batch.execute")
    data = payload.model_dump()
    filter_order_id = data.pop("filter_order_id")
    order = db.get(FilterOrder, filter_order_id)
    if not order:
        raise NotFoundError("Lệnh lọc không tồn tại.")
    _assert_unlocked(order, db.get(FilterMasterOrder, order.master_order_id) if order.master_order_id else None)

    existing_records = db.execute(select(FilterRecord).where(
        FilterRecord.filter_order_id == filter_order_id).order_by(FilterRecord.filter_date)).scalars().all()
    record_summaries = [{"v_beer_hl": r.v_beer_hl, "ended_at": r.ended_at} for r in existing_records]
    if filter_order_svc._is_complete(record_summaries, order.planned_volume_hl, order.volume_tolerance_hl):
        raise DomainError("Lệnh lọc này đã hoàn thành (đủ thể tích kế hoạch) — không thể thêm mẻ lọc mới.")
    if filter_order_svc._chiet_started(db, filter_order_id):
        raise DomainError("Lệnh lọc này đã bắt đầu chiết — chỉ được thêm mẻ lọc khi lệnh còn ở trạng thái Đang lọc.")

    last = existing_records[-1] if existing_records else None
    if last and last.ended_at is None:
        # Mẻ gần nhất của lệnh này còn đang lọc dở dang — bắt buộc tiếp tục đúng tank đó, bỏ
        # qua to_bbt client gửi lên (không cho đổi tank giữa chừng khi tank chưa kết thúc).
        data["to_bbt"] = last.to_bbt
        data["batch_number"] = last.batch_number
        data["order_number"] = last.order_number
    else:
        # Mẻ ĐẦU TIÊN của lệnh, HOẶC mẻ gần nhất đã kết thúc (tank cũ đầy/xong, tràn sang tank
        # khác) — tank chọn tự do, qua kiểm tra chưa được KCS duyệt.
        chosen_to_bbt = data.get("to_bbt")
        if not chosen_to_bbt:
            raise DomainError("Chọn Tank BBT trước khi thêm mẻ lọc.")
        blocked_reason = filter_order_svc._bbt_target_blocked_by(db, chosen_to_bbt)
        if blocked_reason:
            raise DomainError(blocked_reason)
        if last:
            data["batch_number"] = last.batch_number
            data["order_number"] = last.order_number

    tank_lines = db.execute(select(FilterOrderTank).where(
        FilterOrderTank.filter_order_id == filter_order_id,
        FilterOrderTank.filter_id.is_(None)).order_by(FilterOrderTank.seq)).scalars().all()
    cct_lines = [l for l in tank_lines if l.tank_type == "cct"]
    bbt_lines = [l for l in tank_lines if l.tank_type == "bbt"]
    ferments = [db.get(FermentRecord, l.ferment_id) for l in cct_lines]
    bbt_sources = []
    for l in bbt_lines:
        src = db.execute(select(FilterRecord).where(FilterRecord.to_bbt == l.source_bbt_code)
                         .order_by(FilterRecord.filter_date.desc())).scalars().first()
        if not src:
            raise DomainError(f"Tank BBT nguồn '{l.source_bbt_code}' không còn mẻ lọc nào — không thể tạo mẻ lọc lại.")
        bbt_sources.append((l, src))

    first = ferments[0] if ferments else bbt_sources[0][1]
    if not data.get("lot_loc"):
        data["lot_loc"] = _next_lot_number(db, FilterRecord, "lot_loc")
    data["product_id"] = first.product_id
    # Loại bia không nhập tay — kế thừa từ lệnh lọc (đã suy ra/chọn lúc lập lệnh, xem
    # services/filter_order.py::_validate_tanks) — dùng để tra chỉ tiêu Lọc, không phải
    # product_id cụ thể (khác dịch bia nhưng cùng Loại bia vẫn phải chung 1 bộ chỉ tiêu).
    # Nếu chưa suy ra được (dịch bia của tank chưa gán Loại bia) thì giữ nguyên giá trị
    # client gửi lên (tương thích ngược, xem FilterIn.beer_type), chỉ mặc định "" nếu
    # không có gì cả.
    data["beer_type_id"] = order.beer_type_id
    if order.beer_type_id:
        beer_type = db.get(BeerType, order.beer_type_id)
        if beer_type:
            data["beer_type"] = beer_type.name
    if not data.get("beer_type"):
        data["beer_type"] = ""
    # Sản phẩm đích (SKU, tuỳ chọn) — kế thừa từ Lệnh lọc giống beer_type_id, dùng để tra
    # chỉ tiêu Lọc khi cùng 1 Loại bia cần phân biệt theo hình thức đóng gói (xem
    # qc_catalog.SKU_SCOPED_STAGES).
    data["finished_product_id"] = order.finished_product_id
    total_sources = len(ferments) + len(bbt_sources)
    if total_sources == 1:
        if ferments:
            data["ferment_id"] = ferments[0].ferment_id
            data["source_filter_id"] = None
            data["from_cct"] = ferments[0].tank_lm
            data["brew_code"] = ferments[0].brew_code
        else:
            l, src = bbt_sources[0]
            data["ferment_id"] = None
            data["source_filter_id"] = src.filter_id
            data["from_cct"] = f"BBT {l.source_bbt_code} (lọc lại — mẻ {src.filter_code})"
            data["brew_code"] = src.brew_code
    else:
        data["ferment_id"] = None
        data["source_filter_id"] = None
        labels = [f.tank_lm for f in ferments] + [f"BBT {l.source_bbt_code} (lọc lại)" for l, _ in bbt_sources]
        data["from_cct"] = ", ".join(labels)
        codes = {f.brew_code for f in ferments if f.brew_code} | {src.brew_code for _, src in bbt_sources if src.brew_code}
        data["brew_code"] = ", ".join(sorted(codes))
    if bbt_sources:
        data["filter_type"] = "loc_lai"
    if not data.get("wort_type"):
        data["wort_type"] = first.wort_type

    filter_year = (data.get("filter_date") or utcnow()).year
    if db.execute(select(FilterRecord).where(FilterRecord.filter_code == data["filter_code"],
                  FilterRecord.filter_year == filter_year)).scalar_one_or_none():
        raise DomainError(f"Mã lọc '{data['filter_code']}' đã tồn tại trong năm {filter_year}.")
    data["filter_year"] = filter_year

    f = FilterRecord(filter_id=new_id(), filter_order_id=filter_order_id, **data)
    db.add(f); db.flush()
    for line in cct_lines:
        db.add(FilterOrderTank(line_id=new_id(), filter_order_id=filter_order_id, filter_id=f.filter_id,
                               tank_type="cct", ferment_id=line.ferment_id, seq=line.seq))
    for line, src in bbt_sources:
        db.add(FilterOrderTank(line_id=new_id(), filter_order_id=filter_order_id, filter_id=f.filter_id,
                               tank_type="bbt", source_bbt_code=line.source_bbt_code,
                               source_filter_id=src.filter_id, reason=line.reason, seq=line.seq))
    for ferment in ferments:
        genealogy.add_edge(db, from_type="ferment", from_id=ferment.ferment_id, to_type="filter",
                           to_id=f.filter_id, relation="lọc")
    for _, src in bbt_sources:
        genealogy.add_edge(db, from_type="filter", from_id=src.filter_id, to_type="filter",
                           to_id=f.filter_id, relation="lọc lại")
    db.commit(); db.refresh(f)
    return f


def _sync_filter_aggregate(db: Session, f: FilterRecord) -> None:
    """Tổng hợp Dịch nha lọc/Nước bài khí/Sản lượng lọc của FilterRecord = tổng các dòng
    FilterOrderTank NHÂN BẢN RIÊNG của bản ghi này (filter_id khớp — mỗi FilterRecord của 1
    lệnh lọc có bộ dòng "kết thúc" độc lập, xem add_filter/finish_filter_tank, tránh double-
    count khi 1 lệnh có nhiều bản ghi chia vào nhiều tank BBT). on_hand_bbt điều chỉnh theo
    CHÊNH LỆCH, giữ nguyên phần đã tiêu thụ (Chiết) — sửa số liệu 1 tank nhiều lần không làm
    sai lệch tồn đã phát sinh. ended_at (toàn bản ghi) chỉ có giá trị khi TẤT CẢ tank đã kết
    thúc — mirror _sync_ferment_kt_date (để trống tới khi xong)."""
    lines = db.execute(select(FilterOrderTank).where(
        FilterOrderTank.filter_id == f.filter_id)).scalars().all()
    old_v_beer = f.v_beer_hl or 0.0
    consumed_bbt = old_v_beer - f.on_hand_bbt
    new_v_dich = sum(l.v_dich_hl or 0.0 for l in lines)
    new_bai_khi = sum(l.nuoc_bai_khi_hl or 0.0 for l in lines)
    new_v_beer = new_v_dich + new_bai_khi
    f.v_dich_hl = new_v_dich
    f.nuoc_bai_khi_hl = new_bai_khi
    f.v_beer_hl = new_v_beer
    f.on_hand_bbt = max(0.0, new_v_beer - consumed_bbt)
    f.ended_at = (max(l.ended_at for l in lines)
                  if lines and all(l.ended_at is not None for l in lines) else None)


@router.get("/filters/{filter_id}/tanks")
def list_filter_tanks(filter_id: str, db: Session = Depends(get_db)):
    f = db.get(FilterRecord, filter_id)
    if not f:
        raise NotFoundError("Bản ghi lọc không tồn tại.")
    lines = db.execute(select(FilterOrderTank).where(
        FilterOrderTank.filter_id == filter_id).order_by(FilterOrderTank.seq)).scalars().all()
    out = []
    for l in lines:
        exec_status = _exec_status(l.ended_at)
        if l.tank_type == "bbt":
            out.append({"line_id": l.line_id, "tank_type": "bbt", "ferment_id": None,
                        "tank_lm": None, "lm_code": None, "source_bbt_code": l.source_bbt_code,
                        "reason": l.reason, "seq": l.seq,
                        "ended_at": l.ended_at, "v_dich_hl": l.v_dich_hl, "nuoc_bai_khi_hl": l.nuoc_bai_khi_hl,
                        "batch_number": f.batch_number, "order_number": f.order_number,
                        "batch_seq_no": l.batch_seq_no, "is_final_batch": l.is_final_batch,
                        "exec_status": exec_status, "exec_status_label": EXEC_STATUS[exec_status]})
        else:
            ferment = db.get(FermentRecord, l.ferment_id)
            out.append({"line_id": l.line_id, "tank_type": "cct", "ferment_id": l.ferment_id,
                        "tank_lm": ferment.tank_lm if ferment else None, "lm_code": ferment.lm_code if ferment else None,
                        "source_bbt_code": None, "reason": None, "seq": l.seq,
                        "ended_at": l.ended_at, "v_dich_hl": l.v_dich_hl, "nuoc_bai_khi_hl": l.nuoc_bai_khi_hl,
                        "batch_number": f.batch_number, "order_number": f.order_number,
                        "batch_seq_no": l.batch_seq_no, "is_final_batch": l.is_final_batch,
                        "exec_status": exec_status, "exec_status_label": EXEC_STATUS[exec_status]})
    return out


@router.post("/filters/{filter_id}/tanks/{line_id}/toggle-final")
def toggle_final_batch(filter_id: str, line_id: str, db: Session = Depends(get_db),
                       user: User = Depends(get_current_user)):
    """Đảo cờ is_final_batch cho 1 dòng "mẻ lọc số" — đánh dấu/bỏ đánh dấu đây là đợt rút CUỐI
    của 1 mẻ lọc thật (thường sản lượng thấp một cách bình thường do "vét" tank) để báo cáo sản
    lượng theo mẻ lọc số (xem filter_line_yield_report) loại dòng này khỏi phân loại Thấp/Cao."""
    require_perm(user, "batch.execute")
    f = db.get(FilterRecord, filter_id)
    if not f:
        raise NotFoundError("Bản ghi lọc không tồn tại.")
    _assert_unlocked(f, *_filter_order_chain(db, f.filter_order_id))
    line = db.get(FilterOrderTank, line_id)
    if not line or line.filter_id != f.filter_id:
        raise NotFoundError("Dòng mẻ không tồn tại trong bản ghi lọc này.")
    line.is_final_batch = not line.is_final_batch
    db.commit()
    return {"line_id": line.line_id, "is_final_batch": line.is_final_batch}


@router.get("/bbt-tanks")
def list_available_bbt_tanks(db: Session = Depends(get_db)):
    """Tổng hợp theo từng tank BBT vật lý — dùng cho picker chọn tank nguồn 'lọc lại' (Tạo
    Lệnh lọc) và điều kiện chiết đã siết chặt (xem services/filter_order.py::available_bbt_tanks)."""
    return filter_order_svc.available_bbt_tanks(db)


@router.get("/ferment-tanks")
def list_available_ferment_tanks(db: Session = Depends(get_db)):
    """Từng tank lên men (CCT) kèm cờ đang chiếm dụng hay không — dùng cho picker "Tank lên
    men" khi tạo mã nấu (tab Nấu), xem services/dashboard.py::available_ferment_tanks."""
    return dashboard_svc.available_ferment_tanks(db)


@router.post("/filters/{filter_id}/tanks/{line_id}/finish")
def finish_filter_tank(filter_id: str, line_id: str, payload: FinishFilterTankIn = FinishFilterTankIn(),
                       db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Vận hành chọn tay giờ kết thúc CHO 1 TANK trong lệnh lọc (không phối chỉ có 1 dòng;
    phối có nhiều dòng, kết thúc riêng từng dòng) — gọi lại được nhiều lần để sửa giờ/số liệu
    nếu bấm nhầm. Bắt buộc kèm batch_number/order_number (khớp phiếu giấy) mỗi lần gọi — ghi
    lên cả FilterRecord (không phải riêng dòng tank). batch_number/order_number/batch_seq_no
    ĐỀU KHÔNG kiểm tra trùng — thực tế vận hành có thể lặp lại số mẻ/số lệnh giấy giữa các lệnh
    lọc khác nhau (VD reset số theo ca/ngày); báo cáo sản lượng theo mẻ lọc số (xem
    services/filter_yield_report.py::filter_line_yield_report) tự gộp các dòng cùng bộ 3 giá
    trị này lại thành 1 mẻ thật khi tính sản lượng, nên không cần chặn trùng ở đây nữa. Dịch nha
    lọc (v_dich_hl) BẮT BUỘC > 0 mỗi lần gọi (kể cả gọi lại để sửa giờ/số liệu) — mẻ lọc kết
    thúc luôn phải có sản lượng thật, không cho lưu mẻ rỗng. Sau khi cập nhật dòng, tổng hợp lại
    FilterRecord (xem _sync_filter_aggregate)."""
    require_perm(user, "batch.execute")
    f = db.get(FilterRecord, filter_id)
    if not f:
        raise NotFoundError("Bản ghi lọc không tồn tại.")
    _assert_unlocked(f, *_filter_order_chain(db, f.filter_order_id))
    line = db.get(FilterOrderTank, line_id)
    if not line or line.filter_id != f.filter_id:
        raise NotFoundError("Dòng tank không tồn tại trong bản ghi lọc này.")
    batch_number = (payload.batch_number or "").strip()
    order_number = (payload.order_number or "").strip()
    batch_seq_no = (payload.batch_seq_no or "").strip()
    if not batch_number or not order_number or not batch_seq_no:
        raise DomainError("Nhập Mẻ lọc số, Số mẻ (batch number) và Số lệnh (order number) trước khi kết thúc mẻ lọc.")
    old_v_dich = line.v_dich_hl or 0.0
    new_v_dich = payload.v_dich_hl if payload.v_dich_hl is not None else old_v_dich
    new_bai_khi = payload.nuoc_bai_khi_hl if payload.nuoc_bai_khi_hl is not None else (line.nuoc_bai_khi_hl or 0.0)
    # Mỗi mẻ lọc "kết thúc" đại diện 1 đợt rút dịch thật — Dịch nha lọc = 0 nghĩa là chưa thật
    # sự rút dịch gì, không nên đóng mẻ (dữ liệu rác), nên bắt buộc > 0 mỗi lần kết thúc/sửa.
    if new_v_dich <= 0:
        raise DomainError("Dịch nha lọc (hl) phải lớn hơn 0 mới được kết thúc mẻ lọc.")
    f.batch_number = batch_number
    f.order_number = order_number
    line.batch_seq_no = batch_seq_no
    line.ended_at = payload.ended_at or utcnow()
    if line.tank_type == "bbt":
        source = db.get(FilterRecord, line.source_filter_id) if line.source_filter_id else None
        if source:
            source.on_hand_bbt -= (new_v_dich - old_v_dich)
    else:
        ferment = db.get(FermentRecord, line.ferment_id)
        if ferment:
            ferment.on_hand_cct -= (new_v_dich - old_v_dich)
    line.v_dich_hl = new_v_dich
    line.nuoc_bai_khi_hl = new_bai_khi
    db.flush()
    _sync_filter_aggregate(db, f)
    db.commit(); db.refresh(f)
    return f


@router.post("/filters/{filter_id}/tanks/{line_id}/add-batch")
def add_filter_tank_batch(filter_id: str, line_id: str, db: Session = Depends(get_db),
                          user: User = Depends(get_current_user)):
    """Thêm 1 mẻ kéo dịch MỚI cho CÙNG 1 tank nguồn (tank lên men hoặc BBT lọc lại) đã có
    trong bản ghi lọc này — dùng khi 1 tank nguồn được rút dịch thành nhiều đợt (VD tạm dừng
    giữa chừng, tách phiếu giấy theo đợt). Dòng mới nhân bản nguyên tank nguồn (ferment_id
    hoặc source_bbt_code/source_filter_id/reason) của dòng gốc, chưa có kết quả — chờ "Kết
    thúc" riêng (xem finish_filter_tank). Chỉ cho phép khi dòng MỚI NHẤT của CÙNG tank này đã
    kết thúc (ended_at) — không thể có 2 đợt rút dịch cùng lúc từ 1 tank vật lý. Cũng chặn nếu
    lệnh lọc (filter_order) của dòng này đã bắt đầu chiết (xem filter_order_svc._chiet_started,
    cùng quy tắc với add_filter) — chỉ thêm mẻ được khi lệnh còn Đang lọc. Sau khi thêm,
    tổng hợp lại FilterRecord (xem _sync_filter_aggregate) — ended_at của cả bản ghi tự động
    về rỗng cho tới khi dòng mới này cũng kết thúc."""
    require_perm(user, "batch.execute")
    f = db.get(FilterRecord, filter_id)
    if not f:
        raise NotFoundError("Bản ghi lọc không tồn tại.")
    _assert_unlocked(f, *_filter_order_chain(db, f.filter_order_id))
    line = db.get(FilterOrderTank, line_id)
    if not line or line.filter_id != f.filter_id:
        raise NotFoundError("Dòng tank không tồn tại trong bản ghi lọc này.")
    if filter_order_svc._chiet_started(db, line.filter_order_id):
        raise DomainError("Lệnh lọc này đã bắt đầu chiết — chỉ được thêm mẻ lọc khi lệnh còn ở trạng thái Đang lọc.")
    all_lines = db.execute(select(FilterOrderTank).where(
        FilterOrderTank.filter_id == filter_id)).scalars().all()
    same_tank = [l for l in all_lines if (
        l.tank_type == "cct" and l.ferment_id == line.ferment_id) or (
        l.tank_type == "bbt" and l.source_bbt_code == line.source_bbt_code)]
    latest = max(same_tank, key=lambda l: l.seq)
    if latest.ended_at is None:
        raise DomainError("Mẻ trước của tank này chưa kết thúc — kết thúc trước khi thêm mẻ mới.")
    max_seq = max((l.seq for l in all_lines), default=0)
    new_line = FilterOrderTank(line_id=new_id(), filter_order_id=line.filter_order_id, filter_id=filter_id,
                               tank_type=line.tank_type, ferment_id=line.ferment_id,
                               source_bbt_code=line.source_bbt_code, source_filter_id=line.source_filter_id,
                               reason=line.reason, seq=max_seq + 1)
    db.add(new_line); db.flush()
    _sync_filter_aggregate(db, f)
    db.commit()
    return {"line_id": new_line.line_id}


@router.delete("/filters/{filter_id}/tanks/{line_id}", status_code=204)
def delete_filter_tank_batch(filter_id: str, line_id: str, db: Session = Depends(get_db),
                             user: User = Depends(get_current_user)):
    """Xóa 1 dòng "mẻ" (1 đợt rút dịch riêng — xem add_filter_tank_batch) khỏi bản ghi lọc,
    KHÔNG xóa cả bản ghi lọc (dùng data-delrec/delete_filter cho việc đó). Hoàn tác tồn về
    tank nguồn (ferment.on_hand_cct hoặc source_filter.on_hand_bbt) nếu dòng đã ghi nhận thể
    tích — mirror phần xóa từng dòng trong delete_filter. Chặn nếu đây là dòng CUỐI CÙNG của
    bản ghi (1 mẻ lọc luôn phải có ít nhất 1 tank nguồn) hoặc nếu Chiết đã lấy nhiều hơn mức
    tồn sẽ còn lại sau khi xóa (tránh tồn âm)."""
    require_perm(user, "batch.execute")
    f = db.get(FilterRecord, filter_id)
    if not f:
        raise NotFoundError("Bản ghi lọc không tồn tại.")
    _assert_unlocked(f, *_filter_order_chain(db, f.filter_order_id))
    line = db.get(FilterOrderTank, line_id)
    if not line or line.filter_id != f.filter_id:
        raise NotFoundError("Dòng mẻ không tồn tại trong bản ghi lọc này.")
    all_lines = db.execute(select(FilterOrderTank).where(
        FilterOrderTank.filter_id == filter_id)).scalars().all()
    if len(all_lines) <= 1:
        raise DomainError("Đây là dòng mẻ duy nhất của bản ghi lọc này — xóa cả mẻ lọc (nút Xóa) nếu muốn bỏ hẳn.")
    consumed_bbt = (f.v_beer_hl or 0.0) - (f.on_hand_bbt or 0.0)
    remaining_after = sum((l.v_dich_hl or 0.0) + (l.nuoc_bai_khi_hl or 0.0) for l in all_lines if l.line_id != line_id)
    if consumed_bbt > remaining_after + 1e-6:
        raise DomainError("Không thể xóa — Chiết đã lấy nhiều hơn mức tồn sẽ còn lại sau khi xóa mẻ này.")
    if line.v_dich_hl:
        if line.tank_type == "bbt":
            source = db.get(FilterRecord, line.source_filter_id) if line.source_filter_id else None
            if source:
                source.on_hand_bbt += line.v_dich_hl
        else:
            ferment = db.get(FermentRecord, line.ferment_id)
            if ferment:
                ferment.on_hand_cct += line.v_dich_hl
    db.delete(line)
    db.flush()
    _sync_filter_aggregate(db, f)
    db.commit()


@router.post("/ferments/{ferment_id}/empty-cct")
def empty_ferment_cct(ferment_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Buộc tồn CCT về 0 khi tank vật lý đã cạn thật nhưng số liệu phần mềm còn lệch một
    khoảng nhỏ (hao hụt đo đạc/cặn/foam khiến lọc không bao giờ rút hết theo số liệu, làm lô
    lên men kẹt mãi ở trạng thái "còn tồn") — chỉ cho phép khi phần lệch còn lại không vượt
    ngưỡng cấu hình ở Danh mục (xem services/ops_setting.py), tránh xoá nhầm sai lệch lớn do
    lỗi nhập liệu thật."""
    require_perm(user, "batch.execute")
    f = db.get(FermentRecord, ferment_id)
    if not f:
        raise NotFoundError("Bản ghi lên men không tồn tại.")
    _assert_unlocked(f)
    residual = f.on_hand_cct or 0.0
    if residual <= 0:
        raise DomainError("Tank CCT đã hết tồn — không cần làm rỗng.")
    settings = ops_setting_svc.get_settings(db)
    if residual > settings.empty_cct_tolerance_hl:
        raise DomainError(
            f"Tồn CCT còn {residual:g} hl, vượt ngưỡng cho phép làm rỗng ({settings.empty_cct_tolerance_hl:g} hl) "
            "— kiểm tra lại số liệu lọc trước khi làm rỗng, hoặc chỉnh ngưỡng ở Danh mục nếu chắc chắn đúng.")
    record_audit(db, entity_type="ferment_record", entity_id=f.ferment_id, action="empty_cct", actor=user,
                 before={"on_hand_cct": residual}, after={"on_hand_cct": 0.0})
    f.on_hand_cct = 0.0
    db.commit(); db.refresh(f)
    return f


@router.post("/bbt-tanks/{code}/empty")
def empty_bbt_tank(code: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Buộc tồn CẢ TANK BBT VẬT LÝ về 0 khi tank đã chiết cạn thật nhưng số liệu phần mềm còn
    lệch một khoảng nhỏ (chiết không bao giờ rút hết theo số liệu) — tính theo TANK (cộng dồn
    on_hand_bbt của MỌI mẻ lọc cùng to_bbt, so ngưỡng trên TỔNG, rồi zero từng mẻ), không phải
    theo 1 mẻ lọc cụ thể — vì nhiều mẻ lọc có thể cùng chia sẻ 1 tank vật lý (xem
    filter_order_svc.available_bbt_tanks). Cùng cơ chế ngưỡng dung sai như empty_ferment_cct,
    dùng ngưỡng BBT riêng."""
    require_perm(user, "batch.execute")
    recs = db.execute(select(FilterRecord).where(FilterRecord.to_bbt == code)).scalars().all()
    if not recs:
        raise NotFoundError(f"Không có mẻ lọc nào trong tank BBT {code}.")
    for f in recs:
        _assert_unlocked(f, *_filter_order_chain(db, f.filter_order_id))
    residual = sum(f.on_hand_bbt or 0.0 for f in recs)
    if residual <= 0:
        raise DomainError("Tank BBT đã hết tồn — không cần làm rỗng.")
    settings = ops_setting_svc.get_settings(db)
    if residual > settings.empty_bbt_tolerance_hl:
        raise DomainError(
            f"Tồn BBT còn {residual:g} hl, vượt ngưỡng cho phép làm rỗng ({settings.empty_bbt_tolerance_hl:g} hl) "
            "— kiểm tra lại số liệu chiết trước khi làm rỗng, hoặc chỉnh ngưỡng ở Danh mục nếu chắc chắn đúng.")
    record_audit(db, entity_type="bbt_tank", entity_id=code, action="empty_bbt", actor=user,
                 before={"on_hand_bbt": residual}, after={"on_hand_bbt": 0.0})
    for f in recs:
        f.on_hand_bbt = 0.0
    db.commit()
    return {"to_bbt": code, "on_hand_bbt": 0.0}


# ===== Nguyên liệu dùng cho 1 mẻ lọc cụ thể =====
@router.get("/filters/{filter_id}/materials")
def list_filter_materials(filter_id: str, db: Session = Depends(get_db)):
    rows = db.execute(select(FilterMaterialUsage).where(FilterMaterialUsage.filter_id == filter_id)
                      .order_by(FilterMaterialUsage.created_at)).scalars().all()
    return rows


@router.post("/filters/{filter_id}/materials", status_code=201)
def add_filter_material(filter_id: str, payload: FilterMaterialUsageIn, db: Session = Depends(get_db),
                        user: User = Depends(get_current_user)):
    """Gán nguyên liệu (VD: bột trợ lọc) cho 1 mẻ lọc — ưu tiên lot_id (lô thật trong Kho
    phân xưởng): trừ tồn kho thật qua warehouse_svc.issue(), ghi lại movement_id để hoàn kho
    khi xóa. receipt_id/tên tự do chỉ còn là lối dự phòng cho nguyên liệu chưa có trong Kho
    NVL. Mirror add_brew_material."""
    require_perm(user, "batch.execute")
    f = db.get(FilterRecord, filter_id)
    if not f:
        raise NotFoundError("Bản ghi lọc không tồn tại.")
    _assert_unlocked(f, *_filter_order_chain(db, f.filter_order_id))
    data = payload.model_dump()
    lot_id = data.pop("lot_id", None)
    if lot_id:
        lot = db.get(MaterialLot, lot_id)
        if not lot:
            raise NotFoundError("Lô nguyên liệu không tồn tại.")
        if not warehouse_svc._is_workshop_location(lot.location):
            raise DomainError(f"Lô {lot.lot_code} không ở Kho phân xưởng — chỉ được dùng nguyên liệu từ Kho phân xưởng cho mẻ lọc.")
        material = db.get(Material, lot.material_id) if lot.material_id else None
        data["material_name"] = material.name if material else lot.lot_code
        data["lot_pm"] = lot.lot_code
        data["lot_date"] = lot.created_at
        data["fifo_ok"] = warehouse_svc.is_oldest_workshop_lot(db, lot.material_id, lot_id)
        data["uom"] = lot.uom
        result = warehouse_svc.issue(db, lot_id, data["quantity"], user, mode="tu_do",
                                     reason=f"Dùng cho mẻ lọc {f.filter_code}", ref_doc=f.filter_code)
        data["lot_id"] = lot_id
        data["movement_id"] = result["movement_id"]
    else:
        receipt_id = data.get("receipt_id")
        if receipt_id:
            receipt = db.get(MaterialReceipt, receipt_id)
            if not receipt:
                raise NotFoundError("Bản ghi nguyên liệu không tồn tại.")
            data["material_name"] = data.get("material_name") or receipt.material_name
            data["lot_pm"] = data.get("lot_pm") or receipt.lot_pm
        if not data.get("material_name"):
            raise DomainError("Chọn nguyên liệu hoặc nhập tên nguyên liệu.")
    u = FilterMaterialUsage(usage_id=new_id(), filter_id=filter_id, **data)
    db.add(u)
    f.has_nvl = True
    if lot_id:
        genealogy.add_edge(db, from_type="lot", from_id=lot_id, to_type="filter", to_id=filter_id,
                           relation="consume", quantity=data["quantity"], uom=data.get("uom"))
    db.commit(); db.refresh(u)
    return u


@router.put("/filters/{filter_id}/materials/{usage_id}")
def update_filter_material(filter_id: str, usage_id: str, payload: FilterMaterialUsageIn,
                           db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    require_perm(user, "batch.execute")
    u = db.get(FilterMaterialUsage, usage_id)
    if not u or u.filter_id != filter_id:
        raise NotFoundError("Dòng nguyên liệu không tồn tại.")
    f = db.get(FilterRecord, filter_id)
    _assert_unlocked(f, *_filter_order_chain(db, f.filter_order_id if f else None))
    data = payload.model_dump()
    if not data.get("material_name"):
        raise DomainError("Chọn nguyên liệu hoặc nhập tên nguyên liệu.")
    new_qty = data.get("quantity")
    if u.lot_id and u.movement_id and new_qty != u.quantity:
        warehouse_svc.undo_issue(db, u.movement_id, user)
        f = db.get(FilterRecord, filter_id)
        lot = db.get(MaterialLot, u.lot_id)
        if lot:
            u.fifo_ok = warehouse_svc.is_oldest_workshop_lot(db, lot.material_id, u.lot_id)
        result = warehouse_svc.issue(db, u.lot_id, new_qty, user, mode="tu_do",
                                     reason=f"Dùng cho mẻ lọc {f.filter_code} (sửa số lượng)", ref_doc=f.filter_code)
        u.movement_id = result["movement_id"]
    for k, v in data.items():
        if k not in ("receipt_id", "lot_id") or v:
            setattr(u, k, v)
    db.commit(); db.refresh(u)
    return u


@router.delete("/filters/{filter_id}/materials/{usage_id}", status_code=204)
def delete_filter_material(filter_id: str, usage_id: str, db: Session = Depends(get_db),
                           user: User = Depends(get_current_user)):
    require_perm(user, "batch.execute")
    u = db.get(FilterMaterialUsage, usage_id)
    if not u or u.filter_id != filter_id:
        raise NotFoundError("Dòng nguyên liệu không tồn tại.")
    f = db.get(FilterRecord, filter_id)
    _assert_unlocked(f, *_filter_order_chain(db, f.filter_order_id if f else None))
    if u.movement_id:
        warehouse_svc.undo_issue(db, u.movement_id, user, strict=False)
    db.delete(u)
    db.commit()


@router.delete("/filters/{filter_id}", status_code=204)
def delete_filter(filter_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    require_perm(user, "batch.execute")
    f = db.get(FilterRecord, filter_id)
    if not f:
        raise NotFoundError("Bản ghi lọc không tồn tại.")
    _assert_unlocked(f, *_filter_order_chain(db, f.filter_order_id))
    if db.execute(select(BottleRecord).where(BottleRecord.filter_id == filter_id)).first():
        raise DomainError("Đã có bản ghi chiết lấy từ lô lọc này — xóa bản ghi chiết trước khi xóa lọc.")
    for u in db.execute(select(FilterMaterialUsage).where(FilterMaterialUsage.filter_id == filter_id)).scalars().all():
        if u.movement_id:
            warehouse_svc.undo_issue(db, u.movement_id, user, strict=False)
        db.delete(u)
    lines = db.execute(select(FilterOrderTank).where(FilterOrderTank.filter_id == filter_id)).scalars().all()
    for line in lines:
        if line.v_dich_hl:
            if line.tank_type == "bbt":
                source = db.get(FilterRecord, line.source_filter_id) if line.source_filter_id else None
                if source:
                    source.on_hand_bbt += line.v_dich_hl
            else:
                ferment = db.get(FermentRecord, line.ferment_id)
                if ferment:
                    ferment.on_hand_cct += line.v_dich_hl
        # Dòng nhân bản riêng của bản ghi này — xóa hẳn (không phải template dùng chung cấp
        # lệnh), tank BBT của bản ghi này lại "trống" vì không còn FilterRecord nào dùng nữa.
        db.delete(line)
    for r in db.execute(select(QualityResult).where(QualityResult.scope_type == "filter", QualityResult.scope_id == f.filter_code)).scalars().all():
        db.delete(r)
    genealogy.delete_edges_for(db, "filter", filter_id)
    db.delete(f)
    db.commit()


# ===== Thông tin chiết =====
@router.get("/bottles")
def list_bottles(years: list[int] = Query(None), db: Session = Depends(get_db)):
    years = _years_or_current(years)
    rows = db.execute(select(BottleRecord).where(BottleRecord.bottle_year.in_(years))
                      .order_by(BottleRecord.bottle_date.desc())).scalars().all()
    products = {p.product_id: p for p in db.execute(select(Product)).scalars().all()}
    finished_products = {fp.finished_product_id: fp for fp in db.execute(select(FinishedProduct)).scalars().all()}
    source_filters = {f.filter_id: f for f in db.execute(select(FilterRecord)).scalars().all()}
    out = []
    for b in rows:
        total = b.ca1 + b.ca2 + b.ca3
        # Chiết không tiêu thụ NVL (khác Nấu/Lọc) — chỉ 1 chốt chỉ tiêu Thành phẩm (đã gộp
        # "Sau chiết" vào đây, xem nút "Thành phẩm" app.js), đủ chỉ tiêu mới xanh dương.
        tp_ok = _stage_ok(db, "thanh_pham", "bottle", f"{b.bottle_code}__thanh_pham", b.product_id,
                          finished_product_id=b.finished_product_id, beer_type_id=b.beer_type_id)
        color = "blue" if tp_ok else "red"
        exec_status = _exec_status(b.ended_at)
        source_filter = source_filters.get(b.filter_id)
        out.append({"bottle_id": b.bottle_id, "bottle_code": b.bottle_code, "filter_code": b.filter_code,
                    "filter_id": b.filter_id,
                    "source_filter_on_hand_bbt": source_filter.on_hand_bbt if source_filter else None,
                    "bottle_date": b.bottle_date, "beer_type": b.beer_type, "beer_type_id": b.beer_type_id, "lot_no": b.lot_no,
                    "product_id": b.product_id, "product_code": products[b.product_id].code if b.product_id in products else None,
                    "finished_product_id": b.finished_product_id,
                    "finished_product_code": finished_products[b.finished_product_id].code if b.finished_product_id in finished_products else None,
                    "finished_product_name": finished_products[b.finished_product_id].name if b.finished_product_id in finished_products else None,
                    "v_cap_chiet_hl": b.v_cap_chiet_hl, "from_bbt": b.from_bbt, "line": b.line,
                    "ca1": b.ca1, "ca2": b.ca2, "ca3": b.ca3, "total": round(total, 1),
                    "stocked": b.stocked, "approved": b.approved, "approved_by": b.approved_by,
                    "approved_at": b.approved_at, "note": b.note, "color": color,
                    "ended_at": b.ended_at, "exec_status": exec_status, "exec_status_label": EXEC_STATUS[exec_status],
                    "locked": b.locked, "locked_by": b.locked_by, "quality_status": b.quality_status})
    return out


@router.post("/bottles", status_code=201)
def add_bottle(payload: BottleIn, db: Session = Depends(get_db),
               user: User = Depends(get_current_user)):
    """product_id (loại bia) được kế từ FilterRecord đang chứa trong tank BBT nguồn
    (from_bbt) — cùng loại bia đã lọc vào tank đó, không cần chọn lại."""
    require_perm(user, "batch.execute")
    data = payload.model_dump()
    if not data.get("lot_no"):
        data["lot_no"] = _next_lot_number(db, BottleRecord, "lot_no")
    source_filter = None
    if data.get("from_bbt"):
        bbt_status = next((t for t in filter_order_svc.available_bbt_tanks(db) if t["to_bbt"] == data["from_bbt"]), None)
        if not bbt_status or not bbt_status["eligible_for_chiet"]:
            raise DomainError(
                f"Tank BBT {data['from_bbt']} chưa đủ điều kiện chiết — phải đã lọc xong, "
                "được KCS duyệt hết, và không đang bị chọn làm nguồn lọc lại.")
        source_filter = db.execute(
            select(FilterRecord).where(FilterRecord.to_bbt == data["from_bbt"])
            .order_by(FilterRecord.filter_date.desc())
        ).scalars().first()
        if source_filter:
            _assert_unlocked(source_filter, *_filter_order_chain(db, source_filter.filter_order_id))
            data["product_id"] = source_filter.product_id
            data["filter_id"] = source_filter.filter_id
            data["filter_code"] = source_filter.filter_code
            # Loại bia không nhập tay — kế thừa từ FilterRecord nguồn (dùng để tra chỉ
            # tiêu Chiết, xem approve_bottle). Nếu chưa suy ra được thì giữ nguyên giá
            # trị client gửi lên (tương thích ngược), rồi mới dùng beer_type của filter
            # nguồn làm phương án dự phòng.
            data["beer_type_id"] = source_filter.beer_type_id
            if source_filter.beer_type_id:
                beer_type = db.get(BeerType, source_filter.beer_type_id)
                if beer_type:
                    data["beer_type"] = beer_type.name
            if not data.get("beer_type") and source_filter.beer_type:
                data["beer_type"] = source_filter.beer_type
    if not data.get("beer_type"):
        data["beer_type"] = ""
    bottle_year = (data.get("bottle_date") or utcnow()).year
    if db.execute(select(BottleRecord).where(BottleRecord.bottle_code == data["bottle_code"],
                  BottleRecord.bottle_year == bottle_year)).scalar_one_or_none():
        raise DomainError(f"Mã chiết '{data['bottle_code']}' đã tồn tại trong năm {bottle_year}.")
    data["bottle_year"] = bottle_year
    b = BottleRecord(bottle_id=new_id(), **data)
    db.add(b)
    if source_filter:
        genealogy.add_edge(db, from_type="filter", from_id=source_filter.filter_id, to_type="bottle",
                           to_id=b.bottle_id, relation="chiết")
    db.commit(); db.refresh(b)
    return b


@router.delete("/bottles/{bottle_id}", status_code=204)
def delete_bottle(bottle_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    require_perm(user, "batch.execute")
    b = db.get(BottleRecord, bottle_id)
    if not b:
        raise NotFoundError("Bản ghi chiết không tồn tại.")
    _assert_unlocked(b)
    if b.approved:
        # b.approved chỉ đánh dấu ĐÃ TỪNG nhập kho — không có nghĩa vỉ/keg đó vẫn còn tồn
        # (đã có thể xuất/phân rã/xóa hết). Tra thẳng genealogy để biết còn đơn vị nào thật
        # sự tồn tại không, tránh chặn nhầm khi kho đã trống.
        unit_ids = [row[0] for row in db.execute(select(GenealogyEdge.to_id).where(
            GenealogyEdge.from_type == "bottle", GenealogyEdge.from_id == bottle_id,
            GenealogyEdge.to_type == "finished_goods_unit")).all()]
        remaining = db.execute(select(FinishedGoodsUnit.unit_id).where(
            FinishedGoodsUnit.unit_id.in_(unit_ids))).first() if unit_ids else None
        if remaining:
            raise DomainError("Bản ghi chiết này đã được duyệt và còn vỉ/keg trong kho thành phẩm — xóa các vỉ/keg đó trước khi xóa bản ghi chiết.")
    if b.filter_id:
        f = db.get(FilterRecord, b.filter_id)
        if f:
            f.on_hand_bbt += b.v_cap_chiet_hl
    for r in db.execute(select(QualityResult).where(QualityResult.scope_type == "bottle",
                        QualityResult.scope_id.in_([f"{b.bottle_code}__chiet", f"{b.bottle_code}__thanh_pham"]))).scalars().all():
        db.delete(r)
    for u in db.execute(select(BottleMaterialUsage).where(BottleMaterialUsage.bottle_id == bottle_id)).scalars().all():
        if u.movement_id:
            warehouse_svc.undo_issue(db, u.movement_id, user, strict=False)
        db.delete(u)
    genealogy.delete_edges_for(db, "bottle", bottle_id)
    db.delete(b)
    db.commit()


# ===== Nguyên liệu dùng cho 1 mẻ chiết cụ thể (VD: CO2, hóa chất vệ sinh) =====
@router.get("/bottles/{bottle_id}/materials")
def list_bottle_materials(bottle_id: str, db: Session = Depends(get_db)):
    rows = db.execute(select(BottleMaterialUsage).where(BottleMaterialUsage.bottle_id == bottle_id)
                      .order_by(BottleMaterialUsage.created_at)).scalars().all()
    return rows


@router.post("/bottles/{bottle_id}/materials", status_code=201)
def add_bottle_material(bottle_id: str, payload: BottleMaterialUsageIn, db: Session = Depends(get_db),
                        user: User = Depends(get_current_user)):
    """Gán nguyên liệu cho 1 mẻ chiết — trừ tồn kho thật qua warehouse_svc.issue(), ghi lại
    movement_id để hoàn kho khi xóa. Mirror add_filter_material (Chiết trước đây không tiêu
    thụ NVL — bổ sung cùng cơ chế + FIFO snapshot như Nấu/Lọc)."""
    require_perm(user, "batch.execute")
    b = db.get(BottleRecord, bottle_id)
    if not b:
        raise NotFoundError("Bản ghi chiết không tồn tại.")
    _assert_unlocked(b)
    data = payload.model_dump()
    lot_id = data.pop("lot_id", None)
    if lot_id:
        lot = db.get(MaterialLot, lot_id)
        if not lot:
            raise NotFoundError("Lô nguyên liệu không tồn tại.")
        if not warehouse_svc._is_workshop_location(lot.location):
            raise DomainError(f"Lô {lot.lot_code} không ở Kho phân xưởng — chỉ được dùng nguyên liệu từ Kho phân xưởng cho mẻ chiết.")
        material = db.get(Material, lot.material_id) if lot.material_id else None
        data["material_name"] = material.name if material else lot.lot_code
        data["lot_pm"] = lot.lot_code
        data["lot_date"] = lot.created_at
        data["fifo_ok"] = warehouse_svc.is_oldest_workshop_lot(db, lot.material_id, lot_id)
        data["uom"] = lot.uom
        result = warehouse_svc.issue(db, lot_id, data["quantity"], user, mode="tu_do",
                                     reason=f"Dùng cho mẻ chiết {b.bottle_code}", ref_doc=b.bottle_code)
        data["lot_id"] = lot_id
        data["movement_id"] = result["movement_id"]
    elif not data.get("material_name"):
        raise DomainError("Chọn nguyên liệu hoặc nhập tên nguyên liệu.")
    u = BottleMaterialUsage(usage_id=new_id(), bottle_id=bottle_id, **data)
    db.add(u)
    b.has_nvl = True
    if lot_id:
        genealogy.add_edge(db, from_type="lot", from_id=lot_id, to_type="bottle", to_id=bottle_id,
                           relation="consume", quantity=data["quantity"], uom=data.get("uom"))
    db.commit(); db.refresh(u)
    return u


@router.put("/bottles/{bottle_id}/materials/{usage_id}")
def update_bottle_material(bottle_id: str, usage_id: str, payload: BottleMaterialUsageIn,
                           db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    require_perm(user, "batch.execute")
    u = db.get(BottleMaterialUsage, usage_id)
    if not u or u.bottle_id != bottle_id:
        raise NotFoundError("Dòng nguyên liệu không tồn tại.")
    b = db.get(BottleRecord, bottle_id)
    _assert_unlocked(b)
    data = payload.model_dump()
    if not data.get("material_name"):
        raise DomainError("Chọn nguyên liệu hoặc nhập tên nguyên liệu.")
    new_qty = data.get("quantity")
    if u.lot_id and u.movement_id and new_qty != u.quantity:
        warehouse_svc.undo_issue(db, u.movement_id, user)
        lot = db.get(MaterialLot, u.lot_id)
        if lot:
            u.fifo_ok = warehouse_svc.is_oldest_workshop_lot(db, lot.material_id, u.lot_id)
        result = warehouse_svc.issue(db, u.lot_id, new_qty, user, mode="tu_do",
                                     reason=f"Dùng cho mẻ chiết {b.bottle_code} (sửa số lượng)", ref_doc=b.bottle_code)
        u.movement_id = result["movement_id"]
    for k, v in data.items():
        if k != "lot_id" or v:
            setattr(u, k, v)
    db.commit(); db.refresh(u)
    return u


@router.delete("/bottles/{bottle_id}/materials/{usage_id}", status_code=204)
def delete_bottle_material(bottle_id: str, usage_id: str, db: Session = Depends(get_db),
                           user: User = Depends(get_current_user)):
    require_perm(user, "batch.execute")
    u = db.get(BottleMaterialUsage, usage_id)
    if not u or u.bottle_id != bottle_id:
        raise NotFoundError("Dòng nguyên liệu không tồn tại.")
    _assert_unlocked(db.get(BottleRecord, bottle_id))
    if u.movement_id:
        warehouse_svc.undo_issue(db, u.movement_id, user, strict=False)
    db.delete(u)
    db.commit()


@router.post("/bottles/{bottle_id}/finish")
def finish_bottle(bottle_id: str, payload: FinishBottleIn = FinishBottleIn(), db: Session = Depends(get_db),
                  user: User = Depends(get_current_user)):
    """Vận hành chọn tay giờ kết thúc chiết + V cấp chiết/hl + Ca 1/2/3 (chưa biết lúc tạo,
    điền ở đây) — gọi lại được nhiều lần để sửa nếu bấm nhầm. on_hand_bbt của tank BBT nguồn
    điều chỉnh theo CHÊNH LỆCH giữa V cấp chiết cũ/mới (mirror finish_filter_tank). Nếu mẻ
    ĐÃ DUYỆT (approve_bottle đã nhập kho theo Ca cũ), sửa lại Ca 1/2/3 sẽ điều chỉnh THEO
    CHÊNH LỆCH số lượng thành phẩm đã tạo trong kho (xem wms_svc.adjust_bottle_finish_stock)
    — trước đây sửa Ca sau khi duyệt không cập nhật lại tồn kho, gây lệch giữa sản lượng
    hiển thị và số vỉ/keg thật trong kho."""
    require_perm(user, "batch.execute")
    b = db.get(BottleRecord, bottle_id)
    if not b:
        raise NotFoundError("Bản ghi chiết không tồn tại.")
    _assert_unlocked(b)
    b.ended_at = payload.ended_at or utcnow()
    if payload.v_cap_chiet_hl is not None:
        old_v = b.v_cap_chiet_hl or 0.0
        if b.filter_id:
            f = db.get(FilterRecord, b.filter_id)
            if f:
                f.on_hand_bbt -= (payload.v_cap_chiet_hl - old_v)
        b.v_cap_chiet_hl = payload.v_cap_chiet_hl
    old_total = b.ca1 + b.ca2 + b.ca3
    if payload.ca1 is not None:
        b.ca1 = payload.ca1
    if payload.ca2 is not None:
        b.ca2 = payload.ca2
    if payload.ca3 is not None:
        b.ca3 = payload.ca3
    new_total = b.ca1 + b.ca2 + b.ca3
    if b.approved and new_total != old_total:
        finished_product = db.get(FinishedProduct, b.finished_product_id) if b.finished_product_id else None
        pack_size = finished_product.pack_size if finished_product else 24
        unit_type = finished_product.unit_type if finished_product else "vi"
        product_name = finished_product.code if finished_product else b.beer_type
        # delta Ca (vỉ) -> nhân pack_size để ra delta LON, mirror cách quy đổi ở approve_bottle.
        wms_svc.adjust_bottle_finish_stock(
            db, finished_product_id=b.finished_product_id, product_name=product_name,
            lot_code=b.lot_no or b.bottle_code, unit_type=unit_type, pack_size=pack_size,
            delta_total=(new_total - old_total) * pack_size, bottle_id=bottle_id, actor=user)
    db.commit(); db.refresh(b)
    return b


@router.post("/bottles/{bottle_id}/approve")
def approve_bottle(bottle_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Giám đốc/Phó GĐ Sản xuất - Kỹ thuật duyệt lô chiết nhập kho thành phẩm — sau khi duyệt,
    hàng được tự động nhập kho thành phẩm theo vỉ/keg (không còn pallet, xem
    services/wms.py::_create_units — mỗi dòng đúng 1 vỉ/keg, dòng cuối có thể lẻ), đánh dấu
    b.stocked. Yêu cầu đã khai báo đủ chỉ tiêu thành phẩm bắt buộc (KCS đã nhập/khóa); chỉ tiêu
    FAIL (vượt giới hạn) không còn chặn duyệt, chỉ cảnh báo (qc_has_fail). Quyền duyệt tách khỏi
    quality.release (KCS) theo đúng sơ đồ tổ chức thật: KCS nhập/khóa chỉ tiêu, còn quyết định
    cho nhập kho thành phẩm hay không thuộc Giám đốc/Phó GĐ Sản xuất."""
    require_perm(user, "production.release_to_wms")
    b = db.get(BottleRecord, bottle_id)
    if not b:
        raise NotFoundError("Bản ghi chiết không tồn tại.")
    _assert_unlocked(b)
    if b.approved:
        raise DomainError("Bản ghi chiết này đã được duyệt.")
    status = qc_catalog.stage_qc_status(db, "thanh_pham", "bottle", f"{b.bottle_code}__thanh_pham",
                                        finished_product_id=b.finished_product_id, beer_type_id=b.beer_type_id)
    if status["pending"]:
        raise DomainError(f"Còn thiếu chỉ tiêu bắt buộc (thành phẩm): {', '.join(status['pending'])}.")
    # Ca 1/2/3 tính theo VỈ/KEG (đơn vị đóng gói cuối cùng vận hành đếm được ở cuối line), KHÔNG
    # phải theo lon rời — 1 vỉ = pack_size lon (khai báo ở Danh mục Sản phẩm). _create_units
    # nhận "total" theo LON (chia cho pack_size ra số vỉ, mirror Nhập kho thủ công) nên phải
    # nhân ca_total (vỉ) với pack_size trước khi gọi, để n dòng sinh ra ĐÚNG BẰNG ca_total vỉ.
    ca_total = b.ca1 + b.ca2 + b.ca3
    if ca_total <= 0:
        raise DomainError("Chưa nhập sản lượng (SL ca 1/2/3) — không thể duyệt xuất kho thành phẩm.")
    finished_product = db.get(FinishedProduct, b.finished_product_id) if b.finished_product_id else None
    pack_size = finished_product.pack_size if finished_product else 24
    unit_type = finished_product.unit_type if finished_product else "vi"
    product_name = finished_product.code if finished_product else b.beer_type
    units = wms_svc._create_units(db, {
        "finished_product_id": b.finished_product_id, "product_name": product_name,
        "lot_code": b.lot_no or b.bottle_code, "total": ca_total * pack_size, "pack_size": pack_size,
        "unit_type": unit_type,
    }, created_by=user.username, actor=user)
    for u in units:
        genealogy.add_edge(db, from_type="bottle", from_id=bottle_id, to_type="finished_goods_unit",
                           to_id=u.unit_id, relation="nhập kho", quantity=u.quantity, uom=u.unit_type)
    b.approved = True
    b.approved_by = user.username
    b.approved_at = utcnow()
    b.stocked = True
    db.commit()
    # count=ca_total (KHÔNG dùng len(units)) — _create_units giờ luôn trả về 1 dòng/lô
    # (xem docs/WMS-LOT-LEVEL-REDESIGN.md), ca_total mới là số vỉ/keg thật đã nhập kho.
    return {"bottle_id": bottle_id, "approved": True, "unit_type": unit_type, "count": ca_total,
            "unit_codes": [u.unit_code for u in units], "qc_has_fail": status["has_fail"]}


@router.post("/bottles/{bottle_id}/lock-lot")
def lock_bottle_lot(bottle_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """KCS khóa Chiết — công đoạn cuối trong chuỗi khóa lô. Yêu cầu Lọc (mẻ lọc nguồn) đã
    khóa trước, đã Duyệt KCS và đã kết thúc chiết (xem services/lot_lock.py)."""
    require_perm(user, "quality.release")
    locked = lot_lock_svc.lock_bottle(db, bottle_id, user)
    return {"bottle_id": locked.bottle_id, "locked": True}


@router.post("/bottles/{bottle_id}/unlock-lot")
def unlock_bottle_lot(bottle_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Chỉ admin được mở khóa Chiết — bước đầu tiên của chuỗi mở khóa ngược (Chiết → Lọc →
    Lên men → Nấu)."""
    if user.role != Role.ADMIN.value:
        raise PermissionError_("Chỉ admin được mở khóa lô.")
    unlocked = lot_lock_svc.unlock_bottle(db, bottle_id, user)
    return {"bottle_id": unlocked.bottle_id, "locked": False}


# ===== Chỉ tiêu theo công đoạn sản xuất (mẻ nấu/lên men chính-phụ/lọc/chiết/thành phẩm) =====
@router.get("/qc-status")
def brewing_qc_status(stage: str, scope_type: str, scope_id: str, product_id: str = None,
                      finished_product_id: str = None, beer_type_id: str = None, db: Session = Depends(get_db)):
    return qc_catalog.stage_qc_status(db, stage, scope_type, scope_id, product_id,
                                      finished_product_id, beer_type_id)


@router.post("/qc-samples", status_code=201)
def add_qc_sample(payload: QcSampleIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Ghi 1 lần lấy mẫu (nhiều chỉ tiêu cùng lúc) cho CT chính/CT phụ lên men — xem
    qc_catalog.record_qc_sample. LUÔN thêm bản ghi mới, không ghi đè lần trước."""
    require_perm(user, "batch.execute")
    _assert_stage_scope_unlocked(db, payload.scope_type, payload.scope_id)
    return qc_catalog.record_qc_sample(db, payload.stage, payload.scope_type, payload.scope_id,
                                       payload.sampled_at, [r.model_dump() for r in payload.results], user)


@router.get("/qc-samples")
def get_qc_samples(scope_type: str, scope_id: str, db: Session = Depends(get_db)):
    """Lịch sử các lần lấy mẫu (mới nhất trước) cho 1 scope — xem qc_catalog.list_qc_samples."""
    return {"items": qc_catalog.list_qc_samples(db, scope_type, scope_id)}


@router.get("/lot-record")
def get_lot_record(code: str, db: Session = Depends(get_db)):
    """Hồ sơ điện tử theo lô — tổng hợp NVL/mẻ nấu/lên men/lọc/chiết cho 1 lô, tra theo
    bất kỳ mã nào (mã nấu/lô LM/mã lọc/mã chiết/số lô bia). Xem services/lot_record.py."""
    return lot_record_svc.build_lot_record(db, code)


@router.get("/brew-forward-record")
def get_brew_forward_record(brew_id: str, db: Session = Depends(get_db)):
    """Truy xuôi theo nấu — từ 1 lô nấu đã chọn, lấy xuôi chiều lên men/lọc/chiết liên quan,
    dừng ở chiết (không đi tiếp thành phẩm/pallet/xuất kho). Xem services/lot_record.py."""
    return lot_record_svc.build_brew_forward_record(db, brew_id)


@router.post("/qc-results", status_code=201)
def add_stage_qc_result(payload: StageQcResultIn, db: Session = Depends(get_db),
                        user: User = Depends(get_current_user)):
    require_perm(user, "batch.execute")
    data = payload.model_dump()
    stage, scope_type, scope_id = data.pop("stage"), data.pop("scope_type"), data.pop("scope_id")
    _assert_stage_scope_unlocked(db, scope_type, scope_id)
    return qc_catalog.record_stage_result(db, stage, scope_type, scope_id, data, user)


# ===== Chỉ tiêu phân tích =====
@router.get("/indicators")
def list_indicators(stage: str, scope_code: str, db: Session = Depends(get_db)):
    return db.execute(select(StageIndicator).where(
        StageIndicator.stage == stage, StageIndicator.scope_code == scope_code)
        .order_by(StageIndicator.name)).scalars().all()


@router.post("/indicators", status_code=201)
def add_indicator(payload: StageIndicatorIn, db: Session = Depends(get_db),
                  user: User = Depends(get_current_user)):
    # đánh dấu công đoạn đã có chỉ tiêu
    if payload.stage == "loc":
        rec = db.execute(select(FilterRecord).where(FilterRecord.filter_code == payload.scope_code)).scalar_one_or_none()
        if rec:
            _assert_unlocked(rec, *_filter_order_chain(db, rec.filter_order_id))
            rec.has_indicators = True
    elif payload.stage == "chiet":
        rec = db.execute(select(BottleRecord).where(BottleRecord.bottle_code == payload.scope_code)).scalar_one_or_none()
        if rec:
            _assert_unlocked(rec)
            rec.has_indicators = True
    ind = StageIndicator(indicator_id=new_id(), analyst=user.username, updated_at=utcnow(),
                         **payload.model_dump())
    db.add(ind)
    db.commit(); db.refresh(ind)
    return ind


# ===== Cảnh báo chỉ tiêu chất lượng (theo tháng/năm) =====
@router.get("/alerts")
def alerts(month: int = None, year: int = None, db: Session = Depends(get_db)):
    from ..services import derived
    return derived.brewing_alerts(db, month, year)
