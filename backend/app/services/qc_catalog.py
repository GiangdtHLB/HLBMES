"""Danh mục nhóm chỉ tiêu chất lượng NVL + gán cho nguyên liệu (tài liệu §7.4, §7.5).

- QCParameterGroup/QCParameterGroupItem: nhóm chỉ tiêu (vd "Chỉ tiêu Malt Anh (bao)"),
  admin tạo trước rồi gán chỉ tiêu (QCParameter) vào nhóm.
- MaterialQcGroup: chỉ nguyên liệu có gán nhóm mới bị cổng nhập kho (services/warehouse.py)
  bắt buộc khai báo/duyệt chỉ tiêu trước khi được coi là nhập kho nhà máy chính thức.
"""

from sqlalchemy import func, select, true
from sqlalchemy.orm import Session

from ..audit import record_audit
from ..common import ResultStatus, new_id, utcnow
from ..errors import DomainError, NotFoundError
from ..models.batches import BatchExecution
from ..models.batch_pipeline import BatchFilterLot, BatchPackLot, BatchTank
from ..models.brewing import BottleRecord, BrewBatch, BrewRecord, FermentRecord, FilterRecord
from ..models.master import BeerType, Material, MaterialGroup
from ..models.materials import MaterialLot
from ..models.materials_ext import MaterialQcGroup
from ..models.quality import QualityResult
from ..models.quality_ext import QCParameter, QCParameterGroup, QCParameterGroupItem, StageQcGroup
from ..models.workorder import WorkOrder
from ..security import User, require_perm


# lm_code/filter_code/bottle_code chỉ duy nhất TRONG 1 năm (xem UniqueConstraint trên từng
# model) — scope_id ghép chuỗi cho QualityResult/Deviation PHẢI mang theo năm, nếu không 2 lô
# khác năm trùng mã (VD "LM-01" của 2026 và 2027) sẽ lẫn lộn kết quả QC của nhau.
def ferment_scope_id(lm_code: str, ferment_year: int, stage: str) -> str:
    return f"{ferment_year}-{lm_code}__{stage}"


def filter_scope_id(filter_code: str, filter_year: int) -> str:
    return f"{filter_year}-{filter_code}"


def bottle_scope_id(bottle_code: str, bottle_year: int) -> str:
    return f"{bottle_year}-{bottle_code}__thanh_pham"


def batch_tank_scope_id(tank_id: str, stage: str) -> str:
    """Mirror ferment_scope_id — BatchTank (Mẻ SX) cũng có 2 stage chỉ tiêu (len_men_chinh/
    len_men_phu) trên CÙNG 1 bản ghi, nên scope_id phải khác nhau theo stage để QualityResult
    không lẫn giữa 2 bộ chỉ tiêu (tank_id đã duy nhất toàn hệ thống, không cần ghép thêm năm)."""
    return f"{tank_id}__{stage}"


# ---- Nhóm chỉ tiêu ----

def list_groups(db: Session) -> list[QCParameterGroup]:
    return db.execute(select(QCParameterGroup).order_by(QCParameterGroup.code)).scalars().all()


def create_group(db: Session, payload: dict, user: User) -> QCParameterGroup:
    require_perm(user, "master.manage")
    if db.execute(select(QCParameterGroup).where(QCParameterGroup.code == payload["code"])).scalar_one_or_none():
        raise DomainError(f"Mã nhóm chỉ tiêu '{payload['code']}' đã tồn tại.")
    g = QCParameterGroup(group_id=new_id(), **payload)
    db.add(g)
    record_audit(db, entity_type="qc_parameter_group", entity_id=g.group_id, action="create",
                 actor=user, after={"code": g.code, "name": g.name})
    db.commit()
    db.refresh(g)
    return g


def update_group(db: Session, group_id: str, payload: dict, user: User) -> QCParameterGroup:
    require_perm(user, "master.manage")
    g = db.get(QCParameterGroup, group_id)
    if not g:
        raise NotFoundError("Nhóm chỉ tiêu không tồn tại.")
    before = {"code": g.code, "name": g.name, "note": g.note, "active": g.active}
    for k, v in payload.items():
        setattr(g, k, v)
    record_audit(db, entity_type="qc_parameter_group", entity_id=g.group_id, action="update",
                 actor=user, before=before, after=payload)
    db.commit()
    db.refresh(g)
    return g


def delete_group(db: Session, group_id: str, user: User) -> None:
    """Chỉ xóa được khi nhóm chưa gán cho nguyên liệu (MaterialQcGroup) hay công đoạn sản
    xuất (StageQcGroup) nào — tránh xóa "mồ côi" một nhóm đang được dùng để cổng nhập kho/
    duyệt công đoạn. Xóa kèm các chỉ tiêu trong nhóm (QCParameterGroupItem) vì chỉ có ý
    nghĩa gắn với nhóm này."""
    require_perm(user, "master.manage")
    g = db.get(QCParameterGroup, group_id)
    if not g:
        raise NotFoundError("Nhóm chỉ tiêu không tồn tại.")
    mat_links = db.execute(select(MaterialQcGroup).where(
        MaterialQcGroup.group_id == group_id, MaterialQcGroup.active == true())).scalars().all()
    stage_links = db.execute(select(StageQcGroup).where(
        StageQcGroup.group_id == group_id, StageQcGroup.active == true())).scalars().all()
    if mat_links or stage_links:
        parts = []
        if mat_links:
            parts.append(f"{len(mat_links)} nguyên liệu")
        if stage_links:
            parts.append(f"{len(stage_links)} công đoạn sản xuất")
        raise DomainError(f"Không thể xóa — nhóm chỉ tiêu đang được gán cho {' và '.join(parts)}. Hãy gỡ gán trước.")
    for item in db.execute(select(QCParameterGroupItem).where(QCParameterGroupItem.group_id == group_id)).scalars().all():
        db.delete(item)
    record_audit(db, entity_type="qc_parameter_group", entity_id=group_id, action="delete", actor=user,
                 before={"code": g.code, "name": g.name})
    db.delete(g)
    db.commit()


# ---- Chỉ tiêu trong nhóm ----

def _item_out(db: Session, item: QCParameterGroupItem) -> dict:
    param = db.get(QCParameter, item.param_id)
    return {
        "item_id": item.item_id, "group_id": item.group_id, "param_id": item.param_id,
        "seq": item.seq, "mandatory": item.mandatory,
        "target_override": item.target_override, "usl_override": item.usl_override,
        "lsl_override": item.lsl_override,
        "param_code": param.code if param else None,
        "param_name": param.name if param else None,
        "param_unit": param.unit if param else None,
    }


def list_items(db: Session, group_id: str) -> list[dict]:
    items = db.execute(
        select(QCParameterGroupItem).where(QCParameterGroupItem.group_id == group_id)
        .order_by(QCParameterGroupItem.seq)
    ).scalars().all()
    return [_item_out(db, it) for it in items]


def add_item(db: Session, group_id: str, payload: dict, user: User) -> dict:
    require_perm(user, "master.manage")
    if not db.get(QCParameterGroup, group_id):
        raise NotFoundError("Nhóm chỉ tiêu không tồn tại.")
    if not db.get(QCParameter, payload["param_id"]):
        raise NotFoundError("Chỉ tiêu không tồn tại.")
    item = QCParameterGroupItem(item_id=new_id(), group_id=group_id, **payload)
    db.add(item)
    record_audit(db, entity_type="qc_parameter_group_item", entity_id=item.item_id, action="create",
                 actor=user, after={"group_id": group_id, "param_id": payload["param_id"]})
    db.commit()
    db.refresh(item)
    return _item_out(db, item)


