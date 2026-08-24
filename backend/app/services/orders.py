"""Lệnh sản xuất (ERP) — production_order. SoR thực tế là ERP; ở đây chỉ thêm khả năng CHỌN
Công thức (RecipeVersion) + định mức NVL (BOM), mirror phần tương ứng của Lệnh nấu
(services/brew_order.py) nhưng KHÔNG có cấu trúc "lệnh nhỏ" (1 Lệnh SX = 1 dòng, không
master/children). Định mức NVL (production_order_material_line) snapshot tồn kho + SL lấy tại
Kho công ty/phân xưởng NGAY LÚC LẬP PHIẾU (người lập có thể sửa lại/chọn thành viên Nhóm vật tư
thay thế trước khi lưu qua material_qty_overrides, giống hệt Lệnh nấu) — mirror
brew_order_material_line/BrewOrder._insert_sub_order, chỉ khác không có cấu trúc lệnh nhỏ.

Cấu trúc link tới Mẻ sản xuất (BatchExecution) giữ nguyên như cũ: production_order.order_id
vẫn là khóa mà WorkOrder/BatchExecution tham chiếu tới (xem services/workorders.py,
services/batches.py) — thêm recipe_version_id/planned_batch_count không thay đổi gì ở đó."""

from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..audit import record_audit
from ..common import new_id, utcnow
from ..errors import DomainError, NotFoundError
from ..models.batches import BatchExecution
from ..models.brewing import BrewOrder, BrewRecord
from ..models.master import BeerType
from ..models.orders import ProductionOrder, ProductionOrderMaterialLine
from ..models.recipes import Recipe, RecipeVersion
from ..security import User
from . import ops_setting as ops_setting_svc
from .brew_order import (
    _actual_volume_hl,
    _all_batches_finished,
    _annotate_stock,
    _apply_qty_split_override,
    _assert_no_shortage,
    _line_stock,
    _materials_by_id,
    _member_breakdown,
    _member_declared_breakdown,
    _real_actual_by_brew,
    _record_summaries,
    _resolve_group_members,
    _stock_snapshot,
    _validate_member_selection,
    build_lines_from_recipe_version,
)


def _assert_not_executed(db: Session, order: ProductionOrder) -> None:
    """Chặn sửa/xóa khi đã có Mẻ sản xuất (BatchExecution) tạo từ lệnh này — mirror
    brew_order.py::update_master_order/delete_master_order (kiểm tra BrewRecord)."""
    if db.execute(select(BatchExecution.batch_id).where(BatchExecution.order_id == order.order_id)).first():
        raise DomainError(f"Lệnh {order.order_code} đã có Mẻ sản xuất — không thể sửa/xóa.")


def _delete_lines(db: Session, order_id: str) -> None:
    for l in db.execute(select(ProductionOrderMaterialLine).where(
            ProductionOrderMaterialLine.order_id == order_id)).scalars().all():
        db.delete(l)
    db.flush()  # MSSQL enforce FK: xóa dòng định mức (con) trước production_order (cha).


