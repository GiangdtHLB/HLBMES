"""Xóa danh mục gốc (Loại bia/Dịch bia/Vật tư/Sản phẩm thành phẩm/Dây chuyền-Tank) — chặn nếu
mã đó đã được tham chiếu ở bất kỳ đâu (kể cả lịch sử, không chỉ bản ghi đang active), vì đây là
dữ liệu gốc ảnh hưởng truy xuất nguồn gốc một khi đã có bản ghi trỏ tới (mirror
qc_catalog.py::delete_group)."""

import json

from sqlalchemy import delete as sa_delete
from sqlalchemy import func, select, true
from sqlalchemy.orm import Session

from ..audit import record_audit
from ..errors import DomainError, NotFoundError
from ..models.brewing import BrewOrder, BrewOrderMaterialLine
from ..models.batches import BatchExecution
from ..models.cip import CipEquipment
from ..models.lines import ProductionLine
from ..models.formula import Formula
from ..models.master import BeerType, FinishedProduct, Material, MaterialAltGroup, MaterialGroup, Product, UnitTypeCatalog
from ..models.materials import MaterialLot, Supplier
from ..models.materials_ext import MaterialQcGroup
from ..models.metrics import OEERecord
from ..models.oee_ext import DowntimeEvent
from ..models.quality_ext import StageQcGroup
from ..models.recipes import Recipe, RecipeVersion
from ..models.scheduling import ScheduleSlot
from ..models.warehouse import FactoryLocation, MaterialRequestLine, StockMovement
from ..models.workorder import WorkOrder
from ..security import User, require_perm


def _used_by(db: Session, checks: list) -> list:
    """Chạy từng (nhãn, câu lệnh đếm) — trả về danh sách "N nhãn" cho những nhãn có count>0."""
    parts = []
    for label, stmt in checks:
        n = db.execute(stmt).scalar() or 0
        if n:
            parts.append(f"{n} {label}")
    return parts


def _block_if_used(parts: list, kind: str, code: str) -> None:
    if parts:
        raise DomainError(f"Không thể xóa {kind} '{code}' — đang được dùng bởi "
                          f"{', '.join(parts)}. Hãy xóa/gỡ các mục đó trước.")


def delete_beer_type(db: Session, beer_type_id: str, user: User) -> None:
    require_perm(user, "master.manage")
    bt = db.get(BeerType, beer_type_id)
    if not bt:
        raise NotFoundError("Loại bia không tồn tại.")
    checks = [
        ("dịch bia", select(func.count(Product.product_id)).where(Product.beer_type_id == beer_type_id)),
        ("nhóm chỉ tiêu công đoạn", select(func.count(StageQcGroup.link_id)).where(
            StageQcGroup.beer_type_id == beer_type_id, StageQcGroup.active == true())),
    ]
    _block_if_used(_used_by(db, checks), "Loại bia", bt.code)
    record_audit(db, entity_type="beer_type", entity_id=bt.beer_type_id, action="delete",
                 actor=user, before={"code": bt.code, "name": bt.name})
    db.delete(bt)
    db.commit()


# Mã hệ thống bắt buộc phải luôn tồn tại trong Danh mục Loại đơn vị tồn kho (seed sẵn ở
# migration 1f8a7f187deb) — cấm xóa dù không còn dùng, vì code (không phải nhiều nơi trong
# services/wms.py hardcode so sánh trực tiếp "vi"/"keg"/"lon" (VD _decompose_one_vi luôn sinh
# unit_type="lon"), xóa mất dòng danh mục sẽ chỉ mất tên hiển thị chứ không tắt được hành vi đó
# — dễ gây hiểu lầm "đã xóa được loại vi/keg/lon" trong khi code vẫn phụ thuộc cứng vào chúng.
_SYSTEM_UNIT_TYPE_CODES = {"vi", "keg", "lon"}


def delete_unit_type(db: Session, unit_type_id: str, user: User) -> None:
    require_perm(user, "master.manage")
    ut = db.get(UnitTypeCatalog, unit_type_id)
    if not ut:
        raise NotFoundError("Loại đơn vị tồn kho không tồn tại.")
    if ut.code in _SYSTEM_UNIT_TYPE_CODES:
        raise DomainError(f"'{ut.name}' ({ut.code}) là loại hệ thống bắt buộc — không thể xóa.")
    checks = [
        ("sản phẩm (SKU)", select(func.count(FinishedProduct.finished_product_id)).where(
            FinishedProduct.unit_type == ut.code)),
    ]
    _block_if_used(_used_by(db, checks), "Loại đơn vị tồn kho", ut.code)
    record_audit(db, entity_type="unit_type_catalog", entity_id=ut.unit_type_id, action="delete",
                 actor=user, before={"code": ut.code, "name": ut.name})
    db.delete(ut)
    db.commit()