def copy_items(db: Session, target_group_id: str, source_group_id: str, user: User) -> list[dict]:
    """Copy toàn bộ chỉ tiêu (kèm min/max/bắt buộc riêng của nhóm nguồn) sang nhóm đích —
    chỉ cho phép khi nhóm đích đang RỖNG (chưa có chỉ tiêu nào), tránh copy chồng lên dữ liệu
    đã cấu hình sẵn của nhóm đích."""
    require_perm(user, "master.manage")
    if not db.get(QCParameterGroup, target_group_id):
        raise NotFoundError("Nhóm chỉ tiêu đích không tồn tại.")
    source = db.get(QCParameterGroup, source_group_id)
    if not source:
        raise NotFoundError("Nhóm chỉ tiêu nguồn không tồn tại.")
    if source_group_id == target_group_id:
        raise DomainError("Nhóm nguồn và nhóm đích phải khác nhau.")

    target_has_items = db.execute(
        select(QCParameterGroupItem.item_id).where(QCParameterGroupItem.group_id == target_group_id).limit(1)
    ).first()
    if target_has_items:
        raise DomainError("Nhóm đích đã có chỉ tiêu — chỉ có thể copy vào nhóm đang rỗng.")
    source_items = db.execute(
        select(QCParameterGroupItem).where(QCParameterGroupItem.group_id == source_group_id)
        .order_by(QCParameterGroupItem.seq)
    ).scalars().all()

    for it in source_items:
        new_item = QCParameterGroupItem(
            item_id=new_id(), group_id=target_group_id, param_id=it.param_id, seq=it.seq,
            mandatory=it.mandatory, target_override=it.target_override,
            usl_override=it.usl_override, lsl_override=it.lsl_override,
        )
        db.add(new_item)
    record_audit(db, entity_type="qc_parameter_group", entity_id=target_group_id, action="copy_items",
                 actor=user, after={"source_group_id": source_group_id, "copied": len(source_items)})
    db.commit()
    return list_items(db, target_group_id)


def update_item(db: Session, item_id: str, payload: dict, user: User) -> dict:
    require_perm(user, "master.manage")
    item = db.get(QCParameterGroupItem, item_id)
    if not item:
        raise NotFoundError("Chỉ tiêu trong nhóm không tồn tại.")
    for k, v in payload.items():
        setattr(item, k, v)
    record_audit(db, entity_type="qc_parameter_group_item", entity_id=item.item_id, action="update",
                 actor=user, after=payload)
    db.commit()
    db.refresh(item)
    return _item_out(db, item)


def delete_item(db: Session, item_id: str, user: User) -> None:
    require_perm(user, "master.manage")
    item = db.get(QCParameterGroupItem, item_id)
    if not item:
        raise NotFoundError("Chỉ tiêu trong nhóm không tồn tại.")
    db.delete(item)
    record_audit(db, entity_type="qc_parameter_group_item", entity_id=item_id, action="delete", actor=user)
    db.commit()


# ---- Gán nhóm chỉ tiêu cho nguyên liệu ----

def list_material_groups(db: Session, material_id: str) -> list[dict]:
    links = db.execute(
        select(MaterialQcGroup).where(MaterialQcGroup.material_id == material_id,
                                       MaterialQcGroup.active == true())
    ).scalars().all()
    out = []
    for link in links:
        g = db.get(QCParameterGroup, link.group_id)
        out.append({"link_id": link.link_id, "material_id": link.material_id, "group_id": link.group_id,
                    "mandatory": link.mandatory, "active": link.active,
                    "group_code": g.code if g else None, "group_name": g.name if g else None})
    return out


def link_material_group(db: Session, material_id: str, payload: dict, user: User) -> dict:
    require_perm(user, "master.manage")
    if not db.get(QCParameterGroup, payload["group_id"]):
        raise NotFoundError("Nhóm chỉ tiêu không tồn tại.")
    existing = db.execute(
        select(MaterialQcGroup).where(MaterialQcGroup.material_id == material_id,
                                       MaterialQcGroup.group_id == payload["group_id"])
    ).scalar_one_or_none()
    if existing:
        existing.mandatory = payload.get("mandatory", True)
        existing.active = True
        link = existing
    else:
        link = MaterialQcGroup(link_id=new_id(), material_id=material_id, **payload)
        db.add(link)
    record_audit(db, entity_type="material_qc_group", entity_id=link.link_id, action="link",
                 actor=user, after={"material_id": material_id, "group_id": payload["group_id"]})
    db.commit()
    db.refresh(link)
    g = db.get(QCParameterGroup, link.group_id)
    return {"link_id": link.link_id, "material_id": link.material_id, "group_id": link.group_id,
            "mandatory": link.mandatory, "active": link.active,
            "group_code": g.code if g else None, "group_name": g.name if g else None}


def unlink_material_group(db: Session, material_id: str, group_id: str, user: User) -> None:
    require_perm(user, "master.manage")
    link = db.execute(
        select(MaterialQcGroup).where(MaterialQcGroup.material_id == material_id,
                                       MaterialQcGroup.group_id == group_id)
    ).scalar_one_or_none()
    if not link:
        raise NotFoundError("Nguyên liệu chưa gán nhóm chỉ tiêu này.")
    link.active = False
    record_audit(db, entity_type="material_qc_group", entity_id=link.link_id, action="unlink", actor=user)
    db.commit()


# ---- Tra cứu dùng chung (cổng nhập kho + release) ----

def is_raw_material_group(db: Session, material_id: str) -> bool:
    """Vật tư có thuộc nhóm đánh dấu is_raw_material (Nguyên liệu chính/phụ) hay không — dùng
    để BẮT BUỘC toàn bộ nguyên liệu chính/phụ đi qua KCS kiểm soát khi nhập kho (xem
    requires_kcs_hold), kể cả khi vật tư đó CHƯA gán nhóm chỉ tiêu chất lượng nào (không có
    required_params_for_material) — mirror đúng cờ đã dùng để hiện cột "Giá trị CA" ở
    lot_qc_status()."""
    if not material_id:
        return False
    material = db.get(Material, material_id)
    if not material or not material.category:
        return False
    group = db.execute(select(MaterialGroup).where(MaterialGroup.code == material.category)).scalar_one_or_none()
    return bool(group and group.is_raw_material)


def requires_kcs_hold(db: Session, material_id: str) -> bool:
    """Lô của vật tư này có phải HOLD chờ KCS kiểm soát khi nhập/điều chuyển hay không — TRUE
    nếu có >=1 chỉ tiêu chất lượng bắt buộc, HOẶC vật tư thuộc nhóm Nguyên liệu chính/phụ
    (is_raw_material) dù chưa gán chỉ tiêu nào (khi đó KCS vẫn phải kiểm soát bằng cách điền
    Số lô KCS/Số LOT nhà cung cấp — xem services/quality.py::_assert_releasable)."""
    return bool(required_params_for_material(db, material_id)) or is_raw_material_group(db, material_id)