def _persist_lines(db: Session, order_id: str, recipe_version_id: Optional[str],
                    planned_batch_count: Optional[int], qty_overrides: dict) -> None:
    """Nạp định mức NVL từ Công thức + áp SL lấy/thành viên người lập đã tự sửa trong "Xem
    NVL", rồi lưu snapshot — mirror brew_order.py::_insert_sub_order (đoạn dựng
    BrewOrderMaterialLine), chỉ khác ghi vào ProductionOrderMaterialLine. Không làm gì nếu
    chưa chọn Công thức (Lệnh SX không bắt buộc phải gắn dịch bia/công thức)."""
    if not recipe_version_id:
        return
    qty_overrides = qty_overrides or {}
    member_selection = {k: v["selected_material_codes"] for k, v in qty_overrides.items()
                        if v.get("selected_material_codes") is not None}
    lines = build_lines_from_recipe_version(db, recipe_version_id, planned_batch_count or 1, 0.0, member_selection)
    if not lines:
        return
    _validate_member_selection(lines)
    company_stock, workshop_stock = _stock_snapshot(db)
    materials_by_id = _materials_by_id(db)
    _assert_no_shortage(lines, company_stock, workshop_stock, materials_by_id)
    for i, line in enumerate(lines):
        material_id = line.get("material_id")
        member_declared = line.get("member_declared")
        member_qty_snapshot = None
        if member_declared:
            member_splits_ov = (qty_overrides.get(str(line.get("seq", i))) or {}).get("member_qty_splits")
            member_qty_snapshot, _ = _member_declared_breakdown(
                member_declared, line.get("uom"), company_stock, workshop_stock, materials_by_id,
                member_qty_splits=member_splits_ov)
            company = sum(d["stock_company"] for d in member_qty_snapshot)
            workshop = sum(d["stock_workshop"] for d in member_qty_snapshot)
            has_target = True
            qty_from_company = qty_from_workshop = None
        else:
            has_target = bool(material_id or line.get("member_material_ids"))
            company, workshop = _line_stock(line, company_stock, workshop_stock, materials_by_id)
            qty_from_company, qty_from_workshop = _apply_qty_split_override(line, workshop, qty_overrides)
        db.add(ProductionOrderMaterialLine(
            line_id=new_id(), order_id=order_id, seq=line.get("seq", i),
            stt_label=line.get("stt_label"), is_header=line.get("is_header", False),
            material_id=material_id, material_name=line.get("material_name"), uom=line.get("uom"),
            material_group_code=line.get("material_group_code"),
            member_qty_snapshot=member_qty_snapshot,
            qty_per_batch=line.get("qty_per_batch"), qty_total=line.get("qty_total"),
            unit_price=line.get("unit_price"),
            stock_company_snapshot=company if has_target else None,
            stock_workshop_snapshot=workshop if has_target else None,
            qty_from_company=qty_from_company, qty_from_workshop=qty_from_workshop,
        ))


def _validate_recipe_version_selection(db: Session, beer_type_id: Optional[str], recipe_version_id: Optional[str]) -> None:
    """Mirror brew_order._validate_recipe_version_selection: recipe_version_id (nếu có) phải
    thuộc đúng Loại bia đã chọn (qua RecipeVersion.recipe_id -> Recipe.beer_type_id — Lệnh SX
    (ERP) giờ không còn product_id cố định lúc lập, xem models/orders.py) và đang `effective`."""
    if not recipe_version_id:
        return
    rv = db.get(RecipeVersion, recipe_version_id)
    if not rv:
        raise DomainError("Công thức đã chọn không tồn tại.")
    recipe = db.get(Recipe, rv.recipe_id)
    if not recipe or recipe.beer_type_id != beer_type_id:
        raise DomainError(f"Công thức (version {rv.version_no}) không thuộc Loại bia đã chọn.")
    if rv.state != "effective":
        raise DomainError(f"Công thức '{recipe.code}' version {rv.version_no} không còn hiệu lực.")


