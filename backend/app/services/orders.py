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

from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..audit import record_audit
from ..common import new_id, utcnow
from ..errors import DomainError, NotFoundError
from ..models.batches import BatchExecution
from ..models.orders import ProductionOrder, ProductionOrderMaterialLine
from ..models.recipes import Recipe, RecipeVersion
from ..security import User
from .brew_order import (
    _annotate_stock,
    _apply_qty_split_override,
    _assert_no_shortage,
    _line_stock,
    _materials_by_id,
    _member_breakdown,
    _member_declared_breakdown,
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


def _validate_recipe_version_selection(db: Session, product_id: Optional[str], recipe_version_id: Optional[str]) -> None:
    """Mirror brew_order._validate_recipe_version_selection: recipe_version_id (nếu có) phải
    thuộc đúng Recipe của sản phẩm đã chọn và đang ở trạng thái `effective`."""
    if not recipe_version_id:
        return
    rv = db.get(RecipeVersion, recipe_version_id)
    if not rv:
        raise DomainError("Công thức đã chọn không tồn tại.")
    recipe = db.get(Recipe, rv.recipe_id)
    if not recipe or recipe.product_id != product_id:
        raise DomainError(f"Công thức (version {rv.version_no}) không thuộc Sản phẩm đã chọn.")
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
            executed_ids: set = None, with_lines: bool = False) -> dict:
    """recipes_by_id/versions_by_id/executed_ids là bulk-lookup do list_orders() nạp sẵn (tránh
    N+1 query) — khi gọi lẻ (create_order/get_order, không truyền) thì tự query trực tiếp.
    with_lines=True (chỉ get_order) nạp thêm định mức NVL đã lưu — list_orders() để trống vì
    bảng danh sách không cần và tránh N+1 query nặng."""
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
    return {
        "order_id": order.order_id, "order_code": order.order_code, "product_id": order.product_id,
        "planned_qty": order.planned_qty, "uom": order.uom, "due_time": order.due_time,
        "priority": order.priority, "status": order.status, "source_version": order.source_version,
        "recipe_version_id": order.recipe_version_id,
        "recipe_code": recipe.code if recipe else None,
        "recipe_name": recipe.name if recipe else None,
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
    order_ids = {o.order_id for o in orders}
    executed_ids = {row[0] for row in db.execute(select(BatchExecution.order_id).where(
        BatchExecution.order_id.in_(order_ids))).all()} if order_ids else set()
    return [_enrich(db, o, recipes_by_id, versions_by_id, executed_ids) for o in orders]


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
    _validate_recipe_version_selection(db, payload.get("product_id"), payload.get("recipe_version_id"))
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
    _validate_recipe_version_selection(db, payload.get("product_id"), payload.get("recipe_version_id"))
    qty_overrides = payload.pop("material_qty_overrides", None) or {}
    for field in ("order_code", "product_id", "planned_qty", "uom", "due_time", "priority", "source_version",
                  "recipe_version_id", "planned_batch_count", "issued_by", "executor_unit", "warehouse_keeper",
                  "reference_note", "start_date", "end_date", "safety_note"):
        setattr(order, field, payload.get(field))
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