def required_params_for_material(db: Session, material_id: str, mandatory_only: bool = True) -> list[dict]:
    """Danh sách chỉ tiêu bắt buộc khai báo cho một nguyên liệu (rỗng nếu không gán nhóm nào)."""
    if not material_id:
        return []
    stmt = (
        select(QCParameterGroupItem, QCParameter)
        .join(MaterialQcGroup, MaterialQcGroup.group_id == QCParameterGroupItem.group_id)
        .join(QCParameter, QCParameter.param_id == QCParameterGroupItem.param_id)
        .where(MaterialQcGroup.material_id == material_id, MaterialQcGroup.active == true(),
               QCParameter.active == true())
    )
    if mandatory_only:
        stmt = stmt.where(QCParameterGroupItem.mandatory == true())
    rows = db.execute(stmt.order_by(QCParameterGroupItem.seq)).all()
    out = []
    for item, param in rows:
        out.append({
            "param_id": param.param_id, "code": param.code, "name": param.name, "unit": param.unit,
            "target": item.target_override if item.target_override is not None else param.target,
            "usl": item.usl_override if item.usl_override is not None else param.usl,
            "lsl": item.lsl_override if item.lsl_override is not None else param.lsl,
            "mandatory": item.mandatory, "value_type": param.value_type,
        })
    return out


def materials_with_required_qc(db: Session) -> list[str]:
    """material_id nào cần KCS kiểm soát (dùng để hiện nút "Xem chỉ tiêu" + khoá nút Duyệt khi
    lô đang on_hold ở các màn xuất/điều chuyển — tránh N+1 gọi qc-status/lô). Gồm 2 trường hợp:
    có >=1 chỉ tiêu chất lượng bắt buộc, HOẶC thuộc nhóm Nguyên liệu chính/phụ (is_raw_material —
    vẫn cần kiểm soát tối thiểu bằng Số lô KCS/Số LOT nhà cung cấp dù chưa gán chỉ tiêu nào)."""
    rows = db.execute(
        select(MaterialQcGroup.material_id)
        .join(QCParameterGroupItem, QCParameterGroupItem.group_id == MaterialQcGroup.group_id)
        .join(QCParameter, QCParameter.param_id == QCParameterGroupItem.param_id)
        .where(MaterialQcGroup.active == true(), QCParameterGroupItem.mandatory == true(),
               QCParameter.active == true())
        .distinct()
    ).scalars().all()
    raw_material_ids = db.execute(
        select(Material.material_id)
        .join(MaterialGroup, MaterialGroup.code == Material.category)
        .where(MaterialGroup.is_raw_material == true())
    ).scalars().all()
    return list(set(rows) | set(raw_material_ids))


def lot_qc_status(db: Session, lot: MaterialLot) -> dict:
    """Trạng thái khai báo/duyệt chỉ tiêu chất lượng của một lô NVL."""
    required = required_params_for_material(db, lot.material_id, mandatory_only=True)
    recorded = db.execute(
        select(QualityResult).where(QualityResult.scope_type == "lot", QualityResult.scope_id == lot.lot_id)
        .order_by(QualityResult.recorded_at)
    ).scalars().all()
    # Bản ghi MỚI NHẤT theo từng chỉ tiêu (ORDER BY recorded_at ASC rồi ghi đè tại chỗ — dict
    # giữ giá trị của lần lặp SAU CÙNG) — nhất quán với cách frontend (openLotQcModal) dùng
    # Object.fromEntries trên cùng mảng `recorded` để tính "giá trị hiện tại" của mỗi chỉ tiêu.
    latest_by_param = {}
    for r in recorded:
        latest_by_param[r.parameter] = r
    # "Đã khai báo" (không còn pending, đủ điều kiện release) phải có KẾT QUẢ THỰC (pass/fail)
    # — bản ghi chỉ có CA nhưng chưa từng đo giá trị thật (status=pending, value=None; xem
    # openLotQcModal cho phép lưu riêng CA không cần đo lại NẾU chỉ tiêu đó đã có giá trị đo
    # từ trước) KHÔNG được tính là đã khai báo, tránh cho duyệt lô khi chỉ tiêu bắt buộc chưa
    # từng có giá trị đo thực tế nào.
    pending = [p["code"] for p in required
              if latest_by_param.get(p["code"]) is None
              or latest_by_param[p["code"]].status == ResultStatus.PENDING.value]
    # Nhóm vật tư đánh dấu is_raw_material -> modal khai báo (openLotQcModal) hiện thêm cột
    # "Giá trị CA" (giá trị in trên bao bì NCC, khác giá trị nhà máy tự đo) — chỉ áp dụng cho
    # nguyên liệu chính/phụ, không áp dụng bao bì/vật tư khác. Nhóm này BẮT BUỘC phải có Số lô
    # KCS HOẶC Số LOT nhà cung cấp mới được duyệt (release) — kể cả khi không còn chỉ tiêu nào
    # đang pending — vì mọi lô NVL chính/phụ đều phải qua KCS kiểm soát tối thiểu ở mức này.
    is_raw_material = is_raw_material_group(db, lot.material_id)
    missing_lot_no = is_raw_material and not (lot.kcs_lot_no or lot.supplier_lot)
    return {
        "lot_id": lot.lot_id, "lot_code": lot.lot_code, "status": lot.status,
        "kcs_lot_no": lot.kcs_lot_no, "supplier_lot": lot.supplier_lot, "is_raw_material": is_raw_material,
        "required": required,
        "recorded": [{"parameter": r.parameter, "value": r.value, "value_text": r.value_text,
                      "ca_value": r.ca_value, "status": r.status,
                      "recorded_by": r.recorded_by, "recorded_at": r.recorded_at} for r in recorded],
        "pending": pending,
        "missing_lot_no": missing_lot_no,
        "can_release": not pending and not missing_lot_no,
    }


def missing_mandatory_params(db: Session, scope_type: str, scope_id: str) -> list[str]:
    """Dùng bởi services/quality.py::_assert_releasable — áp dụng cho scope 'lot' (lô NVL)
    và 'batch' (Mẻ sản xuất — BatchExecution, stage "nau"). Chỉ tiêu theo công đoạn sản xuất
    của module Nấu-Lọc-Chiết cũ (mẻ nấu/lên men/lọc/chiết) dùng stage_qc_status() riêng (gọi
    trực tiếp từ routers/brewing.py) vì cần biết `stage` cụ thể, không chỉ scope_id."""
    if scope_type == "lot":
        lot = db.get(MaterialLot, scope_id)
        if not lot:
            return []
        return lot_qc_status(db, lot)["pending"]
    if scope_type == "batch":
        batch = db.get(BatchExecution, scope_id)
        if not batch:
            return []
        return stage_qc_status(db, "nau", "batch", scope_id, product_id=batch.product_id)["pending"]
    return []


# ---- Gán nhóm chỉ tiêu cho công đoạn sản xuất (mẻ nấu/lên men chính/phụ/lọc/thành phẩm/
# nước nấu bia) ----
# Cùng cơ chế MaterialQcGroup ở trên, nhưng khoá theo (stage, product_id|beer_type_id) —
# product_id (Dịch bia) dùng cho PRODUCT_SCOPED_STAGES (phân biệt cả độ oP); beer_type_id
# (Loại bia — thương hiệu, không phân biệt oP) dùng cho BEER_TYPE_SCOPED_STAGES (loc,
# thanh_pham) vì lọc phối có thể gộp nhiều Dịch bia cùng 1 Loại bia (xem
# services/filter_order.py::_validate_tanks). Field không thuộc phạm vi stage đó luôn bị
# server bỏ qua (ép về NULL) khi lưu — tránh gán nhầm cột. Stage KHÔNG thuộc cả 2 tập này
# (VD "nuoc_nau" — chỉ tiêu nước nấu bia, dùng chung cho mọi loại bia) luôn có cả product_id
# lẫn beer_type_id = NULL — nhóm gán cho stage đó áp dụng cho MỌI mẻ nấu, không phân biệt
# dịch bia/loại bia.
PRODUCT_SCOPED_STAGES = {"nau", "len_men_chinh", "len_men_phu"}
BEER_TYPE_SCOPED_STAGES = {"loc", "thanh_pham"}
# finished_product_id (SKU cụ thể) có ý nghĩa ở "loc" và "thanh_pham" — cùng 1 Loại bia vẫn
# có thể cần chỉ tiêu Lọc khác nhau theo hình thức đóng gói đích (VD Legend chai lọc khác
# Legend tươi), khai báo 1 lần ở Lệnh lọc (FilterOrder.finished_product_id) và kế thừa xuống
# FilterRecord — mirror cách beer_type_id được kế thừa. Các stage còn lại (nau/lên men/nước
# nấu) ép về NULL vì không có khái niệm SKU ở đó.
SKU_SCOPED_STAGES = {"loc", "thanh_pham"}


