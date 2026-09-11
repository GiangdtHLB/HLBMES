"""Lệnh nấu (BrewOrder) và chỉ tiêu chất lượng theo công đoạn (QC — dùng chung, kể cả bởi
pipeline "Mẻ sản xuất" mới qua scope_type="batch"/"batch_tank"/"batch_filter_lot"/
"batch_pack_lot").

Trước đây file này còn chứa toàn bộ luồng "Nấu-Lọc-Chiết" chi tiết theo công đoạn (nguyên
liệu/nấu/lên men/lọc/chiết) — đã xóa hoàn toàn, thay bằng pipeline "Mẻ sản xuất"
(models/batch_pipeline.py, routers/batch_pipeline.py)."""


from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..database import get_db
from ..errors import DomainError
from ..models.batch_pipeline import BatchFilterLot, BatchPackLot, BatchTank
from ..models.batches import BatchExecution
from ..models.brewing import BrewOrder
from ..schemas import BrewOrderIn, QcSampleIn, StageQcResultIn
from ..security import User, get_current_user, require_any_perm, require_perm
from ..services import batch_pipeline as batch_pipeline_svc
from ..services import brew_order as brew_order_svc
from ..services.brew_order import _assert_unlocked
from ..services import qc_catalog

# Mọi route yêu cầu đăng nhập (an toàn mặc định); thao tác ghi thêm require_perm bên dưới.
router = APIRouter(prefix="/api/brewing", tags=["brewing"],
                   dependencies=[Depends(get_current_user)])


def _assert_stage_scope_unlocked(db, scope_type: str, scope_id: str) -> None:
    """Resolve scope_type/scope_id (quy ước dùng bởi qc_catalog, xem data-stageqc ở app.js)
    về đúng bản ghi để kiểm tra khóa trước khi ghi chỉ tiêu/kết quả QC. Chỉ còn các scope
    của pipeline "Mẻ sản xuất" (batch/batch_tank/batch_filter_lot/batch_pack_lot) — các scope
    của module Nấu-Lọc-Chiết cũ (brew_batch/brew/ferment/filter/bottle) đã bị xóa cùng module."""
    if scope_type == "batch":
        b = db.get(BatchExecution, scope_id)
        if b and b.ebr_locked:
            raise DomainError("Bản ghi đã bị khóa — không thể sửa.")
    elif scope_type == "batch_tank":
        t = db.get(BatchTank, scope_id.split("__")[0])
        batch_pipeline_svc._assert_unlocked(t)
    elif scope_type == "batch_filter_lot":
        batch_pipeline_svc._assert_unlocked(db.get(BatchFilterLot, scope_id))
    elif scope_type == "batch_pack_lot":
        batch_pipeline_svc._assert_unlocked(db.get(BatchPackLot, scope_id))