def delete_material_group(db: Session, group_id: str, user: User) -> None:
    require_perm(user, "master.manage")
    g = db.get(MaterialGroup, group_id)
    if not g:
        raise NotFoundError("Nhóm vật tư không tồn tại.")
    checks = [
        ("vật tư", select(func.count(Material.material_id)).where(Material.category == g.code)),
    ]
    _block_if_used(_used_by(db, checks), "Nhóm vật tư", g.code)
    record_audit(db, entity_type="material_group", entity_id=g.group_id, action="delete",
                 actor=user, before={"code": g.code, "name": g.name})
    db.delete(g)
    db.commit()


def group_unit_options(db: Session, member_material_ids: list[str]) -> list[str]:
    """Giao của các đơn vị mà MỌI thành viên đều khai được — mỗi vật tư khai được đơn vị chính
    (uom) và, nếu có, đơn vị phụ (alt_uom). Đây là danh sách hợp lệ để chọn làm 'đơn vị của
    nhóm' (MaterialAltGroup.unit) — dùng cả ở validate lúc tạo/sửa nhóm và ở màn hình chọn
    đơn vị nhóm trên frontend."""
    members = [db.get(Material, mid) for mid in member_material_ids]
    members = [m for m in members if m]
    if not members:
        return []
    common = None
    for m in members:
        opts = {m.uom} | ({m.alt_uom} if m.alt_uom else set())
        common = opts if common is None else (common & opts)
    return sorted(common or set())


def validate_alt_group_unit(db: Session, member_material_ids: list[str], unit: str) -> None:
    """Bắt buộc mọi thành viên nhóm vật tư thay thế phải cùng đơn vị (chính hoặc phụ), và đơn
    vị của nhóm phải là 1 trong số đơn vị chung đó — nếu không, tồn kho của các thành viên
    không thể cộng chung để so với số lượng cần dùng của công thức/lệnh (xem
    services/brew_order.py::_line_stock, services/filter_order.py::_validate_material_lines)."""
    options = group_unit_options(db, member_material_ids)
    if not options:
        raise DomainError(
            "Các vật tư thành viên không có đơn vị chung (đơn vị chính hoặc đơn vị phụ) — "
            "không thể tạo nhóm vật tư thay thế. Khai báo đơn vị phụ ở Danh mục Vật tư nếu cần.")
    if unit not in options:
        raise DomainError(f"Đơn vị của nhóm phải là 1 trong: {', '.join(options)}.")


def delete_material_alt_group(db: Session, group_id: str, user: User) -> None:
    """Chặn xóa nếu còn Công thức nào khai dòng NVL theo nhóm này (Formula.materials là JSON
    nên phải quét Python, không thể COUNT bằng SQL như các hàm xóa khác ở trên)."""
    require_perm(user, "master.manage")
    g = db.get(MaterialAltGroup, group_id)
    if not g:
        raise NotFoundError("Nhóm vật tư thay thế không tồn tại.")
    used_by_formulas = [
        f.code for f in db.execute(select(Formula)).scalars().all()
        if any((m or {}).get("alt_group_code") == g.code for m in (f.materials or []))
    ]
    if used_by_formulas:
        raise DomainError(
            f"Không thể xóa Nhóm vật tư thay thế '{g.code}' — đang được dùng trong công thức "
            f"{', '.join(used_by_formulas)}. Hãy sửa các công thức đó trước.")
    record_audit(db, entity_type="material_alt_group", entity_id=g.group_id, action="delete",
                 actor=user, before={"code": g.code, "name": g.name, "member_material_ids": g.member_material_ids})
    db.delete(g)
    db.commit()


def delete_supplier(db: Session, supplier_id: str, user: User) -> None:
    require_perm(user, "master.manage")
    sup = db.get(Supplier, supplier_id)
    if not sup:
        raise NotFoundError("Nhà cung cấp không tồn tại.")
    checks = [
        ("lô NVL", select(func.count(MaterialLot.lot_id)).where(MaterialLot.supplier_id == supplier_id)),
    ]
    _block_if_used(_used_by(db, checks), "Nhà cung cấp", sup.code)
    record_audit(db, entity_type="supplier", entity_id=sup.supplier_id, action="delete",
                 actor=user, before={"code": sup.code, "name": sup.name})
    db.delete(sup)
    db.commit()