def _stage_group_out(db: Session, link: StageQcGroup) -> dict:
    g = db.get(QCParameterGroup, link.group_id)
    bt = db.get(BeerType, link.beer_type_id) if link.beer_type_id else None
    return {"link_id": link.link_id, "stage": link.stage, "product_id": link.product_id,
            "beer_type_id": link.beer_type_id,
            "beer_type_code": bt.code if bt else None, "beer_type_name": bt.name if bt else None,
            "finished_product_id": link.finished_product_id,
            "group_id": link.group_id, "mandatory": link.mandatory, "active": link.active,
            "group_code": g.code if g else None, "group_name": g.name if g else None}


def list_stage_groups(db: Session, stage: str = None) -> list[dict]:
    stmt = select(StageQcGroup).where(StageQcGroup.active == true())
    if stage:
        stmt = stmt.where(StageQcGroup.stage == stage)
    links = db.execute(stmt).scalars().all()
    return [_stage_group_out(db, link) for link in links]


def link_stage_group(db: Session, payload: dict, user: User) -> dict:
    require_perm(user, "master.manage")
    if not db.get(QCParameterGroup, payload["group_id"]):
        raise NotFoundError("Nhóm chỉ tiêu không tồn tại.")
    # product_id (Dịch bia) chỉ có ý nghĩa cho PRODUCT_SCOPED_STAGES; beer_type_id (Loại
    # bia) chỉ có ý nghĩa cho BEER_TYPE_SCOPED_STAGES — ép field không thuộc phạm vi về NULL,
    # tránh gán nhầm cột theo đúng stage. Stage ngoài cả 2 tập (VD "nuoc_nau") luôn có cả 2
    # cột NULL = áp dụng chung cho mọi dịch bia/loại bia. finished_product_id (SKU cụ thể)
    # chỉ có ý nghĩa ở SKU_SCOPED_STAGES (loc, thanh_pham) — các stage khác ép về NULL.
    is_product_scoped = payload["stage"] in PRODUCT_SCOPED_STAGES
    is_beer_type_scoped = payload["stage"] in BEER_TYPE_SCOPED_STAGES
    product_id = (payload.get("product_id") or None) if is_product_scoped else None
    beer_type_id = (payload.get("beer_type_id") or None) if is_beer_type_scoped else None
    finished_product_id = (payload.get("finished_product_id") or None) if payload["stage"] in SKU_SCOPED_STAGES else None
    existing = db.execute(
        select(StageQcGroup).where(StageQcGroup.stage == payload["stage"],
                                   StageQcGroup.product_id == product_id,
                                   StageQcGroup.beer_type_id == beer_type_id,
                                   StageQcGroup.finished_product_id == finished_product_id,
                                   StageQcGroup.group_id == payload["group_id"])
    ).scalar_one_or_none()
    if existing:
        existing.mandatory = payload.get("mandatory", True)
        existing.active = True
        link = existing
    else:
        link = StageQcGroup(link_id=new_id(), stage=payload["stage"], product_id=product_id,
                            beer_type_id=beer_type_id,
                            finished_product_id=finished_product_id,
                            group_id=payload["group_id"], mandatory=payload.get("mandatory", True))
        db.add(link)
    record_audit(db, entity_type="stage_qc_group", entity_id=link.link_id, action="link",
                 actor=user, after={"stage": link.stage, "product_id": product_id,
                                    "beer_type_id": beer_type_id,
                                    "finished_product_id": finished_product_id, "group_id": payload["group_id"]})
    db.commit()
    db.refresh(link)
    return _stage_group_out(db, link)


def update_stage_group(db: Session, link_id: str, payload: dict, user: User) -> dict:
    require_perm(user, "master.manage")
    link = db.get(StageQcGroup, link_id)
    if not link:
        raise NotFoundError("Gán nhóm chỉ tiêu công đoạn không tồn tại.")
    if not db.get(QCParameterGroup, payload["group_id"]):
        raise NotFoundError("Nhóm chỉ tiêu không tồn tại.")
    # Cùng logic ép field theo stage như link_stage_group — sửa công đoạn cũng phải
    # scrub lại product_id/beer_type_id/finished_product_id cho khớp phạm vi mới.
    is_product_scoped = payload["stage"] in PRODUCT_SCOPED_STAGES
    is_beer_type_scoped = payload["stage"] in BEER_TYPE_SCOPED_STAGES
    product_id = (payload.get("product_id") or None) if is_product_scoped else None
    beer_type_id = (payload.get("beer_type_id") or None) if is_beer_type_scoped else None
    finished_product_id = (payload.get("finished_product_id") or None) if payload["stage"] in SKU_SCOPED_STAGES else None
    dup = db.execute(
        select(StageQcGroup).where(StageQcGroup.link_id != link_id, StageQcGroup.active == true(),
                                   StageQcGroup.stage == payload["stage"],
                                   StageQcGroup.product_id == product_id,
                                   StageQcGroup.beer_type_id == beer_type_id,
                                   StageQcGroup.finished_product_id == finished_product_id,
                                   StageQcGroup.group_id == payload["group_id"])
    ).scalar_one_or_none()
    if dup:
        raise DomainError("Đã có gán trùng công đoạn/phạm vi/nhóm chỉ tiêu này.")
    before = {"stage": link.stage, "product_id": link.product_id, "beer_type_id": link.beer_type_id,
              "finished_product_id": link.finished_product_id, "group_id": link.group_id,
              "mandatory": link.mandatory}
    link.stage = payload["stage"]
    link.product_id = product_id
    link.beer_type_id = beer_type_id
    link.finished_product_id = finished_product_id
    link.group_id = payload["group_id"]
    link.mandatory = payload.get("mandatory", True)
    record_audit(db, entity_type="stage_qc_group", entity_id=link.link_id, action="update",
                 actor=user, before=before, after={"stage": link.stage, "product_id": product_id,
                                                   "beer_type_id": beer_type_id,
                                                   "finished_product_id": finished_product_id,
                                                   "group_id": link.group_id, "mandatory": link.mandatory})
    db.commit()
    db.refresh(link)
    return _stage_group_out(db, link)


def unlink_stage_group(db: Session, link_id: str, user: User) -> None:
    require_perm(user, "master.manage")
    link = db.get(StageQcGroup, link_id)
    if not link:
        raise NotFoundError("Gán nhóm chỉ tiêu công đoạn không tồn tại.")
    link.active = False
    record_audit(db, entity_type="stage_qc_group", entity_id=link.link_id, action="unlink", actor=user)
    db.commit()