# ===== Lệnh nấu (Brew Production Order) =====
@router.get("/orders")
def list_brew_orders(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return brew_order_svc.list_orders(db)


@router.get("/orders/bom-preview")
def preview_brew_order_bom(recipe_version_id: str = None, planned_batch_count: int = 1, planned_volume_hl: float = 0.0,
                           db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Xem trước bảng định mức NVL (tự nạp từ Công thức) + tồn kho hiện tại — TRƯỚC khi tạo
    lệnh nấu thật, để biết ngay có đủ NVL hay không (nút "Xem NVL" ở form Tạo Lệnh nấu). Cũng
    dùng làm gợi ý NVL/mẻ trong modal "+ NVL" khi lệnh nấu chưa có định mức riêng từng dòng
    (openBrewMaterialsModal) — người thao tác mẻ (batch.execute) không nhất thiết có quyền
    order.create nên chấp nhận cả 2 quyền, không chỉ order.create. Nhận thẳng recipe_version_id
    đã chọn (1 dịch bia có đúng 1 Recipe, nhiều RecipeVersion — chọn 1 version effective, xem
    services/recipes.py), không tự suy ra công thức từ product_id."""
    require_any_perm(user, ["order.create", "batch.execute"])
    if not recipe_version_id:
        raise DomainError("Chọn công thức trước khi xem định mức NVL.")
    return brew_order_svc.preview_bom_lines_from_recipe_version(db, recipe_version_id, planned_batch_count, planned_volume_hl)


@router.post("/orders", status_code=201)
def create_brew_order(payload: BrewOrderIn, db: Session = Depends(get_db),
                      user: User = Depends(get_current_user)):
    require_perm(user, "order.create")
    order = brew_order_svc.create_order(db, payload.model_dump(), user)
    return {"brew_order_id": order.brew_order_id, "order_code": order.order_code}


@router.get("/orders/{brew_order_id}")
def get_brew_order(brew_order_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return brew_order_svc.get_order(db, brew_order_id)


@router.put("/orders/{brew_order_id}")
def update_brew_order(brew_order_id: str, payload: BrewOrderIn, db: Session = Depends(get_db),
                      user: User = Depends(get_current_user)):
    require_perm(user, "order.create")
    _assert_unlocked(db.get(BrewOrder, brew_order_id))
    order = brew_order_svc.update_order(db, brew_order_id, payload.model_dump(), user)
    return {"brew_order_id": order.brew_order_id, "order_code": order.order_code}


@router.delete("/orders/{brew_order_id}", status_code=204)
def delete_brew_order(brew_order_id: str, db: Session = Depends(get_db),
                      user: User = Depends(get_current_user)):
    require_perm(user, "order.create")
    _assert_unlocked(db.get(BrewOrder, brew_order_id))
    brew_order_svc.delete_order(db, brew_order_id, user)


# ===== Chỉ tiêu chất lượng theo công đoạn (generic, scope-agnostic — dùng chung bởi pipeline
# "Mẻ sản xuất" mới qua scope_type="batch_tank"/"batch_filter_lot"/"batch_pack_lot") =====
@router.get("/qc-status")
def brewing_qc_status(stage: str, scope_type: str, scope_id: str, product_id: str = None,
                      finished_product_id: str = None, beer_type_id: str = None, db: Session = Depends(get_db)):
    return qc_catalog.stage_qc_status(db, stage, scope_type, scope_id, product_id,
                                      finished_product_id, beer_type_id)


@router.post("/qc-samples", status_code=201)
def add_qc_sample(payload: QcSampleIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Ghi 1 lần lấy mẫu (nhiều chỉ tiêu cùng lúc) cho CT chính/CT phụ lên men — xem
    qc_catalog.record_qc_sample. LUÔN thêm bản ghi mới, không ghi đè lần trước. Pipeline "Mẻ
    sản xuất" (scope_type="batch_tank") yêu cầu quyền "quality.release" — CHỈ KCS (tái dùng
    đúng quy ước đã dùng cho Duyệt LM/Lọc/Chiết, yêu cầu người dùng 2026-09-02: "chỉ cho nhân
    viên KCS được điền"); các scope khác giữ "batch.execute"."""
    require_perm(user, "quality.release" if payload.scope_type == "batch_tank" else "batch.execute")
    _assert_stage_scope_unlocked(db, payload.scope_type, payload.scope_id)
    return qc_catalog.record_qc_sample(db, payload.stage, payload.scope_type, payload.scope_id,
                                       payload.sampled_at, [r.model_dump() for r in payload.results], user)


@router.get("/qc-samples")
def get_qc_samples(scope_type: str, scope_id: str, db: Session = Depends(get_db)):
    """Lịch sử các lần lấy mẫu (mới nhất trước) cho 1 scope — xem qc_catalog.list_qc_samples."""
    return {"items": qc_catalog.list_qc_samples(db, scope_type, scope_id)}


# Chỉ tiêu lên men (chính/phụ) CỦA PIPELINE "MẺ SẢN XUẤT" (scope_type="batch_tank") là chỉ
# tiêu CHẤT LƯỢNG cần KCS ghi/xác nhận — tái dùng quyền "quality.release" (mirror quy ước đã
# dùng cho Duyệt LM/Lọc/Chiết, xem services/cip.py) thay vì "batch.execute" (cấp cho vận hành)
# — yêu cầu người dùng 2026-09-02: "chỉ cho nhân viên KCS được điền". Các stage khác
# (nau/loc/thanh_pham) giữ nguyên "batch.execute".
_KCS_ONLY_STAGES = ("len_men_chinh", "len_men_phu")


@router.post("/qc-results", status_code=201)
def add_stage_qc_result(payload: StageQcResultIn, db: Session = Depends(get_db),
                        user: User = Depends(get_current_user)):
    kcs_only = payload.stage in _KCS_ONLY_STAGES and payload.scope_type == "batch_tank"
    require_perm(user, "quality.release" if kcs_only else "batch.execute")
    data = payload.model_dump()
    stage, scope_type, scope_id = data.pop("stage"), data.pop("scope_type"), data.pop("scope_id")
    _assert_stage_scope_unlocked(db, scope_type, scope_id)
    return qc_catalog.record_stage_result(db, stage, scope_type, scope_id, data, user)