def delete_factory_location(db: Session, factory_id: str, user: User) -> None:
    require_perm(user, "master.manage")
    fl = db.get(FactoryLocation, factory_id)
    if not fl:
        raise NotFoundError("Nhà máy không tồn tại.")
    checks = [
        ("giao dịch điều chuyển", select(func.count(StockMovement.movement_id)).where(
            StockMovement.destination_factory_id == factory_id)),
    ]
    _block_if_used(_used_by(db, checks), "Nhà máy", fl.code)
    record_audit(db, entity_type="factory_location", entity_id=fl.factory_id, action="delete",
                 actor=user, before={"code": fl.code, "name": fl.name})
    db.delete(fl)
    db.commit()


def delete_product(db: Session, product_id: str, user: User) -> None:
    require_perm(user, "master.manage")
    p = db.get(Product, product_id)
    if not p:
        raise NotFoundError("Dịch bia không tồn tại.")
    checks = [
        ("lệnh nấu", select(func.count(BrewOrder.brew_order_id)).where(BrewOrder.product_id == product_id)),
        ("lô hàng tồn kho", select(func.count(MaterialLot.lot_id)).where(MaterialLot.product_id == product_id)),
        ("sản phẩm thành phẩm", select(func.count(FinishedProduct.finished_product_id)).where(
            FinishedProduct.product_id == product_id)),
        ("nhóm chỉ tiêu công đoạn", select(func.count(StageQcGroup.link_id)).where(
            StageQcGroup.product_id == product_id, StageQcGroup.active == true())),
        ("work order", select(func.count(WorkOrder.wo_id)).where(WorkOrder.product_id == product_id)),
        ("version công thức", select(func.count(RecipeVersion.version_id)).where(
            RecipeVersion.product_id == product_id)),
        ("mẻ sản xuất (module cũ)", select(func.count(BatchExecution.batch_id)).where(
            BatchExecution.product_id == product_id)),
    ]
    _block_if_used(_used_by(db, checks), "Dịch bia", p.code)
    record_audit(db, entity_type="product", entity_id=p.product_id, action="delete",
                 actor=user, before={"code": p.code, "name": p.name})
    db.delete(p)
    db.commit()


def delete_material(db: Session, material_id: str, user: User) -> None:
    require_perm(user, "master.manage")
    m = db.get(Material, material_id)
    if not m:
        raise NotFoundError("Vật tư không tồn tại.")
    checks = [
        ("dòng vật tư lệnh nấu", select(func.count(BrewOrderMaterialLine.line_id)).where(
            BrewOrderMaterialLine.material_id == material_id)),
        ("lô hàng tồn kho", select(func.count(MaterialLot.lot_id)).where(MaterialLot.material_id == material_id)),
        ("gán nhóm chỉ tiêu QC", select(func.count(MaterialQcGroup.link_id)).where(
            MaterialQcGroup.material_id == material_id, MaterialQcGroup.active == true())),
        ("phiếu nhập/xuất kho", select(func.count(StockMovement.movement_id)).where(
            StockMovement.material_id == material_id)),
        ("đề nghị nhận kho", select(func.count(MaterialRequestLine.line_id)).where(
            MaterialRequestLine.material_id == material_id)),
    ]
    _block_if_used(_used_by(db, checks), "Vật tư", m.code)
    record_audit(db, entity_type="material", entity_id=m.material_id, action="delete",
                 actor=user, before={"code": m.code, "name": m.name})
    db.delete(m)
    db.commit()


def delete_finished_product(db: Session, finished_product_id: str, user: User) -> None:
    require_perm(user, "master.manage")
    fp = db.get(FinishedProduct, finished_product_id)
    if not fp:
        raise NotFoundError("Sản phẩm không tồn tại.")
    checks = [
        ("nhóm chỉ tiêu công đoạn", select(func.count(StageQcGroup.link_id)).where(
            StageQcGroup.finished_product_id == finished_product_id, StageQcGroup.active == true())),
    ]
    _block_if_used(_used_by(db, checks), "Sản phẩm", fp.code)
    record_audit(db, entity_type="finished_product", entity_id=fp.finished_product_id, action="delete",
                 actor=user, before={"code": fp.code, "name": fp.name})
    db.delete(fp)
    db.commit()