def required_params_for_stage(db: Session, stage: str, product_id: str = None,
                              finished_product_id: str = None, mandatory_only: bool = True,
                              beer_type_id: str = None) -> list[dict]:
    """Danh sách chỉ tiêu bắt buộc khai báo cho một công đoạn sản xuất (rỗng nếu chưa gán nhóm nào).
    Gộp cả nhóm gán riêng cho `product_id` (Dịch bia, chỉ áp dụng PRODUCT_SCOPED_STAGES)
    hoặc `beer_type_id` (Loại bia, các stage còn lại — VD loc/thanh_pham) / `finished_product_id`
    (sản phẩm đóng gói, chủ yếu dùng ở stage=thanh_pham) và nhóm áp dụng chung (field đó để
    NULL trên nhóm).

    Cùng 1 mã chỉ tiêu (QCParameter.code, duy nhất toàn hệ thống) có thể được gán qua NHIỀU
    nhóm khớp cùng lúc — VD 1 nhóm áp dụng chung (Loại bia, không chọn SKU) và 1 nhóm gán
    riêng cho đúng 1 SKU (finished_product_id) — mỗi nhóm có thể đặt ngưỡng
    (target/usl/lsl_override) khác nhau cho cùng mã đó. Nhóm gán CÀNG CỤ THỂ phải THẮNG hoàn
    toàn (không hiển thị trùng cả 2 dòng cho cùng 1 chỉ tiêu): khớp đúng finished_product_id
    được ưu tiên cao nhất, sau đó tới khớp đúng product_id/beer_type_id, thấp nhất là nhóm áp
    dụng chung (mọi field scope đều NULL). Đây cũng chính là nguồn dữ liệu cho mọi báo cáo/
    trạng thái chỉ tiêu (stage_qc_status, GET /qc-status, hồ sơ điện tử lot_record, tóm tắt QC
    trong genealogy) — sửa 1 chỗ này áp dụng nhất quán ở mọi nơi."""
    if not stage:
        return []
    stmt = (
        select(QCParameterGroupItem, QCParameter, StageQcGroup)
        .join(StageQcGroup, StageQcGroup.group_id == QCParameterGroupItem.group_id)
        .join(QCParameter, QCParameter.param_id == QCParameterGroupItem.param_id)
        .where(StageQcGroup.stage == stage, StageQcGroup.active == true(), QCParameter.active == true())
    )
    if stage in PRODUCT_SCOPED_STAGES:
        if product_id:
            stmt = stmt.where((StageQcGroup.product_id == product_id) | (StageQcGroup.product_id.is_(None)))
        else:
            stmt = stmt.where(StageQcGroup.product_id.is_(None))
    else:
        if beer_type_id:
            stmt = stmt.where((StageQcGroup.beer_type_id == beer_type_id) | (StageQcGroup.beer_type_id.is_(None)))
        else:
            stmt = stmt.where(StageQcGroup.beer_type_id.is_(None))
    if finished_product_id:
        stmt = stmt.where((StageQcGroup.finished_product_id == finished_product_id) |
                          (StageQcGroup.finished_product_id.is_(None)))
    else:
        stmt = stmt.where(StageQcGroup.finished_product_id.is_(None))
    if mandatory_only:
        stmt = stmt.where(QCParameterGroupItem.mandatory == true())
    rows = db.execute(stmt.order_by(QCParameterGroupItem.seq)).all()
    best_by_code: dict[str, dict] = {}
    for item, param, link in rows:
        specificity = (1 if link.finished_product_id else 0,
                      1 if (link.product_id or link.beer_type_id) else 0)
        current = best_by_code.get(param.code)
        if current is not None and specificity <= current["_specificity"]:
            continue
        best_by_code[param.code] = {
            "_specificity": specificity, "_seq": item.seq,
            "param_id": param.param_id, "code": param.code, "name": param.name, "unit": param.unit,
            "target": item.target_override if item.target_override is not None else param.target,
            "usl": item.usl_override if item.usl_override is not None else param.usl,
            "lsl": item.lsl_override if item.lsl_override is not None else param.lsl,
            "mandatory": item.mandatory, "value_type": param.value_type,
        }
    out = sorted(best_by_code.values(), key=lambda p: p["_seq"])
    for p in out:
        del p["_specificity"]; del p["_seq"]
    return out


def _evaluate_stage_result(value, lower, upper) -> str:
    if value is None:
        return "pending"
    if lower is not None and value < lower:
        return "fail"
    if upper is not None and value > upper:
        return "fail"
    return "pass"


def record_stage_result(db: Session, stage: str, scope_type: str, scope_id: str, payload: dict, user: User) -> dict:
    """Ghi 1 giá trị chỉ tiêu công đoạn sản xuất vào QualityResult dùng chung.
    Không đi qua services/quality.py::record_result vì hàm đó gắn với vòng đời
    batch/lot (tự động ON_HOLD khi FAIL) — không áp dụng cho bản ghi công đoạn
    (mẻ nấu/lô LM/lô lọc/mã chiết) vốn không có trạng thái quality_status riêng.
    Cập nhật đè lên bản ghi cũ nếu đã khai (cùng scope_type/scope_id/parameter) — chỉ tiêu công
    đoạn là "giá trị hiện tại", không tích lũy lịch sử; tránh 1 lần khai FAIL cũ còn sót lại
    mãi chặn duyệt dù giá trị mới đã đạt.

    NGOẠI LỆ scope_type="batch" (Mẻ sản xuất/BatchExecution qua stage "nau"): scope_id ở đây LÀ
    PK thật (batch_id, không ghép chuỗi như len_men_chinh/phu/loc/thanh_pham) nên CÓ quality_status
    riêng — sau khi ghi, thử attempt_auto_release() để đối xứng với FAIL tự động ON_HOLD (yêu cầu
    người dùng 2026-08-31: đủ chỉ tiêu bắt buộc + không FAIL treo thì tự release, không bắt QA bấm
    tay). Các scope_type khác giữ nguyên hành vi cũ (không quality_status)."""
    value = payload.get("value")
    value_text = payload.get("value_text")
    lower = payload.get("lower_limit")
    upper = payload.get("upper_limit")
    # Chỉ tiêu kiểu "text" — ghi chú tự do, không so target/USL/LSL, không tính pass/fail
    # (xem cùng quy ước ở services/quality.py::record_result).
    if value_text:
        status = "pass"
        value, lower, upper = None, None, None
    else:
        status = _evaluate_stage_result(value, lower, upper)
    result = db.execute(
        select(QualityResult).where(QualityResult.scope_type == scope_type, QualityResult.scope_id == scope_id,
                                    QualityResult.parameter == payload["parameter"])
    ).scalar_one_or_none()
    if result:
        result.value = value
        result.value_text = value_text
        result.unit = payload.get("unit")
        result.lower_limit = lower
        result.upper_limit = upper
        result.status = status
        result.recorded_by = user.username
        result.recorded_at = utcnow()
    else:
        result = QualityResult(
            result_id=new_id(), sample_id=f"S-{new_id()[:8].upper()}",
            scope_type=scope_type, scope_id=scope_id, parameter=payload["parameter"],
            value=value, value_text=value_text, unit=payload.get("unit"),
            lower_limit=lower, upper_limit=upper,
            status=status, recorded_by=user.username,
        )
        db.add(result)
    record_audit(db, entity_type="quality_result", entity_id=result.result_id, action="record",
                 actor=user, after={"stage": stage, "parameter": result.parameter, "value": value,
                                    "status": status, "scope": f"{scope_type}:{scope_id}"})
    if scope_type == "batch" and status != "fail":
        from . import quality
        quality.attempt_auto_release(db, scope_type, scope_id, user)
    db.commit()
    db.refresh(result)
    return {"parameter": result.parameter, "value": result.value, "value_text": result.value_text,
            "status": result.status, "recorded_by": result.recorded_by, "recorded_at": result.recorded_at}