def _build_output_lines(db: Session, order_id: str) -> list:
    """Dựng lại `lines` để trả ra (Xem/In) từ snapshot đã lưu — mirror
    brew_order.py::get_master_order (đoạn dựng child_lines), member_breakdown tính lại theo
    TỒN KHO SỐNG (không phải lúc lập phiếu, khác stock_company_snapshot/stock_workshop_snapshot
    đã snapshot) để người xem biết tồn hiện tại của từng mã thành viên."""
    rows = db.execute(select(ProductionOrderMaterialLine).where(
        ProductionOrderMaterialLine.order_id == order_id).order_by(ProductionOrderMaterialLine.seq)).scalars().all()
    if not rows:
        return []
    live_company_stock, live_workshop_stock = _stock_snapshot(db)
    materials_by_id = _materials_by_id(db)
    out = []
    for l in rows:
        if l.member_qty_snapshot:
            member_breakdown = l.member_qty_snapshot
            member_ids = [mb["material_id"] for mb in member_breakdown if mb.get("material_id")]
        else:
            member_ids = _resolve_group_members(db, l.material_group_code)
            member_breakdown = _member_breakdown(member_ids, live_company_stock, live_workshop_stock, materials_by_id)
        out.append({
            "line_id": l.line_id, "seq": l.seq, "stt_label": l.stt_label, "is_header": l.is_header,
            "material_id": l.material_id, "material_name": l.material_name, "uom": l.uom,
            "material_group_code": l.material_group_code,
            "member_material_ids": member_ids,
            "member_breakdown": member_breakdown,
            "qty_per_batch": l.qty_per_batch, "qty_total": l.qty_total, "unit_price": l.unit_price,
            "stock_company_snapshot": l.stock_company_snapshot, "stock_workshop_snapshot": l.stock_workshop_snapshot,
            "qty_from_company": l.qty_from_company, "qty_from_workshop": l.qty_from_workshop,
            "shortage": False,
        })
    return out


def _enrich(db: Session, order: ProductionOrder, recipes_by_id: dict = None, versions_by_id: dict = None,
            executed_ids: set = None, with_lines: bool = False, beer_types_by_id: dict = None) -> dict:
    """recipes_by_id/versions_by_id/executed_ids/beer_types_by_id là bulk-lookup do list_orders()
    nạp sẵn (tránh N+1 query) — khi gọi lẻ (create_order/get_order, không truyền) thì tự query
    trực tiếp. with_lines=True (chỉ get_order) nạp thêm định mức NVL đã lưu — list_orders() để
    trống vì bảng danh sách không cần và tránh N+1 query nặng."""
    is_executed = order.order_id in executed_ids if executed_ids is not None else bool(
        db.execute(select(BatchExecution.batch_id).where(BatchExecution.order_id == order.order_id)).first())
    if not order.recipe_version_id:
        rv = None
    elif versions_by_id is not None:
        rv = versions_by_id.get(order.recipe_version_id)
    else:
        rv = db.get(RecipeVersion, order.recipe_version_id)
    if not rv:
        recipe = None
    elif recipes_by_id is not None:
        recipe = recipes_by_id.get(rv.recipe_id)
    else:
        recipe = db.get(Recipe, rv.recipe_id)
    # beer_type tra TRỰC TIẾP qua order.beer_type_id (chọn lúc lập lệnh, luôn có) — không còn
    # qua recipe/version nữa (thường None vì Lệnh SX (ERP) không còn chọn Version).
    if beer_types_by_id is not None:
        beer_type = beer_types_by_id.get(order.beer_type_id)
    else:
        beer_type = db.get(BeerType, order.beer_type_id) if order.beer_type_id else None
    return {
        "order_id": order.order_id, "order_code": order.order_code,
        "beer_type_id": order.beer_type_id, "product_id": order.product_id,
        "planned_qty": order.planned_qty, "uom": order.uom, "due_time": order.due_time,
        "priority": order.priority, "status": order.status, "source_version": order.source_version,
        "recipe_version_id": order.recipe_version_id,
        "recipe_code": recipe.code if recipe else None,
        "recipe_name": recipe.name if recipe else None,
        "beer_type_code": beer_type.code if beer_type else None,
        "beer_type_name": beer_type.name if beer_type else None,
        "recipe_version_no": rv.version_no if rv else None,
        "recipe_note": rv.change_reason if rv else None,
        "planned_batch_count": order.planned_batch_count,
        "issued_by": order.issued_by, "executor_unit": order.executor_unit,
        "warehouse_keeper": order.warehouse_keeper, "reference_note": order.reference_note,
        "start_date": order.start_date, "end_date": order.end_date, "safety_note": order.safety_note,
        "created_by": order.created_by,
        "created_at": order.created_at,
        "is_executed": is_executed,
        "lines": _build_output_lines(db, order.order_id) if with_lines else [],
    }