def delete_recipe(db: Session, recipe_id: str, user: User) -> None:
    """Xóa công thức + toàn bộ version bên trong — chỉ khi KHÔNG version nào đã từng được
    dùng (lệnh nấu/lệnh SX/work order/mẻ sản xuất tham chiếu recipe_version_id), vì batch
    SNAPSHOT dữ liệu version lúc release nên xóa version đã dùng sẽ mất khả năng tra cứu tại sao
    mẻ đó chạy theo thông số nào (tài liệu §4.2, §7.2 — models/recipes.py). Recipe giờ đại diện
    1 Loại bia (không còn 1 product_id duy nhất — mỗi version bên trong tự gắn 1 dịch bia riêng,
    xem models/recipes.py), nên chặn trực tiếp theo recipe_version_id (mirror đúng
    delete_recipe_version) thay vì suy qua product_id như trước."""
    require_perm(user, "master.manage")
    r = db.get(Recipe, recipe_id)
    if not r:
        raise NotFoundError("Công thức không tồn tại.")
    version_ids = db.execute(select(RecipeVersion.version_id).where(
        RecipeVersion.recipe_id == recipe_id)).scalars().all()
    checks = [
        ("lệnh nấu", select(func.count(BrewOrder.brew_order_id)).where(
            BrewOrder.recipe_version_id.in_(version_ids))),
        ("work order", select(func.count(WorkOrder.wo_id)).where(WorkOrder.recipe_version_id.in_(version_ids))),
        ("mẻ sản xuất (module cũ)", select(func.count(BatchExecution.batch_id)).where(
            BatchExecution.recipe_version_id.in_(version_ids))),
    ]
    _block_if_used(_used_by(db, checks), "Công thức", r.code)
    record_audit(db, entity_type="recipe", entity_id=r.recipe_id, action="delete",
                 actor=user, before={"code": r.code, "name": r.name, "versions": len(version_ids)})
    db.execute(sa_delete(RecipeVersion).where(RecipeVersion.recipe_id == recipe_id))
    db.delete(r)
    db.commit()


def used_recipe_version_ids(db: Session, version_ids: list) -> set:
    """Tập version_id ĐÃ được tham chiếu ở bất kỳ đâu (Lệnh nấu, work order, mẻ sản xuất module
    cũ) — dùng để ẨN nút "Xóa version" ở UI cho version đã dùng, thay vì hiện rồi bấm mới báo
    lỗi. Mirror đúng các bảng delete_recipe_version kiểm tra, không lặp logic khác (không tính
    message chi tiết, chỉ cần có/không)."""
    if not version_ids:
        return set()
    used = set()
    for model in (BrewOrder, WorkOrder, BatchExecution):
        used |= {row[0] for row in db.execute(
            select(model.recipe_version_id).where(model.recipe_version_id.in_(version_ids))).all()}
    return used


def delete_recipe_version(db: Session, version_id: str, user: User) -> None:
    """Xóa 1 version riêng lẻ (VD tạo nhầm lúc test) — không đụng tới version khác cùng công
    thức. Chặn nếu version này đã từng được tham chiếu ở bất kỳ đâu (Lệnh nấu, work order, hoặc
    mẻ sản xuất module cũ) — khác delete_recipe (chặn theo product_id vì BrewOrder trước đây
    không lưu recipe_version_id), giờ BrewOrder đã lưu thẳng recipe_version_id (xem
    services/brew_order.py) nên chặn trực tiếp theo version_id là đủ, không cần suy ra qua
    product_id nữa."""
    require_perm(user, "master.manage")
    v = db.get(RecipeVersion, version_id)
    if not v:
        raise NotFoundError("Version không tồn tại.")
    checks = [
        ("lệnh nấu", select(func.count(BrewOrder.brew_order_id)).where(BrewOrder.recipe_version_id == version_id)),
        ("work order", select(func.count(WorkOrder.wo_id)).where(WorkOrder.recipe_version_id == version_id)),
        ("mẻ sản xuất (module cũ)", select(func.count(BatchExecution.batch_id)).where(
            BatchExecution.recipe_version_id == version_id)),
    ]
    _block_if_used(_used_by(db, checks), "Version", f"v{v.version_no}")
    record_audit(db, entity_type="recipe_version", entity_id=v.version_id, action="delete",
                 actor=user, before={"recipe_id": v.recipe_id, "version_no": v.version_no, "state": v.state})
    db.delete(v)
    db.commit()