def stage_qc_status(db: Session, stage: str, scope_type: str, scope_id: str, product_id: str = None,
                    finished_product_id: str = None, beer_type_id: str = None) -> dict:
    """Trạng thái khai báo chỉ tiêu của một bản ghi công đoạn (mẻ nấu/lô LM/lô lọc/mã chiết)
    — giá trị đã khai báo lưu ở QualityResult dùng chung (như lot_qc_status).
    Dùng latest_results_by_param (thay vì đọc thẳng mọi dòng) để CHỈ tính theo giá trị MỚI
    NHẤT/chỉ tiêu — bắt buộc với các stage lấy mẫu nhiều lần (len_men_chinh/len_men_phu,
    xem MULTI_SAMPLE_STAGES/record_qc_sample) vốn có NHIỀU dòng lịch sử cho cùng 1 chỉ tiêu;
    nếu không dedup, 1 lần FAIL cũ (đã đo lại PASS) sẽ chặn duyệt mãi mãi. Với các stage khác
    (chỉ có đúng 1 dòng/chỉ tiêu, ghi đè tại chỗ) hành vi không đổi.

    `required` trả về CẢ chỉ tiêu không bắt buộc (mandatory=False trên QCParameterGroupItem) —
    vẫn phải hiện trong bảng để nhập được (không bắt buộc khác với "ẩn hẳn đi"); chỉ khi tính
    pending/has_fail/can_release mới LỌC RIÊNG tập mandatory=True, đúng nghĩa "không bắt buộc"
    là không cần khai và không chặn duyệt vì nó."""
    from . import quality
    required = required_params_for_stage(db, stage, product_id=product_id,
                                         finished_product_id=finished_product_id, mandatory_only=False,
                                         beer_type_id=beer_type_id)
    latest_by_param = quality.latest_results_by_param(db, scope_type, scope_id)
    mandatory_codes = {p["code"] for p in required if p["mandatory"]}
    pending = [p["code"] for p in required if p["mandatory"] and p["code"] not in latest_by_param]
    has_fail = any(r.status == "fail" for code, r in latest_by_param.items() if code in mandatory_codes)
    return {
        "stage": stage, "scope_type": scope_type, "scope_id": scope_id,
        "required": required,
        "recorded": [{"parameter": r.parameter, "value": r.value, "value_text": r.value_text, "status": r.status,
                      "recorded_by": r.recorded_by, "recorded_at": r.recorded_at}
                     for r in latest_by_param.values()],
        "pending": pending,
        "has_fail": has_fail,
        "can_release": not pending and not has_fail,
    }


# ---- Lấy mẫu nhiều lần (lần 1/lần 2/...) cho CT chính/CT phụ lên men ----
# Khác record_stage_result (ghi đè tại chỗ, "giá trị hiện tại") — mỗi lần gọi LUÔN thêm dòng
# mới (không sửa/xóa dòng cũ), cùng 1 sample_id cho mọi chỉ tiêu khai trong CÙNG 1 lần lấy
# mẫu. Quyết định ĐẠT/FAIL để duyệt (stage_qc_status/qc_fail_count) vẫn chỉ theo giá trị MỚI
# NHẤT (xem latest_results_by_param) — lịch sử chỉ để xem lại, không dùng để chặn duyệt.
MULTI_SAMPLE_STAGES = {"len_men_chinh", "len_men_phu"}


def record_qc_sample(db: Session, stage: str, scope_type: str, scope_id: str,
                     sampled_at, results: list[dict], user: User) -> dict:
    """Ghi 1 LẦN lấy mẫu (nhiều chỉ tiêu cùng lúc, cùng 1 mốc ngày giờ) — luôn INSERT dòng
    mới, không tìm/ghi đè dòng cũ (khác record_stage_result)."""
    if stage not in MULTI_SAMPLE_STAGES:
        raise DomainError(f"Stage '{stage}' không hỗ trợ lấy mẫu nhiều lần.")
    if not results:
        raise DomainError("Chưa nhập giá trị chỉ tiêu nào.")
    sample_id = new_id()
    when = sampled_at or utcnow()
    rows = []
    for item in results:
        value = item.get("value")
        value_text = item.get("value_text")
        lower, upper = item.get("lower_limit"), item.get("upper_limit")
        if value_text:
            status, value, lower, upper = "pass", None, None, None
        else:
            status = _evaluate_stage_result(value, lower, upper)
        row = QualityResult(
            result_id=new_id(), sample_id=sample_id, scope_type=scope_type, scope_id=scope_id,
            parameter=item["parameter"], value=value, value_text=value_text, unit=item.get("unit"),
            lower_limit=lower, upper_limit=upper, status=status,
            recorded_by=user.username, sampled_at=when,
        )
        db.add(row)
        rows.append(row)
    record_audit(db, entity_type="quality_result", entity_id=sample_id, action="record_sample",
                actor=user, after={"stage": stage, "scope": f"{scope_type}:{scope_id}",
                                   "sampled_at": when.isoformat(),
                                   "results": [{"parameter": r["parameter"], "value": r.get("value")}
                                              for r in results]})
    db.commit()
    for row in rows:
        db.refresh(row)
    return {"sample_id": sample_id, "sampled_at": when,
            "results": [{"parameter": r.parameter, "value": r.value, "value_text": r.value_text,
                        "status": r.status} for r in rows]}


def merge_duplicate_qc_samples(db: Session, tolerance_seconds: float = 2.0) -> dict:
    """Gộp các "lần lấy mẫu" (sample_id) bị TÁCH VỤN thành nhiều bản ghi rời rạc — bug frontend
    cũ cho submit từng phần (từng chỉ tiêu 1) thay vì bắt buộc đủ cả bộ chỉ tiêu 1 lần (đã sửa,
    yêu cầu người dùng 2026-09-02: "lần 1 cũng phải gom lại"). CHỈ xét dòng có sampled_at khác
    NULL (đúng đặc trưng MULTI_SAMPLE_STAGES — mọi chỉ tiêu stage khác luôn NULL sampled_at, PHẢI
    loại trừ, nếu không sẽ gộp nhầm hàng loạt kết quả KHÔNG liên quan chỉ vì cùng NULL).

    Nhóm theo (scope_type, scope_id, recorded_by), sắp theo sampled_at, rồi GOM CỤM các dòng
    LIÊN TIẾP cách nhau ≤ `tolerance_seconds` (mặc định 2s — đủ rộng cho cả 2 dạng bug đã gặp:
    ô "Ngày giờ lấy mẫu" giữ nguyên giữa các lần bấm lưu dở dang → sampled_at giống hệt nhau, LẪN
    trường hợp mỗi lần bấm tự làm mới ô này → sampled_at chỉ lệch vài trăm mili-giây do submit
    dồn dập). 2 dòng khác sample_id trong CÙNG 1 cụm rõ ràng là cùng 1 lần lấy mẫu thật — gộp về
    1 sample_id duy nhất (giữ sample_id của dòng ghi SỚM NHẤT theo recorded_at). BỎ QUA cụm nào
    sau khi gộp sẽ bị TRÙNG mã chỉ tiêu (2 dòng khác sample_id nhưng cùng parameter) — đó có thể
    là 2 lần đo thật khác nhau trùng giờ (sửa lại giá trị), không phải do bug tách vụn, không tự
    ý gộp. Idempotent — gọi lại nhiều lần an toàn (sau khi gộp, mỗi cụm chỉ còn 1 sample_id, gap
    kế tiếp giữa các cụm thật luôn > tolerance_seconds nên không gộp thêm được nữa)."""
    rows = db.execute(select(QualityResult).where(QualityResult.sampled_at.is_not(None))).scalars().all()
    groups: dict[tuple, list[QualityResult]] = {}
    for r in rows:
        key = (r.scope_type, r.scope_id, r.recorded_by)
        groups.setdefault(key, []).append(r)
    merged_groups = 0
    merged_rows = 0
    for group_rows in groups.values():
        group_rows.sort(key=lambda r: r.sampled_at)
        clusters: list[list[QualityResult]] = []
        for r in group_rows:
            if clusters and (r.sampled_at - clusters[-1][-1].sampled_at).total_seconds() <= tolerance_seconds:
                clusters[-1].append(r)
            else:
                clusters.append([r])
        for cluster in clusters:
            if len({r.sample_id for r in cluster}) <= 1:
                continue
            params = [r.parameter for r in cluster]
            if len(params) != len(set(params)):
                continue
            canonical = min(cluster, key=lambda r: (r.recorded_at or r.sampled_at)).sample_id
            changed = False
            for r in cluster:
                if r.sample_id != canonical:
                    r.sample_id = canonical
                    merged_rows += 1
                    changed = True
            if changed:
                merged_groups += 1
    if merged_rows:
        db.commit()
    return {"merged_groups": merged_groups, "merged_rows": merged_rows}