def list_orders(db: Session) -> list:
    orders = db.execute(select(ProductionOrder).order_by(ProductionOrder.created_at.desc())).scalars().all()
    rv_ids = {o.recipe_version_id for o in orders if o.recipe_version_id}
    versions_by_id = {v.version_id: v for v in db.execute(
        select(RecipeVersion).where(RecipeVersion.version_id.in_(rv_ids))).scalars().all()} if rv_ids else {}
    recipe_ids = {v.recipe_id for v in versions_by_id.values()}
    recipes_by_id = {r.recipe_id: r for r in db.execute(
        select(Recipe).where(Recipe.recipe_id.in_(recipe_ids))).scalars().all()} if recipe_ids else {}
    beer_type_ids = {o.beer_type_id for o in orders if o.beer_type_id}
    beer_types_by_id = {bt.beer_type_id: bt for bt in db.execute(
        select(BeerType).where(BeerType.beer_type_id.in_(beer_type_ids))).scalars().all()} if beer_type_ids else {}
    order_ids = {o.order_id for o in orders}
    executed_ids = {row[0] for row in db.execute(select(BatchExecution.order_id).where(
        BatchExecution.order_id.in_(order_ids))).all()} if order_ids else set()
    return [_enrich(db, o, recipes_by_id, versions_by_id, executed_ids, beer_types_by_id=beer_types_by_id) for o in orders]


def get_order(db: Session, order_id: str) -> dict:
    order = db.get(ProductionOrder, order_id)
    if not order:
        raise NotFoundError("Order không tồn tại.")
    return _enrich(db, order, with_lines=True)


def create_order(db: Session, payload: dict, user: User) -> dict:
    payload = dict(payload)
    order_code = payload["order_code"]
    if db.execute(select(ProductionOrder).where(ProductionOrder.order_code == order_code)).first():
        raise DomainError(f"Mã lệnh '{order_code}' đã tồn tại.")
    _validate_recipe_version_selection(db, payload.get("beer_type_id"), payload.get("recipe_version_id"))
    qty_overrides = payload.pop("material_qty_overrides", None) or {}
    order = ProductionOrder(order_id=new_id(), created_by=user.username, created_at=utcnow(), **payload)
    db.add(order)
    db.flush()
    _persist_lines(db, order.order_id, order.recipe_version_id, order.planned_batch_count, qty_overrides)
    record_audit(db, entity_type="order", entity_id=order.order_id, action="create",
                 actor=user, after={"order_code": order.order_code})
    db.commit()
    db.refresh(order)
    return _enrich(db, order, with_lines=True)


def update_order(db: Session, order_id: str, payload: dict, user: User) -> dict:
    payload = dict(payload)
    order = db.get(ProductionOrder, order_id)
    if not order:
        raise NotFoundError("Order không tồn tại.")
    _assert_not_executed(db, order)
    order_code = payload["order_code"]
    if order_code != order.order_code and db.execute(
            select(ProductionOrder).where(ProductionOrder.order_code == order_code)).first():
        raise DomainError(f"Mã lệnh '{order_code}' đã tồn tại.")
    _validate_recipe_version_selection(db, payload.get("beer_type_id"), payload.get("recipe_version_id"))
    qty_overrides = payload.pop("material_qty_overrides", None) or {}
    # CHỈ set field nào THỰC SỰ có mặt trong payload (router gọi payload.model_dump(exclude_
    # unset=True) — xem routers/orders.py::update_order) — PATCH-semantics cho các field hành
    # chính/công thức cũ (issued_by/executor_unit/.../recipe_version_id/planned_batch_count):
    # form Sửa lệnh (đơn giản hoá) không còn ô nhập cho chúng nên không gửi lên, phải GIỮ
    # NGUYÊN giá trị cũ thay vì bị ghi đè về None/default — chỉ client nào CHỦ ĐỘNG gửi field
    # đó (VD API/test cũ) mới thực sự thay đổi được. order_code/beer_type_id/planned_qty/uom/
    # priority bắt buộc (không có default) nên luôn có mặt, hành vi "full replace" như cũ.
    for field in ("order_code", "beer_type_id", "planned_qty", "uom", "due_time", "priority",
                  "source_version", "recipe_version_id", "planned_batch_count", "issued_by", "executor_unit",
                  "warehouse_keeper", "reference_note", "start_date", "end_date", "safety_note"):
        if field in payload:
            setattr(order, field, payload[field])
    _delete_lines(db, order_id)
    _persist_lines(db, order.order_id, order.recipe_version_id, order.planned_batch_count, qty_overrides)
    record_audit(db, entity_type="order", entity_id=order.order_id, action="update",
                 actor=user, after={"order_code": order.order_code})
    db.commit()
    db.refresh(order)
    return _enrich(db, order, with_lines=True)