def delete_production_line(db: Session, line_id: str, user: User) -> None:
    """Mã dây chuyền/tank là text tự do (không phải FK thật) — chặn theo so khớp `code` trên
    mọi bảng có thể lưu mã đó, bất kể `kind` (line/tank/tank_bbt) để không sót cột."""
    require_perm(user, "master.manage")
    line = db.get(ProductionLine, line_id)
    if not line:
        raise NotFoundError("Dây chuyền/tank không tồn tại.")
    code = line.code
    checks = [
        ("work order (dây chuyền)", select(func.count(WorkOrder.wo_id)).where(WorkOrder.line == code)),
        ("bản ghi OEE", select(func.count(OEERecord.oee_id)).where(OEERecord.line == code)),
        ("sự kiện dừng máy", select(func.count(DowntimeEvent.event_id)).where(DowntimeEvent.line == code)),
        ("lịch sản xuất", select(func.count(ScheduleSlot.slot_id)).where(ScheduleSlot.resource == code)),
        ("lệnh nấu (tank LM)", select(func.count(BrewOrder.brew_order_id)).where(BrewOrder.tank_lm == code)),
        ("thiết bị CIP gắn tank/dây chuyền này", select(func.count(CipEquipment.equipment_id)).where(
            CipEquipment.production_line_id == line_id)),
    ]
    _block_if_used(_used_by(db, checks), "Dây chuyền/tank", code)
    record_audit(db, entity_type="line", entity_id=line.line_id, action="delete",
                 actor=user, before={"code": code, "name": line.name})
    db.delete(line)
    db.commit()


# ===== Quy định công nghệ nấu (Sapphire form QT-KCS-QT-BM-05) theo dịch bia =====
# Trước đây các field "Thực hiện" (vận hành ghi qua BrewProcessLog.manual_json, module
# Nấu-Lọc-Chiết cũ) sống cùng file với các field "Quy định" này (Product.spec_json, chỉ
# admin/master.manage sửa) vì cùng 1 biểu mẫu giấy có 2 cột — nay "Thực hiện" đã xóa cùng
# module cũ, chỉ còn "Quy định" (độc lập, không phụ thuộc bảng nào đã xóa). Danh sách key
# dưới đây PHẢI khớp đúng field có spec:true/tempSteps trong BF_SECTIONS (frontend/app.js).
SPEC_FIELD_KEYS: list[str] = [
    "rc_bot_gao_kg", "rc_nuoc_hl", "rc_ph_nuoc", "rc_termamyl_ml",
    "rc_step1_nhietdo", "rc_step2_nhietdo",
    "mt_malt_anh_kg", "mt_malt_uc_kg", "mt_malt_duc_kg", "mt_neutrase_ml",
    "mt_ultraprime_ml", "mt_cacl2_kg", "mt_caso4_kg", "mt_nuoc_hl", "mt_ph_nuoc",
    "mt_step1_nhietdo", "mt_step2_nhietdo", "mt_step3_nhietdo", "mt_step4_nhietdo", "mt_step5_nhietdo",
    "whp_chuyen_gio", "whp_thoi_gian_lang_phut", "whp_t0_chuyen_dich", "whp_oxy_lit_phut",
]


def _load_spec_json(text: str | None) -> dict:
    if not text:
        return {}
    try:
        parsed = json.loads(text)
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def get_spec_values(db: Session, product_id: str) -> dict:
    """Trả về đủ mọi key SPEC_FIELD_KEYS (None nếu chưa cấu hình)."""
    product = db.get(Product, product_id)
    if not product:
        raise NotFoundError("Sản phẩm không tồn tại.")
    stored = _load_spec_json(product.spec_json)
    return {k: stored.get(k) for k in SPEC_FIELD_KEYS}


def update_spec_values(db: Session, product_id: str, payload: dict, user: User) -> dict:
    require_perm(user, "master.manage")
    product = db.get(Product, product_id)
    if not product:
        raise NotFoundError("Sản phẩm không tồn tại.")
    values = _load_spec_json(product.spec_json)
    for key, value in payload.items():
        if key not in SPEC_FIELD_KEYS:
            continue
        if value is None:
            values.pop(key, None)
        else:
            values[key] = value
    product.spec_json = json.dumps(values, ensure_ascii=False)
    db.commit()
    return {k: values.get(k) for k in SPEC_FIELD_KEYS}