def list_qc_samples(db: Session, scope_type: str, scope_id: str) -> list[dict]:
    """Lịch sử các lần lấy mẫu (mới nhất trước) cho 1 stage/scope — gộp theo sample_id.
    Tên/ĐVT chỉ tiêu tra theo QCParameter.code hiện tại (giới hạn min/max lấy từ chính dòng
    đã lưu — đúng ngưỡng áp dụng LÚC ghi, không lấy ngưỡng hiện tại có thể đã đổi)."""
    rows = db.execute(
        select(QualityResult).where(QualityResult.scope_type == scope_type, QualityResult.scope_id == scope_id)
    ).scalars().all()
    params_by_code = {p.code: p for p in db.execute(select(QCParameter)).scalars().all()}
    sessions: dict[str, dict] = {}
    for r in rows:
        eff_time = r.sampled_at or r.recorded_at
        s = sessions.setdefault(r.sample_id, {"sample_id": r.sample_id, "sampled_at": eff_time,
                                              "recorded_by": r.recorded_by, "results": []})
        p = params_by_code.get(r.parameter)
        s["results"].append({
            "parameter": r.parameter, "name": p.name if p else r.parameter, "unit": r.unit,
            "value_type": p.value_type if p else "numeric",
            "value": r.value, "value_text": r.value_text, "status": r.status,
            "lower_limit": r.lower_limit, "upper_limit": r.upper_limit,
        })
    return sorted(sessions.values(), key=lambda s: s["sampled_at"], reverse=True)