def delete_order(db: Session, order_id: str, user: User) -> None:
    order = db.get(ProductionOrder, order_id)
    if not order:
        raise NotFoundError("Order không tồn tại.")
    _assert_not_executed(db, order)
    _delete_lines(db, order_id)
    record_audit(db, entity_type="order", entity_id=order.order_id, action="delete",
                 actor=user, before={"order_code": order.order_code})
    db.delete(order)
    db.commit()


def preview_bom(db: Session, recipe_version_id: str, planned_batch_count: int) -> list:
    """Xem trước định mức NVL (BOM) tự nạp từ 1 RecipeVersion + tồn kho hiện tại — TRƯỚC khi
    tạo Lệnh SX thật, mirror brew_order.preview_bom_lines_from_recipe_version."""
    lines = build_lines_from_recipe_version(db, recipe_version_id, planned_batch_count, 0.0)
    company_stock, workshop_stock = _stock_snapshot(db)
    return _annotate_stock(lines, company_stock, workshop_stock, _materials_by_id(db))


def _actual_volume_hl_for_order(db: Session, order_id: str) -> float:
    """Sản lượng thực tế (hl) cộng dồn từ TẤT CẢ mã nấu (BrewRecord) đã tạo qua Lệnh SX này —
    tái dùng nguyên _real_actual_by_brew (đo thật từ BrewProcessLog), KHÔNG cộng volume_hl
    nhập tay lúc tạo mã nấu. Mirror brew_order.py::_actual_volume_hl."""
    brew_ids = db.execute(select(BrewRecord.brew_id).where(
        BrewRecord.production_order_id == order_id)).scalars().all()
    if not brew_ids:
        return 0.0
    real_actual = _real_actual_by_brew(db, brew_ids)
    return round(sum(real_actual.values()), 3)


def _planned_qty_in_hl(order: ProductionOrder) -> float:
    """Quy đổi planned_qty (ĐVT tự do theo order.uom) về hl để so với sản lượng thực tế —
    giả định: uom "L" (lít) quy đổi /100, mọi ĐVT khác coi như đã là hl."""
    if order.uom and order.uom.strip().lower() == "l":
        return order.planned_qty / 100.0
    return order.planned_qty


def mark_in_progress(db: Session, order_id: str) -> None:
    """Gọi ngay sau khi tạo mã nấu ĐẦU TIÊN từ 1 Lệnh SX (ERP) — released -> in_progress. Không
    làm gì nếu lệnh đã ở trạng thái khác (in_progress/completed/cancelled)."""
    order = db.get(ProductionOrder, order_id)
    if order and order.status == "released":
        order.status = "in_progress"
        db.commit()