def list_pending_stage_declarations(db: Session) -> list[dict]:
    """Liệt kê các bản ghi công đoạn sản xuất (mẻ nấu/lô lên men chính+phụ/mẻ lọc/mã chiết)
    còn thiếu chỉ tiêu chất lượng bắt buộc — cùng vai trò với lot_qc_status (lô NVL) nhưng
    gộp cả 4 công đoạn thành 1 danh sách cho panel "chờ khai báo" ở tab Chất lượng. Chỉ những
    bản ghi CÓ nhóm chỉ tiêu bắt buộc gán vào stage đó (required non-empty) mới có thể lọt vào
    đây — required_params_for_stage trả về rỗng nếu stage/sản phẩm chưa được gán nhóm nào.

    TOÀN BỘ pipeline "Mẻ sản xuất" mới (Nấu/Lên men/Lọc/Chiết + Nước nấu bia theo WO) — LUÔN
    liệt kê, KHÔNG ẩn đi dù đã khai đủ (yêu cầu người dùng 2026-09-02: "khi khai xong công đoạn
    đó thì không cần ẩn đi nhé" — mở rộng từ hành vi ban đầu chỉ áp dụng riêng len_men_chinh/phu,
    vì giờ panel đã có cột "Xem chi tiết" nên không cần ẩn đi mới xem lại được). `pending` rỗng
    ở đây nghĩa là "đã khai báo đủ" (frontend hiện nhãn "Đã khai báo"), nút "Khai báo" vẫn giữ
    nguyên tác dụng SỬA giá trị đã khai (xem openStageQcModal — luôn hiện đủ mọi chỉ tiêu bắt
    buộc kèm giá trị hiện tại, không chỉ riêng phần còn thiếu). RIÊNG len_men_chinh/len_men_phu
    (MULTI_SAMPLE_STAGES — lấy mẫu LẶP LẠI) đổi hẳn nút thành "+ Thêm lần lấy mẫu" thay vì chỉ
    sửa đè, vì bản chất là thêm 1 lần mới chứ không ghi đè (xem MULTI_SAMPLE_STAGES ở dưới).
    Module Nấu-Lọc-Chiết CŨ (BrewBatch/FermentRecord/FilterRecord/BottleRecord) GIỮ NGUYÊN hành
    vi ẩn-khi-đã-đủ — không đổi, ngoài phạm vi yêu cầu."""
    out = []
    for b in db.execute(select(BatchExecution)).scalars().all():
        st = stage_qc_status(db, "nau", "batch", b.batch_id, product_id=b.product_id)
        if st["required"]:
            out.append({"stage": "nau", "stage_label": "Nấu (Mẻ SX)", "scope_type": "batch",
                       "scope_id": b.batch_id, "label": f"Mẻ SX {b.batch_code}",
                       "pending": st["pending"], "product_id": b.product_id})
    # Số lần đã lấy mẫu (đếm sample_id khác nhau) cho MỖI scope_id batch_tank — dùng để hiển thị
    # "+ Thêm lần lấy mẫu (lần N)" đúng số thứ tự thay vì chỉ ghi chung chung "thêm lần lấy mẫu"
    # (yêu cầu người dùng 2026-09-02: "Ghi rõ thêm lấy mẫu lần mấy").
    tank_sample_round_counts = dict(db.execute(
        select(QualityResult.scope_id, func.count(func.distinct(QualityResult.sample_id)))
        .where(QualityResult.scope_type == "batch_tank", QualityResult.sampled_at.is_not(None))
        .group_by(QualityResult.scope_id)
    ).all())
    for t in db.execute(select(BatchTank)).scalars().all():
        # Tank vật lý (t.tank_lm) tra từ Danh mục "Tank lên men" (ProductionLine kind="tank") lúc
        # gộp lô — PHẢI hiển thị tên này chứ không phải tank_code (mã LÔ tự sinh theo Lệnh SX,
        # VD "01"/"02"/"04", không nói lên tank vật lý nào — yêu cầu người dùng 2026-09-02:
        # "không rõ tank 01, 02, 04 là gì, tank men phải là lấy từ danh mục tank men chứ").
        tank_label = f"Tank {t.tank_lm} (Lô {t.tank_code})" if t.tank_lm else f"Lô {t.tank_code} (chưa gán tank vật lý)"
        for stage, part_label in (("len_men_chinh", "CT chính"), ("len_men_phu", "CT phụ")):
            scope_id = batch_tank_scope_id(t.tank_id, stage)
            st = stage_qc_status(db, stage, "batch_tank", scope_id, t.product_id)
            if st["required"] and (st["pending"] or stage in MULTI_SAMPLE_STAGES):
                out.append({"stage": stage, "stage_label": f"Lên men (Mẻ SX) — {part_label}",
                           "scope_type": "batch_tank", "scope_id": scope_id,
                           "label": f"{tank_label} — {part_label}", "pending": st["pending"],
                           "product_id": t.product_id,
                           "sample_round_count": tank_sample_round_counts.get(scope_id, 0)})
    brews = {r.brew_id: r for r in db.execute(select(BrewRecord)).scalars().all()}
    for b in db.execute(select(BrewBatch)).scalars().all():
        brew = brews.get(b.brew_id)
        st = stage_qc_status(db, "nau", "brew_batch", b.batch_id, brew.product_id if brew else None)
        if st["pending"]:
            out.append({"stage": "nau", "stage_label": "Nấu", "scope_type": "brew_batch", "scope_id": b.batch_id,
                       "label": f"Mẻ nấu {b.batch_code}" + (f" (mã nấu {brew.brew_code})" if brew else ""),
                       "pending": st["pending"], "product_id": brew.product_id if brew else None})
    # Nước nấu bia: 1 khai báo cho CẢ lô nấu (mã nấu/BrewRecord), không phải theo từng mẻ —
    # dùng chung cho mọi dịch bia nên KHÔNG truyền product_id (required_params_for_stage chỉ
    # khớp nhóm chỉ tiêu áp dụng chung, xem BEER_TYPE_SCOPED_STAGES ở trên).
    for brew in brews.values():
        st_water = stage_qc_status(db, "nuoc_nau", "brew", brew.brew_id)
        if st_water["pending"]:
            out.append({"stage": "nuoc_nau", "stage_label": "Nước nấu bia", "scope_type": "brew",
                       "scope_id": brew.brew_id, "label": f"Mã nấu {brew.brew_code} — Nước nấu",
                       "pending": st_water["pending"]})
    # Pipeline "Mẻ sản xuất" mới: Nước nấu bia khai theo MÃ ĐIỀU ĐỘ (WorkOrder), KHÔNG phải theo
    # từng Mẻ nấu (BatchExecution) — 1 WO có thể "Phát mẻ" nhiều lần ra nhiều mẻ nhưng vẫn dùng
    # chung 1 nguồn nước duy nhất (mirror đúng vai trò "mã nấu"/BrewRecord ở module cũ, yêu cầu
    # người dùng 2026-09-01: "trước đây khai báo ở mã nấu, ở đây cũng hiểu là cho 1 mã điều độ").
    for wo in db.execute(select(WorkOrder)).scalars().all():
        st_water_wo = stage_qc_status(db, "nuoc_nau", "work_order", wo.wo_id)
        if st_water_wo["required"]:
            out.append({"stage": "nuoc_nau", "stage_label": "Nước nấu bia", "scope_type": "work_order",
                       "scope_id": wo.wo_id, "label": f"WO {wo.wo_code} — Nước nấu",
                       "pending": st_water_wo["pending"]})
    for f in db.execute(select(FermentRecord)).scalars().all():
        for stage, part_label in (("len_men_chinh", "CT chính"), ("len_men_phu", "CT phụ")):
            scope_id = ferment_scope_id(f.lm_code, f.ferment_year, stage)
            st = stage_qc_status(db, stage, "ferment", scope_id, f.product_id)
            if st["pending"]:
                out.append({"stage": stage, "stage_label": f"Lên men — {part_label}", "scope_type": "ferment",
                           "scope_id": scope_id, "label": f"Lô lên men {f.lm_code} — {part_label}",
                           "pending": st["pending"], "product_id": f.product_id})
    for r in db.execute(select(FilterRecord)).scalars().all():
        scope_id = filter_scope_id(r.filter_code, r.filter_year)
        st = stage_qc_status(db, "loc", "filter", scope_id, r.product_id,
                             beer_type_id=r.beer_type_id, finished_product_id=r.finished_product_id)
        if st["pending"]:
            out.append({"stage": "loc", "stage_label": "Lọc", "scope_type": "filter", "scope_id": scope_id,
                       "label": f"Mẻ lọc {r.filter_code}", "pending": st["pending"],
                       "product_id": r.product_id, "beer_type_id": r.beer_type_id,
                       "finished_product_id": r.finished_product_id})
    # Lô lọc (Mẻ SX) — mirror khối FilterRecord trên nhưng cho pipeline mới (scope_id = chính
    # filter_lot_id, không cần ghép năm vì đã là khóa chính duy nhất toàn hệ thống, mirror cách
    # gọi có sẵn ở batch_pipeline.py::approve_filter_lot).
    for fl in db.execute(select(BatchFilterLot)).scalars().all():
        st = stage_qc_status(db, "loc", "batch_filter_lot", fl.filter_lot_id, fl.product_id,
                             beer_type_id=fl.beer_type_id, finished_product_id=fl.finished_product_id)
        if st["required"]:
            out.append({"stage": "loc", "stage_label": "Lọc (Mẻ SX)", "scope_type": "batch_filter_lot",
                       "scope_id": fl.filter_lot_id, "label": f"Lô lọc {fl.filter_lot_code}",
                       "pending": st["pending"], "product_id": fl.product_id,
                       "beer_type_id": fl.beer_type_id, "finished_product_id": fl.finished_product_id})
    for b in db.execute(select(BottleRecord)).scalars().all():
        scope_id = bottle_scope_id(b.bottle_code, b.bottle_year)
        st = stage_qc_status(db, "thanh_pham", "bottle", scope_id, b.product_id,
                             beer_type_id=b.beer_type_id, finished_product_id=b.finished_product_id)
        if st["pending"]:
            out.append({"stage": "thanh_pham", "stage_label": "Chiết", "scope_type": "bottle", "scope_id": scope_id,
                       "label": f"Mã chiết {b.bottle_code}", "pending": st["pending"],
                       "product_id": b.product_id, "beer_type_id": b.beer_type_id,
                       "finished_product_id": b.finished_product_id})
    # Lô thành phẩm (Mẻ SX) — mirror khối BottleRecord trên; product_id/beer_type_id kế thừa từ
    # BatchFilterLot nguồn (BatchPackLot không tự lưu 2 field này, mirror approve_pack_lot).
    filter_lots_by_id = {fl.filter_lot_id: fl for fl in db.execute(select(BatchFilterLot)).scalars().all()}
    for p in db.execute(select(BatchPackLot)).scalars().all():
        fl = filter_lots_by_id.get(p.filter_lot_id)
        st = stage_qc_status(db, "thanh_pham", "batch_pack_lot", p.pack_lot_id,
                             product_id=fl.product_id if fl else None,
                             beer_type_id=fl.beer_type_id if fl else None,
                             finished_product_id=p.finished_product_id)
        if st["required"]:
            out.append({"stage": "thanh_pham", "stage_label": "Chiết (Mẻ SX)", "scope_type": "batch_pack_lot",
                       "scope_id": p.pack_lot_id, "label": f"Lô TP {p.pack_lot_code}",
                       "pending": st["pending"], "product_id": fl.product_id if fl else None,
                       "beer_type_id": fl.beer_type_id if fl else None,
                       "finished_product_id": p.finished_product_id})
    return out