def recompute_status_after_finish(db: Session, order_id: str, user: User) -> None:
    """Gọi sau khi 1 mẻ nấu thuộc Lệnh SX này bấm "Kết thúc" — in_progress -> completed khi
    sản lượng thực tế đạt kế hoạch trừ sai số CHUNG (Cài đặt vận hành,
    erp_order_volume_tolerance_hl), KHÔNG cần chờ mọi mẻ kết thúc như BrewOrder (đơn giản hơn
    theo đúng yêu cầu — chỉ xét ngưỡng sản lượng)."""
    order = db.get(ProductionOrder, order_id)
    if not order or order.status != "in_progress":
        return
    tolerance = ops_setting_svc.get_settings(db).erp_order_volume_tolerance_hl
    actual = _actual_volume_hl_for_order(db, order_id)
    if actual >= _planned_qty_in_hl(order) - tolerance:
        order.status = "completed"
        record_audit(db, entity_type="order", entity_id=order.order_id, action="complete",
                     actor=user, after={"order_code": order.order_code, "actual_volume_hl": actual})
        db.commit()


def recompute_status_after_delete(db: Session, order_id: str, user: User) -> None:
    """Gọi sau khi XÓA 1 mã nấu gắn với Lệnh SX này — status tự động có thể lùi lại (khác
    recompute_status_after_finish chỉ tiến): hết sạch mã nấu -> về lại "released" (như chưa
    từng tạo mã nấu nào); còn mã nấu nhưng sản lượng thực tế rớt xuống dưới ngưỡng -> lùi từ
    "completed" về "in_progress". Không đụng "cancelled" (trạng thái người dùng tự chọn, không
    do sản lượng quyết định)."""
    order = db.get(ProductionOrder, order_id)
    if not order or order.status not in ("in_progress", "completed"):
        return
    remaining = db.execute(select(BrewRecord.brew_id).where(
        BrewRecord.production_order_id == order_id)).scalars().all()
    before_status = order.status
    if not remaining:
        order.status = "released"
    else:
        tolerance = ops_setting_svc.get_settings(db).erp_order_volume_tolerance_hl
        actual = _actual_volume_hl_for_order(db, order_id)
        is_complete = actual >= _planned_qty_in_hl(order) - tolerance
        order.status = "completed" if is_complete else "in_progress"
    if order.status != before_status:
        record_audit(db, entity_type="order", entity_id=order.order_id, action="revert_status",
                     actor=user, before={"status": before_status}, after={"status": order.status})
        db.commit()


def recompute_status_from_brew_order(db: Session, brew_order_id: str, user: User) -> None:
    """Gọi sau khi 1 mẻ thuộc Lệnh nấu (BrewOrder) này Kết thúc/bị xóa — nếu Lệnh nấu có Lệnh
    SX (ERP) cha (brew_order.production_order_id), tự chuyển cha completed/in_progress theo
    Lệnh nấu có hoàn thành hay không. LUÔN dùng sai số CHUNG (không phải volume_tolerance_hl
    riêng của Lệnh nấu — nhánh Lệnh nấu độc lập không gọi hàm này) — mirror đúng tiêu chí
    brew_order_svc._is_complete nhưng tự tính lại vì tolerance nguồn khác."""
    bo = db.get(BrewOrder, brew_order_id)
    if not bo or not bo.production_order_id:
        return
    order = db.get(ProductionOrder, bo.production_order_id)
    if not order or order.status not in ("in_progress", "completed"):
        return
    records = _record_summaries(db, brew_order_id)
    actual = _actual_volume_hl(records)
    tolerance = ops_setting_svc.get_settings(db).erp_order_volume_tolerance_hl
    is_complete = (actual >= bo.planned_volume_hl - tolerance
                  and _all_batches_finished(db, [r["brew_id"] for r in records]))
    before_status = order.status
    order.status = "completed" if is_complete else "in_progress"
    if order.status != before_status:
        record_audit(db, entity_type="order", entity_id=order.order_id,
                     action="complete" if order.status == "completed" else "revert_status",
                     actor=user, before={"status": before_status}, after={"status": order.status})
        db.commit()
